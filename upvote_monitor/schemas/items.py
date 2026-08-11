import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from upvote_monitor.db.models import (
    DEFAULT_CHARACTER_TAG_DISPLAY_THRESHOLD,
    DEFAULT_GENERAL_TAG_DISPLAY_THRESHOLD,
    AppSettings,
    MediaAnalysis,
    MediaAttachment,
    ReviewItem,
)
from upvote_monitor.enums import AnalysisStatus, ApprovalStatus, IllustrationLabel
from upvote_monitor.services.media_workflow import (
    MediaDecisionCounts,
    approval_status_api,
)
from upvote_monitor.services.preview_cache import (
    localize_preview_url,
    localize_preview_urls,
)
from upvote_monitor.services.tagging.analysis import (
    ItemAnalysisSummary,
    get_analyses_for_attachments,
)
from upvote_monitor.services.tagging.profiles import active_analysis_profile


@dataclass(frozen=True)
class ResponseProjection:
    attachments_by_item: dict[str, list[MediaAttachment]]
    analyses_by_attachment: dict[int, list[MediaAnalysis]]
    active_profile_id: str | None
    general_threshold: float
    character_threshold: float

    @classmethod
    def load(
        cls,
        session: Session,
        item_ids: list[str],
        *,
        attachments: list[MediaAttachment] | None = None,
    ) -> "ResponseProjection":
        if attachments is None:
            attachments = (
                list(
                    session.exec(
                        select(MediaAttachment)
                        .where(col(MediaAttachment.item_id).in_(item_ids))
                        .order_by(
                            col(MediaAttachment.item_id),
                            col(MediaAttachment.sort_index),
                        ),
                    ).all(),
                )
                if item_ids
                else []
            )
        grouped: defaultdict[str, list[MediaAttachment]] = defaultdict(list)
        attachment_ids: list[int] = []
        for attachment in attachments:
            grouped[attachment.item_id].append(attachment)
            if attachment.id is not None:
                attachment_ids.append(attachment.id)

        profile = active_analysis_profile(session)
        general_threshold, character_threshold = _tag_display_thresholds(session)
        return cls(
            attachments_by_item=dict(grouped),
            analyses_by_attachment=get_analyses_for_attachments(
                session,
                attachment_ids,
            ),
            active_profile_id=profile.id if profile is not None else None,
            general_threshold=general_threshold,
            character_threshold=character_threshold,
        )

    def analyses_for(self, attachment_id: int) -> list[MediaAnalysis]:
        return self.analyses_by_attachment.get(attachment_id, [])

    def active_analysis_for(self, attachment_id: int) -> MediaAnalysis | None:
        if self.active_profile_id is None:
            return None
        return next(
            (
                analysis
                for analysis in self.analyses_for(attachment_id)
                if analysis.analysis_profile_id == self.active_profile_id
            ),
            None,
        )

    def item_analysis_summary(self, item_id: str) -> ItemAnalysisSummary:
        if self.active_profile_id is None:
            return ItemAnalysisSummary(status=None, illustration_score=None)
        rows = [
            analysis
            for attachment in self.attachments_by_item.get(item_id, [])
            if attachment.id is not None
            for analysis in self.analyses_for(attachment.id)
            if analysis.analysis_profile_id == self.active_profile_id
        ]
        scores = [
            row.illustration_score
            for row in rows
            if row.status == AnalysisStatus.COMPLETED
            and row.illustration_score is not None
        ]
        if scores:
            return ItemAnalysisSummary(
                status=AnalysisStatus.COMPLETED.value,
                illustration_score=max(scores),
            )
        statuses = {row.status for row in rows}
        if AnalysisStatus.FAILED in statuses:
            return ItemAnalysisSummary(AnalysisStatus.FAILED.value, None)
        if AnalysisStatus.SKIPPED in statuses:
            return ItemAnalysisSummary(AnalysisStatus.SKIPPED.value, None)
        return ItemAnalysisSummary(status=None, illustration_score=None)


