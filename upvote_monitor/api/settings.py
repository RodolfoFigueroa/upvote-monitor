import json
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from upvote_monitor.api.deps import get_db_session
from upvote_monitor.db.models import AnalysisProfile, AppSettings, SourceSettings
from upvote_monitor.scheduler import reschedule_from_settings
from upvote_monitor.schemas.settings import SettingsResponse, SettingsUpdate
from upvote_monitor.services.secrets import (
    SecretStore,
    SecretStoreInvalid,
    SecretStoreUnavailable,
)
from upvote_monitor.services.source_settings import (
    REDDIT_DEFAULT_OPTIONS,
    REDDIT_SOURCE,
    X_DEFAULT_OPTIONS,
    X_SOURCE,
    decode_options,
    encode_options,
)
from upvote_monitor.services.tagging.profiles import (
    ensure_default_analysis_profiles,
    list_analysis_profiles,
)
from upvote_monitor.sources.x import validate_x_credentials
from upvote_monitor.upvoted import validate_reddit_credentials

router = APIRouter(prefix="/settings", tags=["settings"])
REDDIT_REQUIRED_CREDENTIAL_FIELDS = ("username", "session_cookie")
X_REQUIRED_CREDENTIAL_FIELDS = ("auth_token", "ct0", "twid")
X_SECRET_FIELDS = (*X_REQUIRED_CREDENTIAL_FIELDS, "bearer_token")


@dataclass(frozen=True)
class SourceUpdatePlan:
    source_settings: SourceSettings
    enabled: bool
    options_json: str
    secret_updates: dict[str, str | None]


def _get_settings_or_404(session: Session) -> AppSettings:
    settings = session.get(AppSettings, 1)
    if settings is None:
        raise HTTPException(status_code=500, detail="App settings not initialized")
    return settings


def _get_source_settings(
    session: Session,
    source: str,
    default_options: dict,
    *,
    enabled: bool,
) -> SourceSettings:
    source_settings = session.get(SourceSettings, source)
    if source_settings is None:
        source_settings = SourceSettings(
            source=source,
            enabled=enabled,
            options_json=json.dumps(default_options),
        )
        session.add(source_settings)
        session.commit()
        session.refresh(source_settings)
    return source_settings


def _source_settings_for_update(
    session: Session,
    source: str,
    default_options: dict,
    *,
    enabled: bool,
) -> tuple[SourceSettings, bool]:
    source_settings = session.get(SourceSettings, source)
    if source_settings is not None:
        return source_settings, True
    return (
        SourceSettings(
            source=source,
            enabled=enabled,
            options_json=json.dumps(default_options),
        ),
        False,
    )


def _source_error(
    *,
    code: str,
    source: str,
    fields: tuple[str, ...] | list[str],
    message: str,
) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={
            "code": code,
            "source": source,
            "fields": list(fields),
            "message": message,
        },
    )


def _missing_credentials(source: str, fields: list[str]) -> HTTPException:
    return _source_error(
        code="missing_source_credentials",
        source=source,
        fields=fields,
        message=f"Missing required {source} credentials: {', '.join(fields)}",
    )


def _auth_failed(source: str, fields: tuple[str, ...]) -> HTTPException:
    return _source_error(
        code="source_auth_failed",
        source=source,
        fields=fields,
        message=f"{source.capitalize()} credentials could not be verified",
    )


def _source_secrets_or_400(
    secret_store: SecretStore,
    source: str,
) -> dict[str, str]:
    try:
        return secret_store.get_source_secrets(source)
    except SecretStoreUnavailable as exc:
        raise HTTPException(
            status_code=400,
            detail="UPVOTE_MONITOR_SECRET_KEY is not configured",
        ) from exc
    except SecretStoreInvalid as exc:
        raise HTTPException(
            status_code=400,
            detail="Encrypted secrets could not be read",
        ) from exc


