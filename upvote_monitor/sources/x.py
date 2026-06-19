from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import requests

from upvote_monitor.constants import REQUESTS_TIMEOUT
from upvote_monitor.enums import DownloadStrategy
from upvote_monitor.services.source_settings import X_DEFAULT_USER_AGENT
from upvote_monitor.sources.base import MediaAttachmentInput, SourceItem

SOURCE = "x"
DOMAIN = "x.com"
DEFAULT_BEARER_TOKEN = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"
    "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

GQL_BASE_URL = f"https://{DOMAIN}/i/api/graphql"
LIKES_URL = f"{GQL_BASE_URL}/IohM3gxQHfvWePH5E3KuNA/Likes"
USER_BY_SCREEN_NAME_URL = f"{GQL_BASE_URL}/NimuplG1OB7Fd2btCLdBOw/UserByScreenName"
SETTINGS_URLS = (
    f"https://api.{DOMAIN}/1.1/account/settings.json",
    "https://api.twitter.com/1.1/account/settings.json",
    f"https://{DOMAIN}/i/api/1.1/account/settings.json",
)

FEATURES = {
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "tweetypie_unmention_optimization_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "responsive_web_media_download_video_enabled": False,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}

USER_FEATURES = {
    "hidden_profile_likes_enabled": True,
    "hidden_profile_subscriptions_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "subscriptions_verification_info_is_identity_verified_enabled": True,
    "subscriptions_verification_info_verified_since_enabled": True,
    "highlights_tweets_tab_ui_enabled": True,
    "responsive_web_twitter_article_notes_tab_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
}


class XSourceError(RuntimeError):
    pass


def _flatten_params(params: dict[str, Any]) -> dict[str, str]:
    flattened = {}
    for key, value in params.items():
        if isinstance(value, (dict, list)):
            flattened[key] = json_dumps_compact(value)
        else:
            flattened[key] = str(value)
    return flattened


def json_dumps_compact(value: Any) -> str:
    import json

    return json.dumps(value, separators=(",", ":"))


def _find_values(obj: Any, key: str) -> list[Any]:
    results = []
    if isinstance(obj, dict):
        if key in obj:
            results.append(obj[key])
        for value in obj.values():
            results.extend(_find_values(value, key))
    elif isinstance(obj, list):
        for value in obj:
            results.extend(_find_values(value, key))
    return results


def user_id_from_twid(twid: str | None) -> str | None:
    if not twid:
        return None
    decoded = unquote(twid)
    user_id = decoded.removeprefix("u=") if decoded.startswith("u=") else decoded
    return user_id if user_id.isdigit() else None


def _extension_from_url(url: str) -> str | None:
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix or None


def _photo_original_url(url: str) -> str:
    if "?" in url:
        return url
    extension = (_extension_from_url(url) or ".jpg").removeprefix(".")
    return f"{url}?format={extension}&name=orig"


def _parse_created_at(value: str | None) -> datetime:
    if value:
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        except (TypeError, ValueError):
            pass
    return datetime.now(timezone.utc)


def _request_json(
    session: requests.Session,
    url: str,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    response = session.get(url, params=params, timeout=REQUESTS_TIMEOUT)
    try:
        data = response.json()
    except ValueError as exc:
        raise XSourceError(
            f"X returned non-JSON response with status {response.status_code}"
        ) from exc

    if response.status_code >= 400:
        raise XSourceError(f"X returned HTTP {response.status_code}: {data}")
    if isinstance(data, dict) and data.get("errors"):
        raise XSourceError(f"X returned GraphQL errors: {data['errors']}")
    if not isinstance(data, dict):
        raise XSourceError("X returned an unexpected response shape")
    return data


def _build_session(
    *,
    auth_token: str,
    ct0: str,
    twid: str | None,
    bearer_token: str,
    user_agent: str,
) -> requests.Session:
    session = requests.Session()
    cookies = {"auth_token": auth_token, "ct0": ct0}
    if twid:
        cookies["twid"] = twid
    session.cookies.update(cookies)
    session.headers.update(
        {
            "authorization": f"Bearer {bearer_token}",
            "content-type": "application/json",
            "x-twitter-auth-type": "OAuth2Session",
            "x-twitter-active-user": "yes",
            "referer": f"https://{DOMAIN}/",
            "user-agent": user_agent,
            "accept-language": "en-US,en;q=0.9",
            "x-twitter-client-language": "en-US",
            "x-csrf-token": ct0,
        }
    )
    return session


def _user_by_screen_name(
    session: requests.Session,
    screen_name: str,
) -> tuple[str, str]:
    clean_name = screen_name.lstrip("@")
    params = _flatten_params(
        {
            "variables": {
                "screen_name": clean_name,
                "withSafetyModeUserFields": False,
            },
            "features": USER_FEATURES,
            "fieldToggles": {"withAuxiliaryUserLabels": False},
        }
    )
    data = _request_json(session, USER_BY_SCREEN_NAME_URL, params=params)
    user_data = data.get("data", {}).get("user", {}).get("result")
    if not isinstance(user_data, dict):
        raise XSourceError(f"X did not return user data for @{clean_name}")
    user_legacy = user_data.get("legacy", {})
    resolved_screen_name = (
        str(user_legacy.get("screen_name")) if isinstance(user_legacy, dict) else None
    )
    return str(user_data["rest_id"]), resolved_screen_name or clean_name


def _authenticated_user(session: requests.Session) -> tuple[str, str]:
    errors = []
    for settings_url in SETTINGS_URLS:
        try:
            settings = _request_json(session, settings_url)
            break
        except XSourceError as exc:
            errors.append(f"{settings_url}: {exc}")
    else:
        joined_errors = "; ".join(errors)
        raise XSourceError(f"could not discover authenticated X user: {joined_errors}")

    screen_name = settings.get("screen_name")
    if not screen_name:
        raise XSourceError("X account settings did not include a screen_name")
    return _user_by_screen_name(session, str(screen_name))


def validate_x_credentials(
    *,
    auth_token: str,
    ct0: str,
    twid: str,
    bearer_token: str | None,
    user_agent: str,
) -> None:
    twid_user_id = user_id_from_twid(twid)
    if twid_user_id is None:
        raise XSourceError("X twid cookie did not contain a user id")

    session = _build_session(
        auth_token=auth_token,
        ct0=ct0,
        twid=twid,
        bearer_token=bearer_token or DEFAULT_BEARER_TOKEN,
        user_agent=user_agent,
    )
    _user_likes_page(session, twid_user_id, 1, None)


def _raw_tweet_from_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    for result in _find_values(entry, "result"):
        if not isinstance(result, dict):
            continue
        tweet_data = result.get("tweet", result)
        if not isinstance(tweet_data, dict):
            continue
        if tweet_data.get("__typename") == "TweetTombstone":
            continue
        legacy = tweet_data.get("legacy", {})
        if "core" in tweet_data and isinstance(legacy, dict) and "full_text" in legacy:
            return tweet_data
    return None


def _tweet_from_result_container(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None

    result = value.get("result", value)
    if not isinstance(result, dict):
        return None
    if result.get("__typename") == "TweetTombstone":
        return None

    tweet_data = result.get("tweet", result)
    if not isinstance(tweet_data, dict):
        return None

    legacy = tweet_data.get("legacy", {})
    return tweet_data if isinstance(legacy, dict) else None


def _referenced_tweets(tweet_data: dict[str, Any]) -> Iterable[dict[str, Any]]:
    legacy = tweet_data.get("legacy", {})
    containers = [tweet_data]
    if isinstance(legacy, dict):
        containers.append(legacy)

    seen_ids: set[int] = set()
    for container in containers:
        for key in ("retweeted_status_result", "quoted_status_result"):
            referenced = _tweet_from_result_container(container.get(key))
            if referenced is None or id(referenced) in seen_ids:
                continue
            seen_ids.add(id(referenced))
            yield referenced


def _raw_media_entries(tweet_data: dict[str, Any]) -> list[Any]:
    legacy = tweet_data.get("legacy", {})
    if not isinstance(legacy, dict):
        return []

    extended_entities = legacy.get("extended_entities", {})
    entities = legacy.get("entities", {})
    media_entries = []
    if isinstance(extended_entities, dict):
        media_entries = extended_entities.get("media") or []
    if not media_entries and isinstance(entities, dict):
        media_entries = entities.get("media") or []
    return media_entries if isinstance(media_entries, list) else []


def _attachment_from_raw_media(
    media: dict[str, Any],
    sort_index: int,
) -> tuple[MediaAttachmentInput, str] | None:
    x_media_type = media.get("type")
    original_info = media.get("original_info") or {}
    width = original_info.get("width") if isinstance(original_info, dict) else None
    height = original_info.get("height") if isinstance(original_info, dict) else None

    if x_media_type == "photo":
        url = media.get("media_url_https")
        if not url:
            return None
        download_url = _photo_original_url(str(url))
        return (
            MediaAttachmentInput(
                sort_index=sort_index,
                media_type="image",
                content_type=None,
                download_url=download_url,
                preview_url=str(url),
                width=width,
                height=height,
                extension=_extension_from_url(str(url)),
                download_strategy=DownloadStrategy.HTTP,
            ),
            "photo",
        )

    if x_media_type not in {"video", "animated_gif"}:
        return None

    video_info = media.get("video_info") or {}
    variants = video_info.get("variants", []) if isinstance(video_info, dict) else []
    streams = [
        variant
        for variant in variants
        if isinstance(variant, dict)
        and (variant.get("content_type") or "").startswith("video")
        and variant.get("url")
    ]
    if not streams:
        return None

    stream = max(streams, key=lambda variant: int(variant.get("bitrate") or 0))
    stream_url = str(stream["url"])
    preview_url = media.get("media_url_https")
    return (
        MediaAttachmentInput(
            sort_index=sort_index,
            media_type="video",
            content_type=stream.get("content_type"),
            download_url=stream_url,
            preview_url=str(preview_url) if preview_url else None,
            width=width,
            height=height,
            duration_ms=video_info.get("duration_millis"),
            extension=_extension_from_url(stream_url),
            download_strategy=DownloadStrategy.HTTP,
        ),
        str(x_media_type),
    )


def _item_kind(media_types: list[str]) -> str:
    unique_types = set(media_types)
    if unique_types == {"photo"}:
        return "x_photo"
    if unique_types == {"animated_gif"}:
        return "x_gif"
    if unique_types == {"video"}:
        return "x_video"
    return "x_mixed"


def source_item_from_raw_tweet(tweet_data: dict[str, Any]) -> SourceItem | None:
    legacy = tweet_data.get("legacy", {})
    if not isinstance(legacy, dict):
        return None

    user_data = tweet_data.get("core", {}).get("user_results", {}).get("result", {})
    user_legacy = user_data.get("legacy", {}) if isinstance(user_data, dict) else {}
    if not isinstance(user_legacy, dict):
        user_legacy = {}

    tweet_id = str(tweet_data.get("rest_id") or legacy.get("id_str") or "")
    if not tweet_id:
        return None

    screen_name = user_legacy.get("screen_name")
    normalized_screen_name = str(screen_name).lower() if screen_name else None
    display_name = user_legacy.get("name")
    note_result = (
        tweet_data.get("note_tweet", {})
        .get("note_tweet_results", {})
        .get("result", {})
    )
    text = (
        note_result.get("text") if isinstance(note_result, dict) else None
    ) or legacy.get("full_text")
    title = str(text or "")
    if not title:
        title = (
            f"X post by @{screen_name}"
            if screen_name
            else f"X post {tweet_id}"
        )

    attachments: list[MediaAttachmentInput] = []
    x_media_types: list[str] = []
    seen_download_urls: set[str] = set()
    for media_tweet in (tweet_data, *_referenced_tweets(tweet_data)):
        for media in _raw_media_entries(media_tweet):
            if not isinstance(media, dict):
                continue
            attachment = _attachment_from_raw_media(media, len(attachments))
            if attachment is None:
                continue
            media_attachment, x_media_type = attachment
            if media_attachment.download_url in seen_download_urls:
                continue
            attachments.append(media_attachment)
            x_media_types.append(x_media_type)
            seen_download_urls.add(media_attachment.download_url)

    source_url = (
        f"https://x.com/{screen_name}/status/{tweet_id}"
        if screen_name
        else f"https://x.com/i/web/status/{tweet_id}"
    )
    return SourceItem(
        source=SOURCE,
        source_item_id=tweet_id,
        title=title,
        author_name=normalized_screen_name,
        author_label=f"@{screen_name}" if screen_name else display_name,
        community_name=None,
        community_label=None,
        item_kind=_item_kind(x_media_types) if x_media_types else "x_post",
        source_url=source_url,
        created_at=_parse_created_at(legacy.get("created_at")),
        raw_data=tweet_data,
        media=attachments,
    )


def _extract_cursor(entry: dict[str, Any]) -> str | None:
    content = entry.get("content", {})
    if not isinstance(content, dict):
        return None
    if content.get("cursorType") == "Bottom":
        return content.get("value")
    if entry.get("entryId", "").startswith("cursor-bottom"):
        return content.get("value")
    return None


def raw_tweets_from_likes_response(
    data: dict[str, Any],
) -> tuple[list[dict[str, Any]], str | None]:
    instructions_list = _find_values(data, "instructions")
    if not instructions_list:
        return [], None

    entries: list[dict[str, Any]] = []
    for instructions in instructions_list:
        if not isinstance(instructions, list):
            continue
        for instruction in instructions:
            if isinstance(instruction, dict):
                entries.extend(instruction.get("entries", []))

    tweets = []
    next_cursor = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        cursor = _extract_cursor(entry)
        if cursor:
            next_cursor = cursor

        entry_id = entry.get("entryId", "")
        if not entry_id.startswith(("tweet", "profile-conversation", "profile-grid")):
            continue

        item = entry
        if entry_id.startswith("profile-conversation"):
            conversation_items = entry.get("content", {}).get("items", [])
            if not conversation_items:
                continue
            item = conversation_items[0]

        tweet_data = _raw_tweet_from_entry(item)
        if tweet_data is not None:
            tweets.append(tweet_data)

    return tweets, next_cursor


def _user_likes_page(
    session: requests.Session,
    user_id: str,
    count: int,
    cursor: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    variables: dict[str, Any] = {
        "userId": user_id,
        "count": count,
        "includePromotedContent": True,
        "withQuickPromoteEligibilityTweetFields": True,
        "withVoice": True,
        "withV2Timeline": True,
    }
    if cursor is not None:
        variables["cursor"] = cursor

    data = _request_json(
        session,
        LIKES_URL,
        params=_flatten_params({"variables": variables, "features": FEATURES}),
    )
    return raw_tweets_from_likes_response(data)


class XProvider:
    source = SOURCE

    def __init__(
        self,
        *,
        auth_token: str,
        ct0: str,
        twid: str | None,
        bearer_token: str | None,
        user_agent: str,
        page_size: int,
        page_limit: int,
    ) -> None:
        self.auth_token = auth_token
        self.ct0 = ct0
        self.twid = twid
        self.bearer_token = bearer_token or DEFAULT_BEARER_TOKEN
        self.user_agent = user_agent or X_DEFAULT_USER_AGENT
        self.page_size = page_size
        self.page_limit = page_limit

    def _authenticated_user_id(self, session: requests.Session) -> str:
        if twid_user_id := user_id_from_twid(self.twid):
            return twid_user_id
        user_id, _screen_name = _authenticated_user(session)
        return user_id

    def iter_liked_items(self) -> Iterable[SourceItem]:
        session = _build_session(
            auth_token=self.auth_token,
            ct0=self.ct0,
            twid=self.twid,
            bearer_token=self.bearer_token,
            user_agent=self.user_agent,
        )
        authenticated_user_id = self._authenticated_user_id(session)

        cursor = None
        for _ in range(self.page_limit):
            raw_tweets, cursor = _user_likes_page(
                session,
                authenticated_user_id,
                self.page_size,
                cursor,
            )
            for raw_tweet in raw_tweets:
                item = source_item_from_raw_tweet(raw_tweet)
                if item is not None and item.media:
                    yield item
            if not cursor:
                break