def _persisted_attachment_id(attachment: MediaAttachment) -> int:
    if attachment.id is None:
        msg = "Media attachment must be persisted before serialization"
        raise ValueError(msg)
    return attachment.id


class MediaAttachmentResponse(BaseModel):
    id: int
    item_id: str
    sort_index: int
    media_type: str
    content_type: str | None
    download_url: str
    preview_url: str | None
    width: int | None
    height: int | None
    duration_ms: int | None
    extension: str | None
    download_strategy: str
    approval_status: str
    illustration_label: str
    analysis: "MediaAnalysisResponse | None" = None
    analyses: list["MediaAnalysisResponse"] = Field(default_factory=list)

    @classmethod
    def from_db(
        cls,
        attachment: MediaAttachment,
        session: Session,
        projection: ResponseProjection | None = None,
    ) -> "MediaAttachmentResponse":
        attachment_id = _persisted_attachment_id(attachment)
        projection = projection or ResponseProjection.load(
            session,
            [attachment.item_id],
            attachments=[attachment],
        )
        return cls(
            id=attachment_id,
            item_id=attachment.item_id,
            sort_index=attachment.sort_index,
            media_type=attachment.media_type,
            content_type=attachment.content_type,
            download_url=attachment.download_url,
            preview_url=attachment.preview_url,
            width=attachment.width,
            height=attachment.height,
            duration_ms=attachment.duration_ms,
            extension=attachment.extension,
            download_strategy=attachment.download_strategy.value,
            approval_status=approval_status_api(attachment.approval_status),
            illustration_label=attachment.illustration_label.value,
            analysis=MediaAnalysisResponse.from_db(
                projection.active_analysis_for(attachment_id),
                session,
                thresholds=(
                    projection.general_threshold,
                    projection.character_threshold,
                ),
            ),
            analyses=[
                MediaAnalysisResponse.from_analysis(
                    analysis,
                    session,
                    thresholds=(
                        projection.general_threshold,
                        projection.character_threshold,
                    ),
                )
                for analysis in projection.analyses_for(attachment_id)
            ],
        )


class MediaAnalysisResponse(BaseModel):
    analysis_profile_id: str
    status: str
    model_name: str
    model_version: str
    scoring_version: str
    illustration_score: float | None
    general_tags: dict[str, float]
    character_tags: dict[str, float]
    ratings: dict[str, float]
    stored_general_tag_count: int
    stored_character_tag_count: int
    error: str | None
    analyzed_at: datetime | None

    @classmethod
    def from_analysis(
        cls,
        analysis: MediaAnalysis,
        session: Session,
        *,
        thresholds: tuple[float, float] | None = None,
    ) -> "MediaAnalysisResponse":
        general_threshold, character_threshold = thresholds or _tag_display_thresholds(
            session,
        )
        general_tags = _decode_scores(analysis.general_tags_json)
        character_tags = _decode_scores(analysis.character_tags_json)
        return cls(
            analysis_profile_id=analysis.analysis_profile_id,
            status=analysis.status.value,
            model_name=analysis.model_name,
            model_version=analysis.model_version,
            scoring_version=analysis.scoring_version,
            illustration_score=analysis.illustration_score,
            general_tags=_filter_scores(
                general_tags,
                threshold=general_threshold,
            ),
            character_tags=_filter_scores(
                character_tags,
                threshold=character_threshold,
            ),
            ratings=_decode_scores(analysis.ratings_json),
            stored_general_tag_count=len(general_tags),
            stored_character_tag_count=len(character_tags),
            error=analysis.error,
            analyzed_at=analysis.analyzed_at,
        )

    @classmethod
    def from_db(
        cls,
        analysis: MediaAnalysis | None,
        session: Session,
        *,
        thresholds: tuple[float, float] | None = None,
    ) -> "MediaAnalysisResponse | None":
        if analysis is None:
            return None
        return cls.from_analysis(analysis, session, thresholds=thresholds)


