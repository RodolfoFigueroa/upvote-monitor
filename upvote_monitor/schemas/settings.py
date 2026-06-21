from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, Field, field_validator

from upvote_monitor.db.models import AnalysisProfile, AppSettings, SourceSettings
from upvote_monitor.enums import ApprovalMode
from upvote_monitor.services.secrets import (
    SecretStore,
    SecretStoreInvalid,
    SecretStoreUnavailable,
)
from upvote_monitor.services.source_settings import (
    REDDIT_MAX_PAGE_LIMIT,
    REDDIT_MIN_PAGE_LIMIT,
    REDDIT_SOURCE,
    X_MAX_PAGE_LIMIT,
    X_MAX_PAGE_SIZE,
    X_MIN_PAGE_LIMIT,
    X_MIN_PAGE_SIZE,
    X_SOURCE,
    reddit_options_from_source_settings,
    x_options_from_source_settings,
)


def _reddit_username_from_secret_store(secret_store: SecretStore) -> str:
    if not secret_store.available:
        return ""
    try:
        return secret_store.get_source_secrets(REDDIT_SOURCE).get("username", "").strip()
    except (SecretStoreInvalid, SecretStoreUnavailable):
        return ""


class RedditSourceSettingsResponse(BaseModel):
    enabled: bool
    username: str
    page_limit: int
    page_size: int
    user_agent: str
    session_cookie_configured: bool
    session_cookie_prefix: str | None
    session_cookie_suffix: str | None
    secrets_available: bool

    @classmethod
    def from_db(
        cls,
        source_settings: SourceSettings | None,
        secret_store: SecretStore,
    ) -> "RedditSourceSettingsResponse":
        options = reddit_options_from_source_settings(source_settings)
        return cls(
            enabled=source_settings.enabled if source_settings is not None else True,
            username=_reddit_username_from_secret_store(secret_store),
            page_limit=options.page_limit,
            page_size=options.page_size,
            user_agent=options.user_agent,
            session_cookie_configured=secret_store.source_secret_configured(
                REDDIT_SOURCE,
                "session_cookie",
            ),
            session_cookie_prefix=secret_store.source_secret_prefix(
                REDDIT_SOURCE,
                "session_cookie",
            ),
            session_cookie_suffix=secret_store.source_secret_suffix(
                REDDIT_SOURCE,
                "session_cookie",
            ),
            secrets_available=secret_store.available,
        )


class XSourceSettingsResponse(BaseModel):
    enabled: bool
    page_limit: int
    page_size: int
    user_agent: str
    auth_token_configured: bool
    auth_token_prefix: str | None
    auth_token_suffix: str | None
    ct0_configured: bool
    ct0_prefix: str | None
    ct0_suffix: str | None
    twid_configured: bool
    twid_prefix: str | None
    twid_suffix: str | None
    bearer_token_configured: bool
    bearer_token_prefix: str | None
    bearer_token_suffix: str | None
    secrets_available: bool

    @classmethod
    def from_db(
        cls,
        source_settings: SourceSettings | None,
        secret_store: SecretStore,
    ) -> "XSourceSettingsResponse":
        options = x_options_from_source_settings(source_settings)
        return cls(
            enabled=source_settings.enabled if source_settings is not None else False,
            page_limit=options.page_limit,
            page_size=options.page_size,
            user_agent=options.user_agent,
            auth_token_configured=secret_store.source_secret_configured(
                X_SOURCE,
                "auth_token",
            ),
            auth_token_prefix=secret_store.source_secret_prefix(
                X_SOURCE,
                "auth_token",
            ),
            auth_token_suffix=secret_store.source_secret_suffix(
                X_SOURCE,
                "auth_token",
            ),
            ct0_configured=secret_store.source_secret_configured(X_SOURCE, "ct0"),
            ct0_prefix=secret_store.source_secret_prefix(X_SOURCE, "ct0"),
            ct0_suffix=secret_store.source_secret_suffix(X_SOURCE, "ct0"),
            twid_configured=secret_store.source_secret_configured(X_SOURCE, "twid"),
            twid_prefix=secret_store.source_secret_prefix(X_SOURCE, "twid"),
            twid_suffix=secret_store.source_secret_suffix(X_SOURCE, "twid"),
            bearer_token_configured=secret_store.source_secret_configured(
                X_SOURCE,
                "bearer_token",
            ),
            bearer_token_prefix=secret_store.source_secret_prefix(
                X_SOURCE,
                "bearer_token",
            ),
            bearer_token_suffix=secret_store.source_secret_suffix(
                X_SOURCE,
                "bearer_token",
            ),
            secrets_available=secret_store.available,
        )


class SourceSettingsResponse(BaseModel):
    reddit: RedditSourceSettingsResponse
    x: XSourceSettingsResponse


