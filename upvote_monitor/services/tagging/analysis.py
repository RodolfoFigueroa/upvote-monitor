import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from sqlmodel import Session, col, select

from upvote_monitor.db.models import (
    AnalysisProfile,
    AppSettings,
    MediaAnalysis,
    MediaAttachment,
    ReviewItem,
)
from upvote_monitor.enums import AnalysisStatus, ApprovalStatus
from upvote_monitor.services.preview_cache import (
    get_or_fetch_cached_preview,
    is_cacheable_preview_url,
)
from upvote_monitor.services.media_workflow import set_media_decision
from upvote_monitor.services.tagging.scoring import score_illustration
from upvote_monitor.services.tagging.profiles import active_analysis_profile
from upvote_monitor.services.tagging.pixai_tagger import (
    PIXAI_TAGGER_V0_9_ONNX_REPO_ID,
    get_pixai_tagger,
)
from upvote_monitor.services.tagging.wd_tagger import WDTaggerResult, get_wd_tagger

logger = logging.getLogger(__name__)


class ImageTagger(Protocol):
    model_name: str
    model_version: str

    def tag_image(self, path: Path) -> WDTaggerResult:
        pass


class TaggerUnavailableError(RuntimeError):
    pass


@dataclass
class AnalysisBatchResult:
    analyzed: int = 0
    skipped: int = 0
    failed: int = 0
    approved: int = 0


@dataclass(frozen=True)
class ItemAnalysisSummary:
    status: str | None
    illustration_score: float | None


def process_pending_analysis(
    session: Session,
    tagger: ImageTagger | None = None,
) -> AnalysisBatchResult:
    settings = session.get(AppSettings, 1)
    if settings is None or not settings.illustration_tagger_enabled:
        return AnalysisBatchResult()

    profile = active_analysis_profile(session)
    if profile is None:
        logger.error("No active illustration analysis profile is configured")
        return AnalysisBatchResult()

    if tagger is None:
        try:
            tagger = _default_tagger(profile)
        except TaggerUnavailableError:
            logger.exception("Illustration tagger could not be initialized")
            return AnalysisBatchResult()

    result = AnalysisBatchResult()
    items = session.exec(
        select(ReviewItem).where(
            ReviewItem.approval_status == ApprovalStatus.UNDER_REVIEW
        )
    ).all()

    for item in items:
        item_result = _analyze_item(
            session,
            item,
            profile,
            tagger,
            force=False,
            auto_approve_threshold=(
                profile.auto_approve_threshold
                if settings.illustration_auto_approve_enabled
                else None
            ),
        )
        result.analyzed += item_result.analyzed
        result.skipped += item_result.skipped
        result.failed += item_result.failed
        result.approved += item_result.approved

    session.commit()
    return result


def analyze_item(
    session: Session,
    item: ReviewItem,
    tagger: ImageTagger | None = None,
) -> AnalysisBatchResult:
    profile = active_analysis_profile(session)
    if profile is None:
        msg = "No active illustration analysis profile is configured"
        raise TaggerUnavailableError(msg)

    if tagger is None:
        tagger = _default_tagger(profile)

    result = _analyze_item(
        session,
        item,
        profile,
        tagger,
        force=True,
        auto_approve_threshold=None,
    )
    session.commit()
    return result


def analyze_attachment(
    session: Session,
    attachment: MediaAttachment,
    tagger: ImageTagger | None = None,
) -> MediaAnalysis:
    profile = active_analysis_profile(session)
    if profile is None:
        msg = "No active illustration analysis profile is configured"
        raise TaggerUnavailableError(msg)

    item = session.get(ReviewItem, attachment.item_id)
    if item is None:
        msg = "Media item source post could not be found"
        raise TaggerUnavailableError(msg)

    if tagger is None:
        tagger = _default_tagger(profile)

    existing = (
        _existing_analysis(session, attachment.id, profile) if attachment.id else None
    )
    analysis = _analyze_attachment(item, attachment, profile, tagger)
    if existing is not None:
        _replace_analysis(existing, analysis)
        analysis = existing
    else:
        session.add(analysis)

    session.commit()
    return analysis


