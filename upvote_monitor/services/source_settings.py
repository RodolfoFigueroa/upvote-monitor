import json
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session

from upvote_monitor.db.models import SourceSettings

REDDIT_SOURCE = "reddit"
X_SOURCE = "x"
REDDIT_DEFAULT_OPTIONS = {
    "page_limit": 10,
    "page_size": 100,
    "user_agent": "MyPersonalArchiveScript/1.0",
}
REDDIT_DEFAULT_USER_AGENT = "MyPersonalArchiveScript/1.0"
REDDIT_MIN_PAGE_LIMIT = 1
REDDIT_MAX_PAGE_LIMIT = 10
X_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
X_DEFAULT_OPTIONS = {
    "page_limit": 5,
    "page_size": 20,
    "user_agent": X_DEFAULT_USER_AGENT,
}
X_MIN_PAGE_LIMIT = 1
X_MAX_PAGE_LIMIT = 10
X_MIN_PAGE_SIZE = 1
X_MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class RedditSourceOptions:
    page_limit: int
    page_size: int
    user_agent: str


@dataclass(frozen=True)
class XSourceOptions:
    page_limit: int
    page_size: int
    user_agent: str


def _ensure_source_settings(
    session: Session,
    *,
    source: str,
    enabled: bool,
    options: dict[str, Any],
) -> None:
    if session.get(SourceSettings, source) is None:
        session.add(
            SourceSettings(
                source=source,
                enabled=enabled,
                options_json=json.dumps(options),
            ),
        )


def ensure_default_source_settings(session: Session) -> None:
    _ensure_source_settings(
        session,
        source=REDDIT_SOURCE,
        enabled=True,
        options=REDDIT_DEFAULT_OPTIONS,
    )
    _ensure_source_settings(
        session,
        source=X_SOURCE,
        enabled=False,
        options=X_DEFAULT_OPTIONS,
    )
    session.commit()


def decode_options(source_settings: SourceSettings | None) -> dict[str, Any]:
    if source_settings is None:
        return {}
    try:
        value = json.loads(source_settings.options_json)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def encode_options(options: dict[str, Any]) -> str:
    return json.dumps(options, sort_keys=True)


def clamp_reddit_page_limit(value: int) -> int:
    return max(REDDIT_MIN_PAGE_LIMIT, min(REDDIT_MAX_PAGE_LIMIT, value))


def clamp_x_page_limit(value: int) -> int:
    return max(X_MIN_PAGE_LIMIT, min(X_MAX_PAGE_LIMIT, value))


def clamp_x_page_size(value: int) -> int:
    return max(X_MIN_PAGE_SIZE, min(X_MAX_PAGE_SIZE, value))


def reddit_options_from_source_settings(
    source_settings: SourceSettings | None,
) -> RedditSourceOptions:
    options = REDDIT_DEFAULT_OPTIONS | decode_options(source_settings)
    return RedditSourceOptions(
        page_limit=clamp_reddit_page_limit(int(options.get("page_limit", 10))),
        page_size=100,
        user_agent=str(options.get("user_agent", "")).strip()
        or REDDIT_DEFAULT_USER_AGENT,
    )


def x_options_from_source_settings(
    source_settings: SourceSettings | None,
) -> XSourceOptions:
    options = X_DEFAULT_OPTIONS | decode_options(source_settings)
    return XSourceOptions(
        page_limit=clamp_x_page_limit(int(options.get("page_limit", 5))),
        page_size=clamp_x_page_size(int(options.get("page_size", 20))),
        user_agent=str(options.get("user_agent", "")).strip() or X_DEFAULT_USER_AGENT,
    )