class AnalysisProfileResponse(BaseModel):
    id: str
    name: str
    model_name: str
    model_version: str
    scoring_version: str
    general_tag_storage_threshold: float
    character_tag_storage_threshold: float
    general_tag_display_threshold: float
    character_tag_display_threshold: float
    auto_approve_threshold: float
    enabled: bool

    @classmethod
    def from_db(cls, profile: AnalysisProfile) -> "AnalysisProfileResponse":
        return cls(
            id=profile.id,
            name=profile.name,
            model_name=profile.model_name,
            model_version=profile.model_version,
            scoring_version=profile.scoring_version,
            general_tag_storage_threshold=profile.general_tag_storage_threshold,
            character_tag_storage_threshold=profile.character_tag_storage_threshold,
            general_tag_display_threshold=profile.general_tag_display_threshold,
            character_tag_display_threshold=profile.character_tag_display_threshold,
            auto_approve_threshold=profile.auto_approve_threshold,
            enabled=profile.enabled,
        )


class SettingsResponse(BaseModel):
    approval_mode: str
    refresh_cron: str
    refresh_enabled: bool
    download_base_dir: str
    illustration_tagger_enabled: bool
    illustration_auto_approve_enabled: bool
    active_analysis_profile_id: str
    general_tag_display_threshold: float
    character_tag_display_threshold: float
    analysis_profiles: list[AnalysisProfileResponse]
    sources: SourceSettingsResponse

    @classmethod
    def from_db(
        cls,
        settings: AppSettings,
        reddit_settings: SourceSettings | None,
        x_settings: SourceSettings | None,
        secret_store: SecretStore,
        analysis_profiles: list[AnalysisProfile],
    ) -> "SettingsResponse":
        return cls(
            approval_mode=settings.approval_mode.value,
            refresh_cron=settings.refresh_cron,
            refresh_enabled=settings.refresh_enabled,
            download_base_dir=settings.download_base_dir,
            illustration_tagger_enabled=settings.illustration_tagger_enabled,
            illustration_auto_approve_enabled=(
                settings.illustration_auto_approve_enabled
            ),
            active_analysis_profile_id=settings.active_analysis_profile_id,
            general_tag_display_threshold=settings.general_tag_display_threshold,
            character_tag_display_threshold=settings.character_tag_display_threshold,
            analysis_profiles=[
                AnalysisProfileResponse.from_db(profile)
                for profile in analysis_profiles
            ],
            sources=SourceSettingsResponse(
                reddit=RedditSourceSettingsResponse.from_db(
                    reddit_settings,
                    secret_store,
                ),
                x=XSourceSettingsResponse.from_db(
                    x_settings,
                    secret_store,
                ),
            ),
        )


class RedditSourceSettingsUpdate(BaseModel):
    enabled: bool | None = None
    username: str | None = None
    page_limit: int | None = Field(
        default=None,
        ge=REDDIT_MIN_PAGE_LIMIT,
        le=REDDIT_MAX_PAGE_LIMIT,
    )
    user_agent: str | None = None
    session_cookie: str | None = None

    @field_validator("username", "user_agent")
    @classmethod
    def strip_optional_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class XSourceSettingsUpdate(BaseModel):
    enabled: bool | None = None
    page_limit: int | None = Field(
        default=None,
        ge=X_MIN_PAGE_LIMIT,
        le=X_MAX_PAGE_LIMIT,
    )
    page_size: int | None = Field(
        default=None,
        ge=X_MIN_PAGE_SIZE,
        le=X_MAX_PAGE_SIZE,
    )
    user_agent: str | None = None
    auth_token: str | None = None
    ct0: str | None = None
    twid: str | None = None
    bearer_token: str | None = None

    @field_validator(
        "user_agent",
        "auth_token",
        "ct0",
        "twid",
        "bearer_token",
    )
    @classmethod
    def strip_optional_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class SourceSettingsUpdate(BaseModel):
    reddit: RedditSourceSettingsUpdate | None = None
    x: XSourceSettingsUpdate | None = None


class SettingsUpdate(BaseModel):
    approval_mode: ApprovalMode | None = None
    refresh_cron: str | None = None
    refresh_enabled: bool | None = None
    download_base_dir: str | None = None
    illustration_tagger_enabled: bool | None = None
    illustration_auto_approve_enabled: bool | None = None
    active_analysis_profile_id: str | None = None
    general_tag_display_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    character_tag_display_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )
    sources: SourceSettingsUpdate | None = None

    @field_validator("refresh_cron")
    @classmethod
    def validate_refresh_cron(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                CronTrigger.from_crontab(value)
            except ValueError as exc:
                raise ValueError("refresh_cron must be a valid crontab") from exc
        return value

    @field_validator("download_base_dir")
    @classmethod
    def validate_absolute_path(cls, value: str | None) -> str | None:
        if value is not None:
            from pathlib import Path

            if not Path(value).is_absolute():
                raise ValueError("download_base_dir must be an absolute path")
        return value