def get_attachment_analysis(
    session: Session,
    attachment_id: int | None,
) -> MediaAnalysis | None:
    if attachment_id is None:
        return None
    profile = active_analysis_profile(session)
    if profile is None:
        return None
    return session.exec(
        select(MediaAnalysis)
        .where(MediaAnalysis.attachment_id == attachment_id)
        .where(MediaAnalysis.analysis_profile_id == profile.id)
        .order_by(col(MediaAnalysis.analyzed_at).desc())
    ).first()


def get_attachment_analyses(
    session: Session,
    attachment_id: int | None,
) -> list[MediaAnalysis]:
    if attachment_id is None:
        return []
    return list(
        session.exec(
            select(MediaAnalysis)
            .where(MediaAnalysis.attachment_id == attachment_id)
            .order_by(col(MediaAnalysis.analyzed_at).desc())
        ).all()
    )


def get_item_analysis_summary(
    session: Session,
    item_id: str,
) -> ItemAnalysisSummary:
    profile = active_analysis_profile(session)
    if profile is None:
        return ItemAnalysisSummary(status=None, illustration_score=None)

    rows = session.exec(
        select(MediaAnalysis)
        .join(
            MediaAttachment,
            col(MediaAttachment.id) == col(MediaAnalysis.attachment_id),
        )
        .where(MediaAttachment.item_id == item_id)
        .where(MediaAnalysis.analysis_profile_id == profile.id)
    ).all()
    if not rows:
        return ItemAnalysisSummary(status=None, illustration_score=None)

    scores = [
        row.illustration_score
        for row in rows
        if row.status == AnalysisStatus.COMPLETED and row.illustration_score is not None
    ]
    if scores:
        return ItemAnalysisSummary(
            status=AnalysisStatus.COMPLETED.value,
            illustration_score=max(scores),
        )

    statuses = {row.status for row in rows}
    if AnalysisStatus.FAILED in statuses:
        return ItemAnalysisSummary(
            status=AnalysisStatus.FAILED.value,
            illustration_score=None,
        )
    if AnalysisStatus.SKIPPED in statuses:
        return ItemAnalysisSummary(
            status=AnalysisStatus.SKIPPED.value,
            illustration_score=None,
        )
    return ItemAnalysisSummary(status=None, illustration_score=None)


def _image_attachments_for_item(
    session: Session,
    item_id: str,
) -> list[MediaAttachment]:
    return list(
        session.exec(
            select(MediaAttachment)
            .where(MediaAttachment.item_id == item_id)
            .where(MediaAttachment.media_type == "image")
            .order_by(col(MediaAttachment.sort_index))
        ).all()
    )


def _analyze_item(
    session: Session,
    item: ReviewItem,
    profile: AnalysisProfile,
    tagger: ImageTagger,
    *,
    force: bool,
    auto_approve_threshold: float | None,
) -> AnalysisBatchResult:
    result = AnalysisBatchResult()
    attachments = _image_attachments_for_item(session, item.id)

    for attachment in attachments:
        if attachment.id is None:
            continue
        existing = _existing_analysis(session, attachment.id, profile)
        if existing is not None and not force:
            if _maybe_auto_approve_attachment(
                session,
                attachment,
                existing.illustration_score,
                auto_approve_threshold,
            ):
                result.approved += 1
            continue

        analysis = _analyze_attachment(
            item,
            attachment,
            profile,
            tagger,
        )
        if existing is not None:
            _replace_analysis(existing, analysis)
            analysis = existing
        else:
            session.add(analysis)

        if analysis.status == AnalysisStatus.COMPLETED:
            result.analyzed += 1
            if _maybe_auto_approve_attachment(
                session,
                attachment,
                analysis.illustration_score,
                auto_approve_threshold,
            ):
                result.approved += 1
        elif analysis.status == AnalysisStatus.SKIPPED:
            result.skipped += 1
        elif analysis.status == AnalysisStatus.FAILED:
            result.failed += 1

    return result


def _existing_analysis(
    session: Session,
    attachment_id: int,
    profile: AnalysisProfile,
) -> MediaAnalysis | None:
    return session.exec(
        select(MediaAnalysis)
        .where(MediaAnalysis.attachment_id == attachment_id)
        .where(MediaAnalysis.analysis_profile_id == profile.id)
    ).first()


