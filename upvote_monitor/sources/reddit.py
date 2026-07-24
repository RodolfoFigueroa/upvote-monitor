from collections.abc import Iterable
from urllib.parse import urlparse

from upvote_monitor.enums import DownloadStrategy
from upvote_monitor.models.child import Children
from upvote_monitor.sources.base import MediaAttachmentInput, SourceItem
from upvote_monitor.upvoted import upvoted_posts_generator

SOURCE = "reddit"
REDDIT_BASE_URL = "https://reddit.com"


def normalize_reddit_community(name: str) -> str:
    name = name.strip().lower()
    return name.removeprefix("r/")


def reddit_community_label(name: str) -> str:
    return f"r/{normalize_reddit_community(name)}"


def _extension_from_url(url: str) -> str | None:
    suffix = urlparse(url).path.rsplit(".", 1)
    if len(suffix) != 2:
        return None
    extension = suffix[1].strip().lower()
    if not extension:
        return None
    return f".{extension}"


def _media_type_for_child(child: Children, download_url: str) -> str:
    if child.data.post_hint in {"hosted:video", "rich:video"}:
        return "video"
    extension = _extension_from_url(download_url)
    if extension in {".mp4", ".webm", ".mov", ".m4v"}:
        return "video"
    return "image"


def _download_strategy_for_child(child: Children) -> DownloadStrategy:
    if child.data.post_hint == "rich:video":
        return DownloadStrategy.YT_DLP
    return DownloadStrategy.HTTP


def _absolute_reddit_url(permalink: str) -> str:
    if permalink.startswith(("http://", "https://")):
        return permalink
    return f"{REDDIT_BASE_URL}{permalink}"


def child_to_source_item(child: Children) -> SourceItem:
    download_urls = [str(url) for url in child.data.media_download_url]
    preview_urls = [str(url) for url in child.data.media_preview_url]
    attachments: list[MediaAttachmentInput] = []

    for index, download_url in enumerate(download_urls):
        preview_url = preview_urls[index] if index < len(preview_urls) else None
        attachments.append(
            MediaAttachmentInput(
                sort_index=index,
                media_type=_media_type_for_child(child, download_url),
                download_url=download_url,
                preview_url=preview_url,
                extension=_extension_from_url(download_url),
                download_strategy=_download_strategy_for_child(child),
            ),
        )

    community_name = normalize_reddit_community(child.data.subreddit)
    return SourceItem(
        source=SOURCE,
        source_item_id=child.data.id,
        title=child.data.title,
        author_name=child.data.author,
        author_label=f"u/{child.data.author}",
        community_name=community_name,
        community_label=reddit_community_label(community_name),
        item_kind=child.data.post_hint,
        source_url=_absolute_reddit_url(child.data.permalink),
        created_at=child.data.created_utc,
        raw_data=child.data.model_dump(mode="json", exclude_computed_fields=True),
        media=attachments,
    )


class RedditProvider:
    source = SOURCE

    def __init__(
        self,
        *,
        username: str,
        session_cookie: str,
        user_agent: str,
        page_size: int,
        page_limit: int,
    ) -> None:
        self.username = username
        self.session_cookie = session_cookie
        self.user_agent = user_agent
        self.page_size = page_size
        self.page_limit = page_limit

    def iter_liked_items(self) -> Iterable[SourceItem]:
        for child in upvoted_posts_generator(
            username=self.username,
            session_cookie=self.session_cookie,
            user_agent=self.user_agent,
            page_size=self.page_size,
            page_limit=self.page_limit,
        ):
            item = child_to_source_item(child)
            if item.media:
                yield item
