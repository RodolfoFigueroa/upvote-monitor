from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Column, Index, Text, UniqueConstraint, text
from sqlmodel import Field, SQLModel

from upvote_monitor.enums import (
    AnalysisStatus,
    ApprovalMode,
    ApprovalStatus,
    DownloadStatus,
    DownloadStrategy,
    IllustrationLabel,
    ListType,
    RefreshRunStatus,
    RuleTargetType,
)

DEFAULT_ANALYSIS_PROFILE_ID = "wd-swinv2-v3-627aef95"
DEFAULT_GENERAL_TAG_DISPLAY_THRESHOLD = 0.15
DEFAULT_CHARACTER_TAG_DISPLAY_THRESHOLD = 0.35


def utc_now() -> datetime:
    return datetime.now(UTC)


class ReviewItem(SQLModel, table=True):
    __tablename__ = "review_items"
    __table_args__ = (
        UniqueConstraint("source", "source_item_id", name="uq_review_item_source_item"),
        Index(
            "ix_review_items_list",
            "approval_status",
            "download_status",
            "created_at",
            "id",
        ),
        Index(
            "ix_review_items_download_claim",
            "approval_status",
            "download_status",
            "download_ready_at",
            "id",
        ),
        Index("ix_review_items_created_cursor", "created_at", "id"),
        Index("ix_review_items_source_created", "source", "created_at", "id"),
        Index(
            "ix_review_items_community_created",
            "community_name",
            "created_at",
            "id",
        ),
        Index(
            "ix_review_items_author_created",
            "author_name",
            "created_at",
            "id",
        ),
        Index(
            "ix_review_items_download_recovery",
            "download_status",
            "download_heartbeat_at",
        ),
    )

    id: str = Field(primary_key=True)
    source: str = Field(index=True)
    source_item_id: str = Field(index=True)
    title: str
    author_name: str | None = Field(default=None, index=True)
    author_label: str | None = None
    community_name: str | None = Field(default=None, index=True)
    community_label: str | None = None
    item_kind: str
    source_url: str
    created_at: datetime
    approval_status: ApprovalStatus
    download_status: DownloadStatus = Field(default=DownloadStatus.PENDING)
    download_ready_at: datetime | None = Field(default=None, index=True)
    download_error: str | None = None
    raw_data_json: str = Field(sa_column=Column(Text, nullable=False))
    media_count: int
    discovered_at: datetime = Field(default_factory=utc_now)
    downloaded_at: datetime | None = None
    download_dir: str | None = None
    download_claim_token: str | None = Field(default=None, index=True)
    download_claimed_at: datetime | None = None
    download_heartbeat_at: datetime | None = Field(default=None, index=True)