def _analyze_attachment(
    item: ReviewItem,
    attachment: MediaAttachment,
    profile: AnalysisProfile,
    tagger: ImageTagger,
) -> MediaAnalysis:
    assert attachment.id is not None
    preview_url = attachment.preview_url or attachment.download_url
    if not is_cacheable_preview_url(preview_url):
        return _analysis_result(
            attachment.id,
            profile,
            AnalysisStatus.SKIPPED,
            error="Preview URL is not cacheable",
        )

    try:
        image_path = get_or_fetch_cached_preview(
            item.id,
            attachment.sort_index,
            preview_url,
        )
        tagger_result = tagger.tag_image(image_path)
    except Exception as exc:
        return _analysis_result(
            attachment.id,
            profile,
            AnalysisStatus.FAILED,
            error=str(exc),
        )

    score = score_illustration(
        tagger_result.general_tags,
        tagger_result.character_tags,
        tagger_result.ratings,
    )
    general_tags = _filter_scores(
        tagger_result.general_tags,
        threshold=profile.general_tag_storage_threshold,
    )
    character_tags = _filter_scores(
        tagger_result.character_tags,
        threshold=profile.character_tag_storage_threshold,
    )
    return _analysis_result(
        attachment.id,
        profile,
        AnalysisStatus.COMPLETED,
        illustration_score=score,
        general_tags_json=json.dumps(general_tags, sort_keys=True),
        character_tags_json=json.dumps(character_tags, sort_keys=True),
        ratings_json=json.dumps(
            _filter_scores(tagger_result.ratings, threshold=0.0),
            sort_keys=True,
        ),
    )


def _analysis_result(
    attachment_id: int,
    profile: AnalysisProfile,
    status: AnalysisStatus,
    *,
    illustration_score: float | None = None,
    general_tags_json: str = "{}",
    character_tags_json: str = "{}",
    ratings_json: str = "{}",
    error: str | None = None,
) -> MediaAnalysis:
    return MediaAnalysis(
        attachment_id=attachment_id,
        analysis_profile_id=profile.id,
        model_name=profile.model_name,
        model_version=profile.model_version,
        scoring_version=profile.scoring_version,
        status=status,
        illustration_score=illustration_score,
        general_tags_json=general_tags_json,
        character_tags_json=character_tags_json,
        ratings_json=ratings_json,
        error=error,
        analyzed_at=datetime.now(timezone.utc),
    )


def _replace_analysis(target: MediaAnalysis, source: MediaAnalysis) -> None:
    target.analysis_profile_id = source.analysis_profile_id
    target.model_name = source.model_name
    target.model_version = source.model_version
    target.scoring_version = source.scoring_version
    target.status = source.status
    target.illustration_score = source.illustration_score
    target.general_tags_json = source.general_tags_json
    target.character_tags_json = source.character_tags_json
    target.ratings_json = source.ratings_json
    target.error = source.error
    target.analyzed_at = source.analyzed_at


def _filter_scores(
    scores: Mapping[str, float],
    *,
    threshold: float,
) -> dict[str, float]:
    return {
        name: round(float(score), 4)
        for name, score in sorted(
            scores.items(), key=lambda item: item[1], reverse=True
        )
        if score >= threshold
    }


def _maybe_auto_approve_attachment(
    session: Session,
    attachment: MediaAttachment,
    score: float | None,
    threshold: float | None,
) -> bool:
    if threshold is None:
        return False
    if attachment.approval_status != ApprovalStatus.UNDER_REVIEW:
        return False
    if score is None or score < threshold:
        return False

    set_media_decision(
        session,
        attachment,
        approval_status=ApprovalStatus.APPROVED,
    )
    return True


def _default_tagger(profile: AnalysisProfile) -> ImageTagger:
    try:
        if profile.model_name == PIXAI_TAGGER_V0_9_ONNX_REPO_ID:
            return get_pixai_tagger(profile.model_name, profile.model_version)
        return get_wd_tagger(profile.model_name, profile.model_version)
    except Exception as exc:
        msg = "Illustration tagger could not be initialized"
        raise TaggerUnavailableError(msg) from exc