def _update_source_secrets_or_400(
    secret_store: SecretStore,
    source: str,
    updates: dict[str, str | None],
) -> None:
    try:
        secret_store.update_source_secrets(source, updates)
    except SecretStoreUnavailable as exc:
        raise HTTPException(
            status_code=400,
            detail="UPVOTE_MONITOR_SECRET_KEY is not configured",
        ) from exc
    except SecretStoreInvalid as exc:
        raise HTTPException(
            status_code=400,
            detail="Encrypted secrets could not be read",
        ) from exc


def _effective_secrets(
    current_secrets: dict[str, str],
    updates: dict[str, str | None],
) -> dict[str, str]:
    effective = dict(current_secrets)
    for key, value in updates.items():
        if value is None:
            continue
        if value == "":
            effective.pop(key, None)
        else:
            effective[key] = value
    return effective


def _has_new_secret(updates: dict[str, str | None]) -> bool:
    return any(value not in (None, "") for value in updates.values())


def _prepare_reddit_update(
    session: Session,
    body: SettingsUpdate,
    secret_store: SecretStore,
) -> SourceUpdatePlan | None:
    if body.sources is None or body.sources.reddit is None:
        return None

    reddit_update = body.sources.reddit
    reddit_settings, existed = _source_settings_for_update(
        session,
        REDDIT_SOURCE,
        REDDIT_DEFAULT_OPTIONS,
        enabled=True,
    )
    was_enabled = reddit_settings.enabled if existed else False
    next_enabled = (
        reddit_update.enabled
        if reddit_update.enabled is not None
        else reddit_settings.enabled
    )

    options = REDDIT_DEFAULT_OPTIONS | decode_options(reddit_settings)
    options.pop("username", None)
    if reddit_update.page_limit is not None:
        options["page_limit"] = reddit_update.page_limit
    if reddit_update.user_agent is not None:
        options["user_agent"] = reddit_update.user_agent

    secret_updates = {
        field: getattr(reddit_update, field)
        for field in REDDIT_REQUIRED_CREDENTIAL_FIELDS
        if field in reddit_update.model_fields_set
    }
    if reddit_update.session_cookie == "":
        secret_updates["username"] = ""
    has_new_secret = _has_new_secret(secret_updates)
    needs_credentials = next_enabled or has_new_secret
    current_secrets = (
        _source_secrets_or_400(secret_store, REDDIT_SOURCE)
        if secret_updates or needs_credentials
        else {}
    )
    effective_secrets = _effective_secrets(current_secrets, secret_updates)

    if needs_credentials:
        missing = []
        if not effective_secrets.get("username"):
            missing.append("username")
        if not effective_secrets.get("session_cookie"):
            missing.append("session_cookie")
        if missing:
            raise _missing_credentials(REDDIT_SOURCE, missing)

    if has_new_secret or (next_enabled and not was_enabled):
        try:
            validate_reddit_credentials(
                username=effective_secrets["username"],
                session_cookie=effective_secrets["session_cookie"],
                user_agent=str(options["user_agent"]),
            )
        except Exception as exc:
            raise _auth_failed(
                REDDIT_SOURCE,
                REDDIT_REQUIRED_CREDENTIAL_FIELDS,
            ) from exc

    return SourceUpdatePlan(
        source_settings=reddit_settings,
        enabled=bool(next_enabled),
        options_json=encode_options(options),
        secret_updates=secret_updates,
    )


