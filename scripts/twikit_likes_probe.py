"""Probe X/Twitter liked tweets without Twikit.

This is intentionally standalone. It does not touch the database, review queue,
or downloader; it only verifies whether X's private web GraphQL endpoint can
fetch liked tweets and native media metadata using browser cookies.

Examples:
    $env:X_COOKIES_JSON = '{"auth_token":"...","ct0":"...","twid":"u%3D123"}'
    uv run python scripts/twikit_likes_probe.py --pages 1 --count 20

    uv run python scripts/twikit_likes_probe.py --cookies-file cookies.json --username some_handle

Cookie files may be simple JSON objects, for example:
    {"auth_token": "...", "ct0": "...", "twid": "u%3D123"}

or browser-export JSON lists, for example:
    [{"name": "auth_token", "value": "..."}, {"name": "ct0", "value": "..."}]
"""

from __future__ import annotations

import argparse
import json
import os
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import requests


DOMAIN = "x.com"
BEARER_TOKEN = (
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

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch a small sample of X/Twitter liked tweets via direct web GraphQL."
    )
    parser.add_argument(
        "--cookies-file",
        type=Path,
        default=os.getenv("X_COOKIES_FILE"),
        help="Path to JSON cookies. Defaults to X_COOKIES_FILE.",
    )
    parser.add_argument(
        "--cookies-json",
        default=os.getenv("X_COOKIES_JSON"),
        help="Raw JSON cookies. Defaults to X_COOKIES_JSON.",
    )
    parser.add_argument(
        "--username",
        help=(
            "Screen name whose likes to fetch. Defaults to the authenticated "
            "account resolved from twid or account settings."
        ),
    )
    parser.add_argument(
        "--user-id",
        help="Numeric X user id. Skips username/self resolution when provided.",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=1,
        help="Number of Likes result pages to request.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=20,
        help="Items requested per page.",
    )
    parser.add_argument(
        "--user-agent",
        default=os.getenv("X_USER_AGENT", DEFAULT_USER_AGENT),
        help="User-Agent for X requests. Defaults to X_USER_AGENT or a browser UA.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print counts and media stats without printing individual liked items.",
    )
    parser.add_argument(
        "--direct-gql",
        action="store_true",
        help="Compatibility no-op. This script always uses direct GraphQL.",
    )
    return parser.parse_args()


def normalize_cookies(raw: Any) -> dict[str, str]:
    if isinstance(raw, dict):
        cookies = raw.get("cookies", raw)
        if isinstance(cookies, list):
            return normalize_cookies(cookies)
        normalized: dict[str, str] = {}
        for name, value in cookies.items():
            if isinstance(value, dict) and "value" in value:
                normalized[str(name)] = str(value["value"])
            else:
                normalized[str(name)] = str(value)
        return normalized

    if isinstance(raw, list):
        normalized = {}
        for cookie in raw:
            if not isinstance(cookie, dict):
                continue
            name = cookie.get("name")
            value = cookie.get("value")
            if name is not None and value is not None:
                normalized[str(name)] = str(value)
        return normalized

    msg = "cookies must be a JSON object or a browser-export JSON list"
    raise ValueError(msg)


def load_cookies(args: argparse.Namespace) -> dict[str, str]:
    if args.cookies_json:
        raw = json.loads(args.cookies_json)
    elif args.cookies_file:
        raw = json.loads(Path(args.cookies_file).read_text(encoding="utf-8"))
    else:
        msg = (
            "provide --cookies-file, --cookies-json, X_COOKIES_FILE, or X_COOKIES_JSON"
        )
        raise ValueError(msg)

    cookies = normalize_cookies(raw)
    missing = {"auth_token", "ct0"} - cookies.keys()
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"cookie data is missing required cookie(s): {missing_list}")
    return cookies


def user_id_from_twid(cookies: dict[str, str]) -> str | None:
    twid = cookies.get("twid")
    if not twid:
        return None

    decoded = unquote(twid)
    user_id = decoded.removeprefix("u=") if decoded.startswith("u=") else decoded
    return user_id if user_id.isdigit() else None


def flatten_params(params: dict[str, Any]) -> dict[str, str]:
    flattened = {}
    for key, value in params.items():
        flattened[key] = (
            json.dumps(value, separators=(",", ":"))
            if isinstance(value, (dict, list))
            else str(value)
        )
    return flattened


