import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from sqlmodel import Session, col, select

from upvote_monitor.db.models import AppSettings, MediaAnalysis, MediaAttachment, ReviewItem
from upvote_monitor.enums import AnalysisStatus, ApprovalStatus
from upvote_monitor.services.preview_cache import (
    delete_item_preview_cache,
    get_or_fetch_cached_preview,
    is_cacheable_preview_url,
)
from upvote_monitor.services.tagging.scoring import score_illustration
from upvote_monitor.services.tagging.wd_tagger import WDTaggerResult, get_wd_tagger

logger = logging.getLogger(__name__)
DEFAULT_TAG_PERSISTENCE_THRESHOLD = 0.15


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

    if tagger is None:
        try:
            tagger = _default_tagger()
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
            tagger,
            force=False,
            auto_approve_threshold=(
                settings.illustration_auto_approve_threshold
                if settings.illustration_auto_approve_enabled
                else None
            ),
            tag_persistence_threshold=settings.illustration_tag_persistence_threshold,
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
    if tagger is None:
        tagger = _default_tagger()

    settings = session.get(AppSettings, 1)
    result = _analyze_item(
        session,
        item,
        tagger,
        force=True,
        auto_approve_threshold=None,
        tag_persistence_threshold=(
            settings.illustration_tag_persistence_threshold
            if settings is not None
            else DEFAULT_TAG_PERSISTENCE_THRESHOLD
        ),
    )
    session.commit()
    return result


def get_attachment_analysis(
    session: Session,
    attachment_id: int | None,
) -> MediaAnalysis | None:
    if attachment_id is None:
        return None
    return session.exec(
        select(MediaAnalysis)
        .where(MediaAnalysis.attachment_id == attachment_id)
        .order_by(col(MediaAnalysis.analyzed_at).desc())
    ).first()


def get_item_analysis_summary(
    session: Session,
    item_id: str,
) -> ItemAnalysisSummary:
    rows = session.exec(
        select(MediaAnalysis)
        .join(
            MediaAttachment,
            col(MediaAttachment.id) == col(MediaAnalysis.attachment_id),
        )
        .where(MediaAttachment.item_id == item_id)
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


def _existing_item_scores(
    session: Session,
    item_id: str,
    tagger: ImageTagger,
) -> list[float]:
    rows = session.exec(
        select(MediaAnalysis)
        .join(
            MediaAttachment,
            col(MediaAttachment.id) == col(MediaAnalysis.attachment_id),
        )
        .where(MediaAttachment.item_id == item_id)
        .where(MediaAnalysis.model_name == tagger.model_name)
        .where(MediaAnalysis.model_version == tagger.model_version)
        .where(MediaAnalysis.status == AnalysisStatus.COMPLETED)
    ).all()
    return [row.illustration_score for row in rows if row.illustration_score is not None]


def _analyze_item(
    session: Session,
    item: ReviewItem,
    tagger: ImageTagger,
    *,
    force: bool,
    auto_approve_threshold: float | None,
    tag_persistence_threshold: float,
) -> AnalysisBatchResult:
    result = AnalysisBatchResult()
    scores = _existing_item_scores(session, item.id, tagger) if not force else []
    attachments = _image_attachments_for_item(session, item.id)

    for attachment in attachments:
        if attachment.id is None:
            continue
        existing = _existing_analysis(session, attachment.id, tagger)
        if existing is not None and not force:
            continue

        analysis = _analyze_attachment(
            item,
            attachment,
            tagger,
            tag_persistence_threshold=tag_persistence_threshold,
        )
        if existing is not None:
            _replace_analysis(existing, analysis)
            analysis = existing
        else:
            session.add(analysis)

        if analysis.status == AnalysisStatus.COMPLETED:
            result.analyzed += 1
            if analysis.illustration_score is not None:
                scores.append(analysis.illustration_score)
        elif analysis.status == AnalysisStatus.SKIPPED:
            result.skipped += 1
        elif analysis.status == AnalysisStatus.FAILED:
            result.failed += 1

    if auto_approve_threshold is not None and _maybe_auto_approve_item(
        item,
        scores,
        auto_approve_threshold,
    ):
        session.add(item)
        delete_item_preview_cache(item.id)
        result.approved += 1

    return result


def _existing_analysis(
    session: Session,
    attachment_id: int,
    tagger: ImageTagger,
) -> MediaAnalysis | None:
    return session.exec(
        select(MediaAnalysis)
        .where(MediaAnalysis.attachment_id == attachment_id)
        .where(MediaAnalysis.model_name == tagger.model_name)
        .where(MediaAnalysis.model_version == tagger.model_version)
    ).first()


def _analyze_attachment(
    item: ReviewItem,
    attachment: MediaAttachment,
    tagger: ImageTagger,
    *,
    tag_persistence_threshold: float,
) -> MediaAnalysis:
    assert attachment.id is not None
    preview_url = attachment.preview_url or attachment.download_url
    if not is_cacheable_preview_url(preview_url):
        return _analysis_result(
            attachment.id,
            tagger,
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
            tagger,
            AnalysisStatus.FAILED,
            error=str(exc),
        )

    score = score_illustration(
        tagger_result.general_tags,
        tagger_result.character_tags,
        tagger_result.ratings,
    )
    tags = _persisted_tags(
        tagger_result.general_tags,
        tagger_result.character_tags,
        threshold=tag_persistence_threshold,
    )
    return _analysis_result(
        attachment.id,
        tagger,
        AnalysisStatus.COMPLETED,
        illustration_score=score,
        tags_json=json.dumps(tags, sort_keys=True),
        ratings_json=json.dumps(
            _filter_scores(tagger_result.ratings, threshold=0.0),
            sort_keys=True,
        ),
    )


def _analysis_result(
    attachment_id: int,
    tagger: ImageTagger,
    status: AnalysisStatus,
    *,
    illustration_score: float | None = None,
    tags_json: str = "{}",
    ratings_json: str = "{}",
    error: str | None = None,
) -> MediaAnalysis:
    return MediaAnalysis(
        attachment_id=attachment_id,
        model_name=tagger.model_name,
        model_version=tagger.model_version,
        status=status,
        illustration_score=illustration_score,
        tags_json=tags_json,
        ratings_json=ratings_json,
        error=error,
        analyzed_at=datetime.now(timezone.utc),
    )


def _replace_analysis(target: MediaAnalysis, source: MediaAnalysis) -> None:
    target.status = source.status
    target.illustration_score = source.illustration_score
    target.tags_json = source.tags_json
    target.ratings_json = source.ratings_json
    target.error = source.error
    target.analyzed_at = source.analyzed_at


def _persisted_tags(
    general_tags: Mapping[str, float],
    character_tags: Mapping[str, float],
    *,
    threshold: float,
) -> dict[str, float]:
    combined = dict(general_tags)
    combined.update(character_tags)
    return _filter_scores(combined, threshold=threshold)


def _filter_scores(
    scores: Mapping[str, float],
    *,
    threshold: float,
) -> dict[str, float]:
    return {
        name: round(float(score), 4)
        for name, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        if score >= threshold
    }


def _maybe_auto_approve_item(
    item: ReviewItem,
    scores: list[float],
    threshold: float,
) -> bool:
    if item.approval_status != ApprovalStatus.UNDER_REVIEW:
        return False
    if not scores:
        return False
    if max(scores) < threshold:
        return False

    item.approval_status = ApprovalStatus.APPROVED
    return True


def _default_tagger() -> ImageTagger:
    try:
        return get_wd_tagger()
    except Exception as exc:
        raise TaggerUnavailableError(
            "Illustration tagger could not be initialized"
        ) from exc
