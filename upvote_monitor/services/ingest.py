import json
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha1

from sqlmodel import Session, select

from upvote_monitor.db.models import (
    AppSettings,
    MediaAttachment,
    ReviewItem,
    SourceSettings,
)
from upvote_monitor.enums import ApprovalStatus, DownloadStatus
from upvote_monitor.services.approval import compute_initial_status, load_rule_sets
from upvote_monitor.services.secrets import (
    SecretStore,
    SecretStoreInvalid,
    SecretStoreUnavailable,
)
from upvote_monitor.services.source_settings import (
    REDDIT_SOURCE,
    X_SOURCE,
    reddit_options_from_source_settings,
    x_options_from_source_settings,
)
from upvote_monitor.sources import RedditProvider, SourceItem, SourceProvider, XProvider

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    new_items: int
    skipped: int


def get_source_providers(session: Session) -> list[SourceProvider]:
    providers: list[SourceProvider] = []
    secret_store = SecretStore()

    reddit_settings = session.get(SourceSettings, REDDIT_SOURCE)
    if reddit_settings is not None and reddit_settings.enabled:
        reddit_options = reddit_options_from_source_settings(reddit_settings)
        try:
            reddit_secrets = secret_store.get_source_secrets(REDDIT_SOURCE)
        except (SecretStoreInvalid, SecretStoreUnavailable):
            logger.warning("Reddit source is enabled but secrets are unavailable")
            reddit_secrets = {}

        username = reddit_secrets.get("username", "").strip()
        session_cookie = reddit_secrets.get("session_cookie", "")
        if username and session_cookie:
            providers.append(
                RedditProvider(
                    username=username,
                    session_cookie=session_cookie,
                    user_agent=reddit_options.user_agent,
                    page_size=reddit_options.page_size,
                    page_limit=reddit_options.page_limit,
                )
            )
        else:
            missing_fields = [
                field
                for field, value in {
                    "username": username,
                    "session_cookie": session_cookie,
                }.items()
                if not value
            ]
            logger.warning(
                "Reddit source is enabled but required credential fields are "
                "missing: %s",
                ", ".join(missing_fields),
            )

    x_settings = session.get(SourceSettings, X_SOURCE)
    if x_settings is not None and x_settings.enabled:
        x_options = x_options_from_source_settings(x_settings)
        try:
            x_secrets = secret_store.get_source_secrets(X_SOURCE)
        except (SecretStoreInvalid, SecretStoreUnavailable):
            logger.warning("X source is enabled but secrets are unavailable")
            x_secrets = {}

        auth_token = x_secrets.get("auth_token", "")
        ct0 = x_secrets.get("ct0", "")
        twid = x_secrets.get("twid", "")
        if auth_token and ct0 and twid:
            providers.append(
                XProvider(
                    auth_token=auth_token,
                    ct0=ct0,
                    twid=twid,
                    bearer_token=x_secrets.get("bearer_token"),
                    user_agent=x_options.user_agent,
                    page_size=x_options.page_size,
                    page_limit=x_options.page_limit,
                )
            )
        else:
            missing_fields = [
                field
                for field, value in {
                    "auth_token": auth_token,
                    "ct0": ct0,
                    "twid": twid,
                }.items()
                if not value
            ]
            logger.warning(
                "X source is enabled but required credential fields are missing: %s",
                ", ".join(missing_fields),
            )
    return providers


def item_id_for_source(source: str, source_item_id: str) -> str:
    safe_source = re.sub(r"[^A-Za-z0-9_.-]+", "_", source).strip("_").lower()
    safe_item_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", source_item_id).strip("_")
    if safe_item_id == source_item_id and safe_item_id:
        return f"{safe_source}_{safe_item_id}"

    digest = sha1(source_item_id.encode("utf-8")).hexdigest()[:10]
    safe_item_id = safe_item_id or "item"
    return f"{safe_source}_{safe_item_id}_{digest}"


def _existing_source_keys(session: Session) -> set[tuple[str, str]]:
    rows = session.exec(select(ReviewItem.source, ReviewItem.source_item_id)).all()
    return {(source, source_item_id) for source, source_item_id in rows}


def _review_item_from_source_item(source_item: SourceItem) -> ReviewItem:
    return ReviewItem(
        id=item_id_for_source(source_item.source, source_item.source_item_id),
        source=source_item.source,
        source_item_id=source_item.source_item_id,
        title=source_item.title,
        author_name=source_item.author_name,
        author_label=source_item.author_label,
        community_name=source_item.community_name,
        community_label=source_item.community_label,
        item_kind=source_item.item_kind,
        source_url=source_item.source_url,
        created_at=source_item.created_at,
        approval_status=ApprovalStatus.UNDER_REVIEW,
        download_status=DownloadStatus.PENDING,
        raw_data_json=json.dumps(source_item.raw_data),
        media_count=len(source_item.media),
    )


def _attachments_from_source_item(
    source_item: SourceItem,
    item_id: str,
    approval_status: ApprovalStatus,
) -> Iterable[MediaAttachment]:
    for attachment in source_item.media:
        yield MediaAttachment(
            item_id=item_id,
            sort_index=attachment.sort_index,
            media_type=attachment.media_type,
            content_type=attachment.content_type,
            download_url=attachment.download_url,
            preview_url=attachment.preview_url,
            width=attachment.width,
            height=attachment.height,
            duration_ms=attachment.duration_ms,
            extension=attachment.extension,
            download_strategy=attachment.download_strategy,
            approval_status=approval_status,
        )


def ingest_items(
    session: Session,
    providers: Iterable[SourceProvider] | None = None,
) -> IngestResult:
    settings = session.get(AppSettings, 1)
    if settings is None:
        msg = "App settings not initialized"
        raise RuntimeError(msg)

    whitelist, blacklist = load_rule_sets(session)
    existing_keys = _existing_source_keys(session)

    new_items = 0
    skipped = 0

    active_providers = (
        providers if providers is not None else get_source_providers(session)
    )
    active_providers = list(active_providers)
    if not active_providers:
        logger.warning("No source providers are configured for this refresh")

    for provider in active_providers:
        provider_source = getattr(provider, "source", provider.__class__.__name__)
        provider_new_items = 0
        provider_skipped = 0
        for source_item in provider.iter_liked_items():
            if not source_item.media:
                skipped += 1
                provider_skipped += 1
                continue

            source_key = (source_item.source, source_item.source_item_id)
            if source_key in existing_keys:
                skipped += 1
                provider_skipped += 1
                continue

            item = _review_item_from_source_item(source_item)
            item.approval_status = compute_initial_status(
                item,
                settings.approval_mode,
                whitelist,
                blacklist,
            )

            session.add(item)
            for attachment in _attachments_from_source_item(
                source_item,
                item.id,
                item.approval_status,
            ):
                session.add(attachment)

            existing_keys.add(source_key)
            new_items += 1
            provider_new_items += 1

        logger.info(
            "Source refresh completed for %s: %s new, %s skipped",
            provider_source,
            provider_new_items,
            provider_skipped,
        )

    session.commit()
    return IngestResult(new_items=new_items, skipped=skipped)
