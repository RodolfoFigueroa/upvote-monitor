import mimetypes
import shutil
from pathlib import Path
from threading import Lock
from urllib.parse import quote, unquote, urlparse
from uuid import uuid4

import requests
from sqlmodel import Session, select

from upvote_monitor.constants import REQUESTS_TIMEOUT
from upvote_monitor.db.models import ReviewItem
from upvote_monitor.enums import ApprovalStatus

PREVIEW_CACHE_DIR = Path("/data/preview-cache")
MAX_PREVIEW_BYTES = 10 * 1024 * 1024

IMAGE_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
}
CACHE_EXTENSIONS = tuple(IMAGE_CONTENT_TYPES.values())

IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"})
VIDEO_EXTENSIONS = frozenset({".mp4", ".webm", ".mov", ".m4v"})
REDDIT_IMAGE_HOSTS = frozenset(
    {"i.redd.it", "preview.redd.it", "external-preview.redd.it"}
)

_locks_guard = Lock()
_cache_locks: dict[tuple[str, int], Lock] = {}


class PreviewCacheError(Exception):
    pass


class PreviewCacheNotFound(PreviewCacheError):
    pass


class PreviewCacheFetchError(PreviewCacheError):
    pass


def ensure_preview_cache_dir() -> None:
    PREVIEW_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def item_cache_dir(item_id: str) -> Path:
    return PREVIEW_CACHE_DIR / quote(item_id, safe="")


def cached_preview_url(item_id: str, index: int) -> str:
    return f"/api/items/{quote(item_id, safe='')}/preview/{index}"


def is_cacheable_preview_url(url: str) -> bool:
    parsed = urlparse(url)
    suffix = Path(parsed.path.lower()).suffix
    if suffix in VIDEO_EXTENSIONS:
        return False
    if suffix in IMAGE_EXTENSIONS:
        return True
    return (parsed.hostname or "").lower() in REDDIT_IMAGE_HOSTS


def localize_preview_urls(
    item_id: str,
    approval_status: ApprovalStatus,
    preview_urls: list[str],
) -> list[str]:
    if approval_status != ApprovalStatus.UNDER_REVIEW:
        return preview_urls

    return [
        cached_preview_url(item_id, index) if is_cacheable_preview_url(url) else url
        for index, url in enumerate(preview_urls)
    ]


def delete_item_preview_cache(item_id: str) -> None:
    shutil.rmtree(item_cache_dir(item_id), ignore_errors=True)


def cleanup_stale_preview_cache(session: Session) -> None:
    ensure_preview_cache_dir()
    active_ids = set(
        session.exec(
            select(ReviewItem.id).where(
                ReviewItem.approval_status == ApprovalStatus.UNDER_REVIEW
            )
        ).all()
    )

    for path in PREVIEW_CACHE_DIR.iterdir():
        if not path.is_dir():
            continue
        if unquote(path.name) not in active_ids:
            shutil.rmtree(path, ignore_errors=True)


def find_cached_preview_file(item_id: str, index: int) -> Path | None:
    cache_dir = item_cache_dir(item_id)
    if not cache_dir.is_dir():
        return None

    for extension in CACHE_EXTENSIONS:
        candidate = cache_dir / f"{index}{extension}"
        if candidate.is_file():
            return candidate
    return None


def preview_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    for media_type, extension in IMAGE_CONTENT_TYPES.items():
        if suffix == extension:
            return media_type
    media_type, _ = mimetypes.guess_type(path.name)
    return media_type or "application/octet-stream"


def get_or_fetch_cached_preview(item_id: str, index: int, remote_url: str) -> Path:
    if not is_cacheable_preview_url(remote_url):
        raise PreviewCacheNotFound("Preview URL is not cacheable")

    cached = find_cached_preview_file(item_id, index)
    if cached is not None:
        return cached

    lock = _cache_lock(item_id, index)
    with lock:
        cached = find_cached_preview_file(item_id, index)
        if cached is not None:
            return cached
        return _fetch_preview(item_id, index, remote_url)


def _cache_lock(item_id: str, index: int) -> Lock:
    key = (item_id, index)
    with _locks_guard:
        lock = _cache_locks.get(key)
        if lock is None:
            lock = Lock()
            _cache_locks[key] = lock
        return lock


def _fetch_preview(item_id: str, index: int, remote_url: str) -> Path:
    try:
        response = requests.get(
            remote_url,
            stream=True,
            timeout=REQUESTS_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise PreviewCacheFetchError(str(exc)) from exc

    try:
        response.raise_for_status()
        content_type = _normalized_content_type(
            response.headers.get("Content-Type", "")
        )
        extension = IMAGE_CONTENT_TYPES.get(content_type)
        if extension is None:
            raise PreviewCacheFetchError("Preview response is not an image")

        content_length = response.headers.get("Content-Length")
        if content_length is not None:
            try:
                if int(content_length) > MAX_PREVIEW_BYTES:
                    raise PreviewCacheFetchError("Preview response is too large")
            except ValueError:
                pass

        cache_dir = item_cache_dir(item_id)
        cache_dir.mkdir(parents=True, exist_ok=True)

        target_path = cache_dir / f"{index}{extension}"
        temp_path = cache_dir / f".{index}.{uuid4().hex}.tmp"

        total = 0
        try:
            with open(temp_path, "wb") as file:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_PREVIEW_BYTES:
                        raise PreviewCacheFetchError("Preview response is too large")
                    file.write(chunk)
            temp_path.replace(target_path)
        finally:
            temp_path.unlink(missing_ok=True)

        _remove_other_index_files(cache_dir, index, target_path)
        return target_path
    except requests.RequestException as exc:
        raise PreviewCacheFetchError(str(exc)) from exc
    finally:
        close = getattr(response, "close", None)
        if close is not None:
            close()


def _normalized_content_type(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()


def _remove_other_index_files(cache_dir: Path, index: int, keep_path: Path) -> None:
    for extension in CACHE_EXTENSIONS:
        path = cache_dir / f"{index}{extension}"
        if path != keep_path:
            path.unlink(missing_ok=True)