def _prepare_x_update(
    session: Session,
    body: SettingsUpdate,
    secret_store: SecretStore,
) -> SourceUpdatePlan | None:
    if body.sources is None or body.sources.x is None:
        return None

    x_update = body.sources.x
    x_settings, existed = _source_settings_for_update(
        session,
        X_SOURCE,
        X_DEFAULT_OPTIONS,
        enabled=False,
    )
    was_enabled = x_settings.enabled if existed else False
    next_enabled = x_update.enabled if x_update.enabled is not None else x_settings.enabled

    options = X_DEFAULT_OPTIONS | decode_options(x_settings)
    if x_update.page_limit is not None:
        options["page_limit"] = x_update.page_limit
    if x_update.page_size is not None:
        options["page_size"] = x_update.page_size
    if x_update.user_agent is not None:
        options["user_agent"] = x_update.user_agent

    secret_updates = {
        key: getattr(x_update, key)
        for key in X_SECRET_FIELDS
        if key in x_update.model_fields_set
    }
    has_new_secret = _has_new_secret(secret_updates)
    needs_credentials = next_enabled or has_new_secret
    current_secrets = (
        _source_secrets_or_400(secret_store, X_SOURCE)
        if secret_updates or needs_credentials
        else {}
    )
    effective_secrets = _effective_secrets(current_secrets, secret_updates)

    if needs_credentials:
        missing = [
            field
            for field in X_REQUIRED_CREDENTIAL_FIELDS
            if not effective_secrets.get(field)
        ]
        if missing:
            raise _missing_credentials(X_SOURCE, missing)

    if has_new_secret or (next_enabled and not was_enabled):
        try:
            validate_x_credentials(
                auth_token=effective_secrets["auth_token"],
                ct0=effective_secrets["ct0"],
                twid=effective_secrets["twid"],
                bearer_token=effective_secrets.get("bearer_token"),
                user_agent=str(options["user_agent"]),
            )
        except Exception as exc:
            raise _auth_failed(X_SOURCE, X_REQUIRED_CREDENTIAL_FIELDS) from exc

    return SourceUpdatePlan(
        source_settings=x_settings,
        enabled=bool(next_enabled),
        options_json=encode_options(options),
        secret_updates=secret_updates,
    )


def _apply_source_update_plan(
    session: Session,
    secret_store: SecretStore,
    plan: SourceUpdatePlan,
) -> None:
    plan.source_settings.enabled = plan.enabled
    plan.source_settings.options_json = plan.options_json
    if plan.secret_updates:
        _update_source_secrets_or_400(
            secret_store,
            plan.source_settings.source,
            plan.secret_updates,
        )
    session.add(plan.source_settings)


def _settings_response(
    session: Session,
    settings: AppSettings,
) -> SettingsResponse:
    ensure_default_analysis_profiles(session)
    reddit_settings = _get_source_settings(
        session,
        REDDIT_SOURCE,
        REDDIT_DEFAULT_OPTIONS,
        enabled=True,
    )
    x_settings = _get_source_settings(
        session,
        X_SOURCE,
        X_DEFAULT_OPTIONS,
        enabled=False,
    )
    return SettingsResponse.from_db(
        settings,
        reddit_settings,
        x_settings,
        SecretStore(),
        list_analysis_profiles(session),
    )


@router.get("", response_model=SettingsResponse)
def get_settings(session: Session = Depends(get_db_session)) -> SettingsResponse:
    settings = _get_settings_or_404(session)
    return _settings_response(session, settings)


@router.patch("", response_model=SettingsResponse)
def update_settings(
    body: SettingsUpdate,
    session: Session = Depends(get_db_session),
) -> SettingsResponse:
    settings = _get_settings_or_404(session)
    updates = body.model_dump(exclude_unset=True, exclude={"sources"})
    secret_store = SecretStore()
    source_plans = [
        plan
        for plan in (
            _prepare_reddit_update(session, body, secret_store),
            _prepare_x_update(session, body, secret_store),
        )
        if plan is not None
    ]

    if "download_base_dir" in updates:
        Path(updates["download_base_dir"]).mkdir(parents=True, exist_ok=True)

    if "active_analysis_profile_id" in updates:
        profile = session.get(AnalysisProfile, updates["active_analysis_profile_id"])
        if profile is None or not profile.enabled:
            raise HTTPException(
                status_code=400,
                detail="Active analysis profile does not exist or is disabled",
            )

    for key, value in updates.items():
        setattr(settings, key, value)

    session.add(settings)
    for plan in source_plans:
        _apply_source_update_plan(session, secret_store, plan)

    session.commit()
    session.refresh(settings)
    for plan in source_plans:
        session.refresh(plan.source_settings)

    if "refresh_cron" in updates or "refresh_enabled" in updates:
        reschedule_from_settings(settings)

    return _settings_response(session, settings)