class ItemSummary(BaseModel):
    id: str
    source: str
    source_item_id: str
    title: str
    author_name: str | None
    author_label: str | None
    community_name: str | None
    community_label: str | None
    item_kind: str
    approval_status: str
    download_status: str
    created_at: datetime
    source_url: str
    media_count: int
    discovered_at: datetime
    downloaded_at: datetime | None
    preview_urls: list[str]
    analysis_status: str | None
    illustration_score: float | None
    media_approved_count: int
    media_rejected_count: int
    media_under_review_count: int
    media_unlabeled_count: int

    @classmethod
    def from_db(
        cls,
        item: ReviewItem,
        session: Session,
        projection: ResponseProjection | None = None,
    ) -> "ItemSummary":
        projection = projection or ResponseProjection.load(session, [item.id])
        attachments = projection.attachments_by_item.get(item.id, [])
        preview_urls = [
            attachment.preview_url or attachment.download_url
            for attachment in attachments
        ]
        analysis = projection.item_analysis_summary(item.id)
        counts = _attachment_counts(attachments)
        return cls(
            id=item.id,
            source=item.source,
            source_item_id=item.source_item_id,
            title=item.title,
            author_name=item.author_name,
            author_label=item.author_label,
            community_name=item.community_name,
            community_label=item.community_label,
            item_kind=item.item_kind,
            approval_status=approval_status_api(item.approval_status),
            download_status=item.download_status.value,
            created_at=item.created_at,
            source_url=item.source_url,
            media_count=item.media_count,
            discovered_at=item.discovered_at,
            downloaded_at=item.downloaded_at,
            preview_urls=localize_preview_urls(
                item.id,
                item.approval_status,
                preview_urls,
            ),
            analysis_status=analysis.status,
            illustration_score=analysis.illustration_score,
            media_approved_count=counts.approved,
            media_rejected_count=counts.rejected,
            media_under_review_count=counts.under_review,
            media_unlabeled_count=counts.unlabeled,
        )


class ItemDetail(ItemSummary):
    download_error: str | None
    source_urls: list[str]
    media: list[MediaAttachmentResponse]

    @classmethod
    def from_db(
        cls,
        item: ReviewItem,
        session: Session,
        projection: ResponseProjection | None = None,
    ) -> "ItemDetail":
        projection = projection or ResponseProjection.load(session, [item.id])
        attachments = projection.attachments_by_item.get(item.id, [])
        return cls(
            **ItemSummary.from_db(item, session, projection).model_dump(),
            download_error=item.download_error,
            source_urls=[attachment.download_url for attachment in attachments],
            media=[
                MediaAttachmentResponse.from_db(attachment, session, projection)
                for attachment in attachments
            ],
        )


class ItemListResponse(BaseModel):
    items: list[ItemSummary]
    total: int
    limit: int
    offset: int


