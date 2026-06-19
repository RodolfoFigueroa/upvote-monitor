from datetime import datetime
import json

from pydantic import BaseModel, Field
from sqlmodel import Session

from upvote_monitor.db.models import (
    AnalysisProfile,
    MediaAnalysis,
    MediaAttachment,
    ReviewItem,
)
from upvote_monitor.enums import ApprovalStatus
from upvote_monitor.services.download import (
    get_media_attachments,
    get_preview_urls,
    get_source_urls,
)
from upvote_monitor.services.preview_cache import localize_preview_urls
from upvote_monitor.services.tagging.analysis import (
    get_attachment_analysis,
    get_attachment_analyses,
    get_item_analysis_summary,
)
from upvote_monitor.services.tagging.profiles import (
    DEFAULT_CHARACTER_TAG_DISPLAY_THRESHOLD,
    DEFAULT_GENERAL_TAG_DISPLAY_THRESHOLD,
)


def _approval_status_api(status: ApprovalStatus) -> str:
    return {
        ApprovalStatus.REJECTED: "rejected",
        ApprovalStatus.APPROVED: "approved",
        ApprovalStatus.UNDER_REVIEW: "under_review",
    }[status]


class MediaAttachmentResponse(BaseModel):
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
    analysis: "MediaAnalysisResponse | None" = None
    analyses: list["MediaAnalysisResponse"] = Field(default_factory=list)

    @classmethod
    def from_db(
        cls,
        attachment: MediaAttachment,
        session: Session,
    ) -> "MediaAttachmentResponse":
        return cls(
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
            analysis=MediaAnalysisResponse.from_db(
                get_attachment_analysis(session, attachment.id),
                session,
            ),
            analyses=[
                MediaAnalysisResponse.from_analysis(analysis, session)
                for analysis in get_attachment_analyses(session, attachment.id)
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
    ) -> "MediaAnalysisResponse":
        profile = session.get(AnalysisProfile, analysis.analysis_profile_id)
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
                threshold=(
                    profile.general_tag_display_threshold
                    if profile is not None
                    else DEFAULT_GENERAL_TAG_DISPLAY_THRESHOLD
                ),
            ),
            character_tags=_filter_scores(
                character_tags,
                threshold=(
                    profile.character_tag_display_threshold
                    if profile is not None
                    else DEFAULT_CHARACTER_TAG_DISPLAY_THRESHOLD
                ),
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
    ) -> "MediaAnalysisResponse | None":
        if analysis is None:
            return None
        return cls.from_analysis(analysis, session)


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

    @classmethod
    def from_db(cls, item: ReviewItem, session: Session) -> "ItemSummary":
        preview_urls = get_preview_urls(session, item.id)
        analysis = get_item_analysis_summary(session, item.id)
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
            approval_status=_approval_status_api(item.approval_status),
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
        )


class ItemDetail(ItemSummary):
    download_error: str | None
    source_urls: list[str]
    media: list[MediaAttachmentResponse]

    @classmethod
    def from_db(cls, item: ReviewItem, session: Session) -> "ItemDetail":
        attachments = get_media_attachments(session, item.id)
        return cls(
            **ItemSummary.from_db(item, session).model_dump(),
            download_error=item.download_error,
            source_urls=get_source_urls(session, item.id),
            media=[
                MediaAttachmentResponse.from_db(attachment, session)
                for attachment in attachments
            ],
        )


class ItemListResponse(BaseModel):
    items: list[ItemSummary]
    total: int
    limit: int
    offset: int


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


def _filter_scores(
    scores: dict[str, float],
    *,
    threshold: float,
) -> dict[str, float]:
    return {
        name: score
        for name, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        if score >= threshold
    }