def find_values(obj: Any, key: str) -> list[Any]:
    results = []
    if isinstance(obj, dict):
        if key in obj:
            results.append(obj[key])
        for value in obj.values():
            results.extend(find_values(value, key))
    elif isinstance(obj, list):
        for value in obj:
            results.extend(find_values(value, key))
    return results


def build_session(cookies: dict[str, str], user_agent: str) -> requests.Session:
    session = requests.Session()
    session.cookies.update(cookies)
    session.headers.update(
        {
            "authorization": f"Bearer {BEARER_TOKEN}",
            "content-type": "application/json",
            "x-twitter-auth-type": "OAuth2Session",
            "x-twitter-active-user": "yes",
            "referer": f"https://{DOMAIN}/",
            "user-agent": user_agent,
            "accept-language": "en-US,en;q=0.9",
            "x-twitter-client-language": "en-US",
            "x-csrf-token": cookies["ct0"],
        }
    )
    return session


def get_json(
    session: requests.Session,
    url: str,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    response = session.get(url, params=params, timeout=30)
    try:
        data = response.json()
    except requests.JSONDecodeError as exc:
        raise RuntimeError(
            f"X returned non-JSON response with status {response.status_code}"
        ) from exc

    if response.status_code >= 400:
        raise RuntimeError(f"X returned HTTP {response.status_code}: {data}")
    if isinstance(data, dict) and data.get("errors"):
        raise RuntimeError(f"X returned GraphQL errors: {data['errors']}")
    return data


def user_by_screen_name(session: requests.Session, screen_name: str) -> tuple[str, str]:
    clean_name = screen_name.lstrip("@")
    params = flatten_params(
        {
            "variables": {
                "screen_name": clean_name,
                "withSafetyModeUserFields": False,
            },
            "features": USER_FEATURES,
            "fieldToggles": {"withAuxiliaryUserLabels": False},
        }
    )
    data = get_json(session, USER_BY_SCREEN_NAME_URL, params=params)
    user_data = data.get("data", {}).get("user", {}).get("result")
    if not user_data:
        raise RuntimeError(f"X did not return user data for @{clean_name}")
    user_legacy = user_data.get("legacy", {})
    return str(user_data["rest_id"]), str(user_legacy.get("screen_name") or clean_name)


def authenticated_user(session: requests.Session) -> tuple[str, str]:
    errors = []
    for settings_url in SETTINGS_URLS:
        try:
            settings = get_json(session, settings_url)
            break
        except RuntimeError as exc:
            errors.append(f"{settings_url}: {exc}")
    else:
        joined_errors = "; ".join(errors)
        raise RuntimeError(f"could not discover authenticated X user: {joined_errors}")

    screen_name = settings.get("screen_name")
    if not screen_name:
        msg = "X account settings did not include a screen_name"
        raise RuntimeError(msg)
    return user_by_screen_name(session, screen_name)


def parse_created_at(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError):
        return value


def raw_tweet_from_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    for result in find_values(entry, "result"):
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


def raw_media_to_dict(media: dict[str, Any], sort_index: int) -> dict[str, Any] | None:
    media_type = media.get("type")
    original_info = media.get("original_info") or {}
    width = original_info.get("width")
    height = original_info.get("height")

    if media_type == "photo":
        url = media.get("media_url_https")
        if not url:
            return None
        return {
            "sort_index": sort_index,
            "media_type": "image",
            "download_url": url,
            "preview_url": url,
            "content_type": None,
            "width": width,
            "height": height,
            "duration_ms": None,
        }

    if media_type not in {"video", "animated_gif"}:
        return None

    video_info = media.get("video_info") or {}
    variants = [
        variant
        for variant in video_info.get("variants", [])
        if (variant.get("content_type") or "").startswith("video")
        and variant.get("url")
    ]
    if not variants:
        return None

    stream = max(variants, key=lambda variant: int(variant.get("bitrate") or 0))
    return {
        "sort_index": sort_index,
        "media_type": "video" if media_type == "video" else "animated_gif",
        "download_url": stream["url"],
        "preview_url": media.get("media_url_https"),
        "content_type": stream.get("content_type"),
        "width": width,
        "height": height,
        "duration_ms": video_info.get("duration_millis"),
        "bitrate": stream.get("bitrate"),
    }


def raw_tweet_to_dict(tweet_data: dict[str, Any]) -> dict[str, Any]:
    legacy = tweet_data.get("legacy", {})
    user_data = tweet_data.get("core", {}).get("user_results", {}).get("result", {})
    user_legacy = user_data.get("legacy", {})
    tweet_id = str(tweet_data.get("rest_id") or legacy.get("id_str"))
    screen_name = user_legacy.get("screen_name")
    note_result = (
        tweet_data.get("note_tweet", {}).get("note_tweet_results", {}).get("result", {})
    )
    text = note_result.get("text") or legacy.get("full_text") or ""
    media_entries = (
        legacy.get("extended_entities", {}).get("media")
        or legacy.get("entities", {}).get("media")
        or []
    )
    media = [
        media_dict
        for index, entry in enumerate(media_entries)
        if isinstance(entry, dict)
        and (media_dict := raw_media_to_dict(entry, index)) is not None
    ]
    return {
        "source": "x",
        "source_item_id": tweet_id,
        "title": text,
        "author_name": screen_name,
        "author_label": f"@{screen_name}" if screen_name else user_legacy.get("name"),
        "item_kind": "tweet",
        "source_url": (
            f"https://x.com/{screen_name}/status/{tweet_id}"
            if screen_name
            else f"https://x.com/i/web/status/{tweet_id}"
        ),
        "created_at": parse_created_at(legacy.get("created_at")),
        "media_count": len(media),
        "media": media,
    }


def extract_cursor(entry: dict[str, Any]) -> str | None:
    content = entry.get("content", {})
    if content.get("cursorType") == "Bottom":
        return content.get("value")
    if entry.get("entryId", "").startswith("cursor-bottom"):
        return content.get("value")
    return None


def tweets_from_likes_response(
    data: dict[str, Any],
) -> tuple[list[dict[str, Any]], str | None]:
    instructions_list = find_values(data, "instructions")
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
        cursor = extract_cursor(entry)
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

        tweet_data = raw_tweet_from_entry(item)
        if tweet_data is not None:
            tweets.append(raw_tweet_to_dict(tweet_data))

    return tweets, next_cursor


def user_likes_page(
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

    data = get_json(
        session,
        LIKES_URL,
        params=flatten_params({"variables": variables, "features": FEATURES}),
    )
    return tweets_from_likes_response(data)


def resolve_target_user(
    session: requests.Session,
    cookies: dict[str, str],
    args: argparse.Namespace,
) -> tuple[str, str | None]:
    if args.user_id:
        return args.user_id, args.username
    if args.username:
        return user_by_screen_name(session, args.username)
    if twid_user_id := user_id_from_twid(cookies):
        return twid_user_id, None
    return authenticated_user(session)


def summarize_items(items: list[dict[str, Any]]) -> dict[str, int]:
    media_counts: dict[str, int] = {}
    for item in items:
        for media in item["media"]:
            media_type = media["media_type"]
            media_counts[media_type] = media_counts.get(media_type, 0) + 1
    return media_counts


def fetch_likes(args: argparse.Namespace) -> dict[str, Any]:
    cookies = load_cookies(args)
    session = build_session(cookies, args.user_agent)
    user_id, username = resolve_target_user(session, cookies, args)

    page_count = max(args.pages, 1)
    per_page = max(args.count, 1)
    cursor = None
    items = []
    for _ in range(page_count):
        tweets, cursor = user_likes_page(session, user_id, per_page, cursor)
        items.extend(tweets)
        if not cursor:
            break

    payload: dict[str, Any] = {
        "target_user_id": user_id,
        "target_username": username,
        "pages_requested": page_count,
        "count_requested": per_page,
        "items_returned": len(items),
        "items_with_media": sum(1 for item in items if item["media"]),
        "media_by_type": summarize_items(items),
    }
    if not args.summary_only:
        payload["items"] = items
    return payload


def main() -> int:
    args = parse_args()
    try:
        payload = fetch_likes(args)
    except Exception as exc:  # noqa: BLE001 - this probe should show auth/API breakage plainly.
        print(
            json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, indent=2)
        )
        return 2

    print(json.dumps({"ok": True, **payload}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