class MediaAttachment(SQLModel, table=True):
    __tablename__ = "media_attachments"
    __table_args__ = (
        UniqueConstraint(
            "item_id",
            "sort_index",
            name="uq_media_attachment_item_sort",
        ),
        Index("ix_media_attachments_item_order", "item_id", "sort_index", "id"),
        Index(
            "ix_media_attachments_approval_item_order",
            "approval_status",
            "item_id",
            "sort_index",
            "id",
        ),
        Index(
            "ix_media_attachments_label_item_order",
            "illustration_label",
            "item_id",
            "sort_index",
            "id",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    item_id: str = Field(foreign_key="review_items.id", index=True)
    sort_index: int
    media_type: str
    content_type: str | None = None
    download_url: str
    preview_url: str | None = None
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    extension: str | None = None
    download_strategy: DownloadStrategy = Field(default=DownloadStrategy.HTTP)
    approval_status: ApprovalStatus = Field(
        default=ApprovalStatus.UNDER_REVIEW,
        index=True,
    )
    decided_at: datetime | None = Field(default=None, index=True)
    illustration_label: IllustrationLabel = Field(
        default=IllustrationLabel.UNLABELED,
        index=True,
    )


class AnalysisProfile(SQLModel, table=True):
    __tablename__ = "analysis_profiles"

    id: str = Field(primary_key=True)
    name: str
    model_name: str = Field(index=True)
    model_version: str = Field(default="main", index=True)
    model_revision: str | None = Field(default=None, index=True)
    model_sha256: str | None = None
    preprocessing_version: str | None = None
    scoring_version: str = Field(default="illustration-v1", index=True)
    general_tag_storage_threshold: float = Field(default=0.01)
    character_tag_storage_threshold: float = Field(default=0.01)
    general_tag_display_threshold: float = Field(default=0.15)
    character_tag_display_threshold: float = Field(default=0.35)
    auto_approve_threshold: float = Field(default=0.90)
    enabled: bool = Field(default=True)


class MediaAnalysis(SQLModel, table=True):
    __tablename__ = "media_analyses"
    __table_args__ = (
        UniqueConstraint(
            "attachment_id",
            "analysis_profile_id",
            name="uq_media_analysis_attachment_profile",
        ),
        Index(
            "ix_media_analyses_attachment_analyzed",
            "attachment_id",
            "analyzed_at",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    attachment_id: int = Field(foreign_key="media_attachments.id", index=True)
    analysis_profile_id: str = Field(foreign_key="analysis_profiles.id", index=True)
    model_name: str = Field(index=True)
    model_version: str = Field(default="main", index=True)
    model_revision: str | None = Field(default=None, index=True)
    model_sha256: str | None = None
    preprocessing_version: str | None = None
    scoring_version: str = Field(default="illustration-v1", index=True)
    status: AnalysisStatus = Field(default=AnalysisStatus.COMPLETED, index=True)
    illustration_score: float | None = Field(default=None, index=True)
    general_tags_json: str = Field(default="{}", sa_column=Column(Text, nullable=False))
    character_tags_json: str = Field(
        default="{}",
        sa_column=Column(Text, nullable=False),
    )
    ratings_json: str = Field(default="{}", sa_column=Column(Text, nullable=False))
    error: str | None = None
    analyzed_at: datetime | None = None


class AppSettings(SQLModel, table=True):
    __tablename__ = "app_settings"

    id: int = Field(primary_key=True, default=1)
    approval_mode: ApprovalMode = Field(default=ApprovalMode.MANUAL)
    refresh_cron: str = Field(default="0 */6 * * *")
    refresh_enabled: bool = Field(default=True)
    download_base_dir: str = Field(default="/download")
    illustration_tagger_enabled: bool = Field(default=False)
    illustration_auto_approve_enabled: bool = Field(default=False)
    active_analysis_profile_id: str = Field(default=DEFAULT_ANALYSIS_PROFILE_ID)
    general_tag_display_threshold: float = Field(
        default=DEFAULT_GENERAL_TAG_DISPLAY_THRESHOLD,
    )
    character_tag_display_threshold: float = Field(
        default=DEFAULT_CHARACTER_TAG_DISPLAY_THRESHOLD,
    )


class SourceSettings(SQLModel, table=True):
    __tablename__ = "source_settings"

    source: str = Field(primary_key=True)
    enabled: bool = Field(default=True)
    options_json: str = Field(default="{}", sa_column=Column(Text, nullable=False))


class SourceRule(SQLModel, table=True):
    __tablename__ = "source_rules"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "rule_type",
            "target_type",
            "target_value",
            name="uq_source_rule",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    rule_type: ListType = Field(index=True)
    target_type: RuleTargetType = Field(index=True)
    target_value: str = Field(index=True)
    target_label: str


class RefreshRun(SQLModel, table=True):
    __tablename__ = "refresh_runs"
    __table_args__ = (
        Index("ix_refresh_runs_active", "status", "heartbeat_at", "started_at"),
        Index(
            "uq_refresh_runs_one_active",
            text("1"),
            unique=True,
            sqlite_where=text("status IN ('QUEUED', 'RUNNING')"),
        ),
    )

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    status: RefreshRunStatus = Field(default=RefreshRunStatus.QUEUED)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    new_items: int = Field(default=0)
    skipped: int = Field(default=0)
    downloads_triggered: int = Field(default=0)
    downloads_failed: int = Field(default=0)
    error: str | None = None
    claim_token: str | None = Field(default=None, index=True)
    claimed_at: datetime | None = None
    heartbeat_at: datetime | None = Field(default=None, index=True)