class MediaItemResponse(BaseModel):
    id: int
    item_id: str
    item_title: str
    source: str
    source_item_id: str
    source_url: str
    author_name: str | None
    author_label: str | None
    community_name: str | None
    community_label: str | None
    item_kind: str
    item_created_at: datetime
    discovered_at: datetime
    item_approval_status: str
    item_download_status: str
    sort_index: int
    media_type: str
    content_type: str | None
    download_url: str
    preview_url: str | None
    width: int | None
    height: int | None
    duration_ms: int | None
    extension: str | None
    download_strategy: str
    approval_status: str
    illustration_label: str
    analysis: MediaAnalysisResponse | None = None
    analyses: list[MediaAnalysisResponse] = Field(default_factory=list)

    @classmethod
    def from_db(
        cls,
        attachment: MediaAttachment,
        item: ReviewItem,
        session: Session,
        projection: ResponseProjection | None = None,
    ) -> "MediaItemResponse":
        attachment_id = _persisted_attachment_id(attachment)
        projection = projection or ResponseProjection.load(
            session,
            [item.id],
            attachments=[attachment],
        )
        preview_url = attachment.preview_url or attachment.download_url
        localized_preview_url = localize_preview_url(
            item.id,
            item.approval_status,
            attachment.sort_index,
            preview_url,
        )
        return cls(
            id=attachment_id,
            item_id=item.id,
            item_title=item.title,
            source=item.source,
            source_item_id=item.source_item_id,
            source_url=item.source_url,
            author_name=item.author_name,
            author_label=item.author_label,
            community_name=item.community_name,
            community_label=item.community_label,
            item_kind=item.item_kind,
            item_created_at=item.created_at,
            discovered_at=item.discovered_at,
            item_approval_status=approval_status_api(item.approval_status),
            item_download_status=item.download_status.value,
            sort_index=attachment.sort_index,
            media_type=attachment.media_type,
            content_type=attachment.content_type,
            download_url=attachment.download_url,
            preview_url=localized_preview_url,
            width=attachment.width,
            height=attachment.height,
            duration_ms=attachment.duration_ms,
            extension=attachment.extension,
            download_strategy=attachment.download_strategy.value,
            approval_status=approval_status_api(attachment.approval_status),
            illustration_label=attachment.illustration_label.value,
            analysis=MediaAnalysisResponse.from_db(
                projection.active_analysis_for(attachment_id),
                session,
                thresholds=(
                    projection.general_threshold,
                    projection.character_threshold,
                ),
            ),
            analyses=[
                MediaAnalysisResponse.from_analysis(
                    analysis,
                    session,
                    thresholds=(
                        projection.general_threshold,
                        projection.character_threshold,
                    ),
                )
                for analysis in projection.analyses_for(attachment_id)
            ],
        )


class MediaListResponse(BaseModel):
    media: list[MediaItemResponse]
    limit: int
    next_cursor: str | None = None


class MediaUpdate(BaseModel):
    approval_status: str | None = None
    illustration_label: str | None = None


class ItemFile(BaseModel):
    filename: str
    url: str
    media_type: str


class ItemFilesResponse(BaseModel):
    item_id: str
    files: list[ItemFile]


def _decode_scores(value: str) -> dict[str, float]:
    try:
        raw = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(raw, dict):
        return {}

    result: dict[str, float] = {}
    for key, score in raw.items():
        if isinstance(key, str) and isinstance(score, int | float):
            result[key] = float(score)
    return result


def _tag_display_thresholds(session: Session) -> tuple[float, float]:
    settings = session.get(AppSettings, 1)
    if settings is None:
        return (
            DEFAULT_GENERAL_TAG_DISPLAY_THRESHOLD,
            DEFAULT_CHARACTER_TAG_DISPLAY_THRESHOLD,
        )
    return (
        settings.general_tag_display_threshold,
        settings.character_tag_display_threshold,
    )


def _attachment_counts(
    attachments: list[MediaAttachment],
) -> MediaDecisionCounts:
    return MediaDecisionCounts(
        approved=sum(
            attachment.approval_status == ApprovalStatus.APPROVED
            for attachment in attachments
        ),
        rejected=sum(
            attachment.approval_status == ApprovalStatus.REJECTED
            for attachment in attachments
        ),
        under_review=sum(
            attachment.approval_status == ApprovalStatus.UNDER_REVIEW
            for attachment in attachments
        ),
        unlabeled=sum(
            attachment.illustration_label == IllustrationLabel.UNLABELED
            for attachment in attachments
        ),
    )


def _filter_scores(
    scores: dict[str, float],
    *,
    threshold: float,
) -> dict[str, float]:
    return {
        name: score
        for name, score in sorted(
            scores.items(),
            key=lambda item: item[1],
            reverse=True,
        )
        if score >= threshold
    }
