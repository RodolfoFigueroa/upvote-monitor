from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from upvote_monitor.db.models import (
    AppSettings,
    MediaAttachment,
    ReviewItem,
    SourceRule,
    SourceSettings,
)
from upvote_monitor.enums import (
    ApprovalMode,
    ApprovalStatus,
    DownloadStrategy,
    ListType,
    RuleTargetType,
)
from upvote_monitor.services.ingest import get_source_providers, ingest_items
from upvote_monitor.services.secrets import SecretStore
from upvote_monitor.services.source_settings import (
    REDDIT_SOURCE,
    X_SOURCE,
    encode_options,
)
from upvote_monitor.models.child import Children
from upvote_monitor.models.upvoted import UpvotedResponse
from upvote_monitor.sources.base import MediaAttachmentInput, SourceItem
from upvote_monitor.sources.reddit import child_to_source_item
from upvote_monitor.sources.x import LIKES_URL, XProvider, source_item_from_raw_tweet, validate_x_credentials
from upvote_monitor.upvoted import upvoted_posts_generator


@pytest.fixture
def engine() -> Iterator[Engine]:
    db_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(db_engine)
    yield db_engine
    db_engine.dispose()


def test_reddit_child_is_normalized_to_source_item() -> None:
    child = SimpleNamespace(
        data=SimpleNamespace(
            id="abc123",
            title="A good image",
            author="poster",
            subreddit="Python",
            post_hint="image",
            permalink="/r/Python/comments/abc123/a_good_image/",
            created_utc=datetime.now(timezone.utc),
            media_download_url=["https://i.redd.it/image.jpg"],
            media_preview_url=["https://preview.redd.it/image.jpg"],
            model_dump=lambda **_kwargs: {"id": "abc123"},
        )
    )

    item = child_to_source_item(cast(Children, child))

    assert item.source == "reddit"
    assert item.source_item_id == "abc123"
    assert item.community_name == "python"
    assert item.community_label == "r/python"
    assert (
        item.source_url == "https://reddit.com/r/Python/comments/abc123/a_good_image/"
    )
    assert item.media[0].download_strategy == DownloadStrategy.HTTP


def test_reddit_rich_video_uses_ytdlp_strategy() -> None:
    child = SimpleNamespace(
        data=SimpleNamespace(
            id="video123",
            title="A video",
            author="poster",
            subreddit="videos",
            post_hint="rich:video",
            permalink="/r/videos/comments/video123/a_video/",
            created_utc=datetime.now(timezone.utc),
            media_download_url=["https://example.com/watch?v=video123"],
            media_preview_url=["https://example.com/thumb.jpg"],
            model_dump=lambda **_kwargs: {"id": "video123"},
        )
    )

    item = child_to_source_item(cast(Children, child))

    assert item.media[0].media_type == "video"
    assert item.media[0].download_strategy == DownloadStrategy.YT_DLP


class FakeProvider:
    source = "fake"

    def iter_liked_items(self) -> Iterator[SourceItem]:
        yield SourceItem(
            source="fake",
            source_item_id="one",
            title="One",
            author_name="author",
            author_label="@author",
            community_name="community",
            community_label="Community",
            item_kind="image",
            source_url="https://example.com/one",
            created_at=datetime.now(timezone.utc),
            raw_data={"id": "one"},
            media=[
                MediaAttachmentInput(
                    sort_index=0,
                    media_type="image",
                    download_url="https://example.com/source.jpg",
                    preview_url="https://example.com/preview.jpg",
                    extension=".jpg",
                )
            ],
        )


def test_ingest_stores_generic_items_and_applies_rules(engine: Engine) -> None:
    with Session(engine) as session:
        session.add(
            AppSettings(
                id=1,
                approval_mode=ApprovalMode.MANUAL,
                refresh_cron="0 */6 * * *",
                refresh_enabled=True,
                download_base_dir="/download",
            )
        )
        session.add(
            SourceRule(
                source="fake",
                rule_type=ListType.WHITELIST,
                target_type=RuleTargetType.COMMUNITY,
                target_value="community",
                target_label="Community",
            )
        )
        session.commit()

        result = ingest_items(session, providers=[FakeProvider()])
        item = session.exec(select(ReviewItem)).one()
        attachment = session.exec(select(MediaAttachment)).one()
        item_id = item.id
        item_status = item.approval_status
        attachment_item_id = attachment.item_id
        attachment_download_url = attachment.download_url

    assert result.new_items == 1
    assert result.skipped == 0
    assert item_id == "fake_one"
    assert item_status == ApprovalStatus.APPROVED
    assert attachment_item_id == item_id
    assert attachment_download_url == "https://example.com/source.jpg"


class XFakeProvider:
    source = X_SOURCE

    def iter_liked_items(self) -> Iterator[SourceItem]:
        yield SourceItem(
            source=X_SOURCE,
            source_item_id="x-one",
            title="One",
            author_name="poster",
            author_label="@poster",
            community_name=None,
            community_label=None,
            item_kind="x_photo",
            source_url="https://x.com/poster/status/x-one",
            created_at=datetime.now(timezone.utc),
            raw_data={"id": "x-one"},
            media=[
                MediaAttachmentInput(
                    sort_index=0,
                    media_type="image",
                    download_url="https://pbs.twimg.com/media/source.jpg",
                    preview_url="https://pbs.twimg.com/media/source.jpg",
                    extension=".jpg",
                )
            ],
        )


def test_ingest_applies_x_author_rules(engine: Engine) -> None:
    with Session(engine) as session:
        session.add(
            AppSettings(
                id=1,
                approval_mode=ApprovalMode.MANUAL,
                refresh_cron="0 */6 * * *",
                refresh_enabled=True,
                download_base_dir="/download",
            )
        )
        session.add(
            SourceRule(
                source=X_SOURCE,
                rule_type=ListType.WHITELIST,
                target_type=RuleTargetType.AUTHOR,
                target_value="poster",
                target_label="@poster",
            )
        )
        session.commit()

        result = ingest_items(session, providers=[XFakeProvider()])
        item = session.exec(select(ReviewItem)).one()

    assert result.new_items == 1
    assert item.approval_status == ApprovalStatus.APPROVED


def test_ingest_applies_reddit_author_rules(engine: Engine) -> None:
    class FakeRedditProvider:
        source = REDDIT_SOURCE

        def iter_liked_items(self) -> Iterator[SourceItem]:
            yield SourceItem(
                source=REDDIT_SOURCE,
                source_item_id="reddit-one",
                title="One",
                author_name="author",
                author_label="u/author",
                community_name="python",
                community_label="r/python",
                item_kind="image",
                source_url="https://reddit.com/r/python/comments/reddit-one/item/",
                created_at=datetime.now(timezone.utc),
                raw_data={"id": "reddit-one"},
                media=[
                    MediaAttachmentInput(
                        sort_index=0,
                        media_type="image",
                        download_url="https://example.com/source.jpg",
                        preview_url="https://example.com/preview.jpg",
                        extension=".jpg",
                    )
                ],
            )

    with Session(engine) as session:
        session.add(
            AppSettings(
                id=1,
                approval_mode=ApprovalMode.MANUAL,
                refresh_cron="0 */6 * * *",
                refresh_enabled=True,
                download_base_dir="/download",
            )
        )
        session.add(
            SourceRule(
                source=REDDIT_SOURCE,
                rule_type=ListType.WHITELIST,
                target_type=RuleTargetType.AUTHOR,
                target_value="author",
                target_label="@author",
            )
        )
        session.commit()

        result = ingest_items(session, providers=[FakeRedditProvider()])
        item = session.exec(select(ReviewItem)).one()

    assert result.new_items == 1
    assert item.approval_status == ApprovalStatus.APPROVED


def test_x_tweet_is_normalized_to_source_item() -> None:
    item = source_item_from_raw_tweet(
        {
            "rest_id": "123",
            "core": {
                "user_results": {
                    "result": {
                        "legacy": {
                            "screen_name": "Poster",
                            "name": "Poster Name",
                        }
                    }
                }
            },
            "legacy": {
                "id_str": "123",
                "full_text": "A good X post",
                "created_at": "Mon Sep 24 03:35:21 +0000 2012",
                "extended_entities": {
                    "media": [
                        {
                            "type": "photo",
                            "media_url_https": "https://pbs.twimg.com/media/photo.jpg",
                            "original_info": {"width": 1024, "height": 768},
                        },
                        {
                            "type": "video",
                            "media_url_https": "https://pbs.twimg.com/media/video.jpg",
                            "original_info": {"width": 1280, "height": 720},
                            "video_info": {
                                "duration_millis": 1200,
                                "variants": [
                                    {
                                        "content_type": "application/x-mpegURL",
                                        "url": "https://video.twimg.com/playlist.m3u8",
                                    },
                                    {
                                        "content_type": "video/mp4",
                                        "bitrate": 832000,
                                        "url": "https://video.twimg.com/low.mp4",
                                    },
                                    {
                                        "content_type": "video/mp4",
                                        "bitrate": 2176000,
                                        "url": "https://video.twimg.com/high.mp4",
                                    },
                                ],
                            },
                        },
                    ]
                },
            },
        }
    )

    assert item is not None
    assert item.source == X_SOURCE
    assert item.source_item_id == "123"
    assert item.author_name == "poster"
    assert item.author_label == "@Poster"
    assert item.item_kind == "x_mixed"
    assert item.source_url == "https://x.com/Poster/status/123"
    assert len(item.media) == 2
    assert item.media[0].download_url == (
        "https://pbs.twimg.com/media/photo.jpg?format=jpg&name=orig"
    )
    assert item.media[0].media_type == "image"
    assert item.media[1].download_url == "https://video.twimg.com/high.mp4"
    assert item.media[1].media_type == "video"
    assert item.media[1].duration_ms == 1200


def test_x_retweet_media_is_normalized_to_source_item() -> None:
    item = source_item_from_raw_tweet(
        {
            "rest_id": "123",
            "core": {
                "user_results": {
                    "result": {
                        "legacy": {
                            "screen_name": "Reposter",
                            "name": "Reposter Name",
                        }
                    }
                }
            },
            "legacy": {
                "id_str": "123",
                "full_text": "RT @Artist: A good X post",
                "created_at": "Mon Sep 24 03:35:21 +0000 2012",
                "retweeted_status_result": {
                    "result": {
                        "rest_id": "456",
                        "core": {
                            "user_results": {
                                "result": {
                                    "legacy": {
                                        "screen_name": "Artist",
                                        "name": "Artist Name",
                                    }
                                }
                            }
                        },
                        "legacy": {
                            "id_str": "456",
                            "full_text": "A good X post",
                            "created_at": "Mon Sep 24 03:33:21 +0000 2012",
                            "extended_entities": {
                                "media": [
                                    {
                                        "type": "photo",
                                        "media_url_https": (
                                            "https://pbs.twimg.com/media/retweet.jpg"
                                        ),
                                        "original_info": {
                                            "width": 1024,
                                            "height": 768,
                                        },
                                    }
                                ]
                            },
                        },
                    }
                },
            },
        }
    )

    assert item is not None
    assert item.source == X_SOURCE
    assert item.source_item_id == "123"
    assert item.author_name == "reposter"
    assert item.item_kind == "x_photo"
    assert len(item.media) == 1
    assert item.media[0].download_url == (
        "https://pbs.twimg.com/media/retweet.jpg?format=jpg&name=orig"
    )


def test_x_quote_media_is_normalized_to_source_item() -> None:
    item = source_item_from_raw_tweet(
        {
            "rest_id": "123",
            "core": {
                "user_results": {
                    "result": {
                        "legacy": {
                            "screen_name": "Poster",
                            "name": "Poster Name",
                        }
                    }
                }
            },
            "quoted_status_result": {
                "result": {
                    "tweet": {
                        "rest_id": "456",
                        "core": {
                            "user_results": {
                                "result": {
                                    "legacy": {
                                        "screen_name": "Artist",
                                        "name": "Artist Name",
                                    }
                                }
                            }
                        },
                        "legacy": {
                            "id_str": "456",
                            "full_text": "A quoted X post",
                            "created_at": "Mon Sep 24 03:33:21 +0000 2012",
                            "extended_entities": {
                                "media": [
                                    {
                                        "type": "photo",
                                        "media_url_https": (
                                            "https://pbs.twimg.com/media/quote.jpg"
                                        ),
                                        "original_info": {
                                            "width": 1024,
                                            "height": 768,
                                        },
                                    }
                                ]
                            },
                        },
                    }
                }
            },
            "legacy": {
                "id_str": "123",
                "full_text": "Look at this",
                "created_at": "Mon Sep 24 03:35:21 +0000 2012",
            },
        }
    )

    assert item is not None
    assert item.source_item_id == "123"
    assert item.item_kind == "x_photo"
    assert len(item.media) == 1
    assert item.media[0].download_url == (
        "https://pbs.twimg.com/media/quote.jpg?format=jpg&name=orig"
    )


def test_source_providers_use_reddit_source_settings(
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_path = tmp_path / "secrets.enc"
    SecretStore(secret_key="provider-key", path=secret_path).update_source_secrets(
        REDDIT_SOURCE,
        {"username": "myusername", "session_cookie": "cookie"},
    )

    def store_factory() -> SecretStore:
        return SecretStore(secret_key="provider-key", path=secret_path)

    monkeypatch.setattr("upvote_monitor.services.ingest.SecretStore", store_factory)

    with Session(engine) as session:
        session.add(
            SourceSettings(
                source=REDDIT_SOURCE,
                enabled=True,
                options_json=encode_options(
                    {
                        "username": "ignored-option",
                        "page_limit": 4,
                        "page_size": 100,
                        "user_agent": "agent/1.0",
                    }
                ),
            )
        )
        session.commit()

        providers = get_source_providers(session)

    assert len(providers) == 1
    provider = providers[0]
    assert provider.source == REDDIT_SOURCE
    assert getattr(provider, "username") == "myusername"
    assert getattr(provider, "session_cookie") == "cookie"
    assert getattr(provider, "user_agent") == "agent/1.0"
    assert getattr(provider, "page_size") == 100
    assert getattr(provider, "page_limit") == 4


def test_source_providers_use_x_source_settings(
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_path = tmp_path / "secrets.enc"
    SecretStore(secret_key="provider-key", path=secret_path).update_source_secrets(
        X_SOURCE,
        {"auth_token": "auth", "ct0": "csrf", "twid": "u%3D123"},
    )

    def store_factory() -> SecretStore:
        return SecretStore(secret_key="provider-key", path=secret_path)

    monkeypatch.setattr("upvote_monitor.services.ingest.SecretStore", store_factory)

    with Session(engine) as session:
        session.add(
            SourceSettings(
                source=X_SOURCE,
                enabled=True,
                options_json=encode_options(
                    {
                        "page_limit": 5,
                        "page_size": 20,
                        "user_agent": "agent/1.0",
                    }
                ),
            )
        )
        session.commit()

        providers = get_source_providers(session)

    assert len(providers) == 1
    provider = providers[0]
    assert isinstance(provider, XProvider)
    assert provider.source == X_SOURCE
    assert provider.auth_token == "auth"
    assert provider.ct0 == "csrf"
    assert provider.twid == "u%3D123"
    assert provider.user_agent == "agent/1.0"
    assert provider.page_limit == 5
    assert provider.page_size == 20


def test_x_provider_resolves_authenticated_user_from_twid() -> None:
    provider = XProvider(
        auth_token="auth",
        ct0="csrf",
        twid="u%3D123",
        bearer_token=None,
        user_agent="agent/1.0",
        page_size=20,
        page_limit=5,
    )

    assert provider._authenticated_user_id(cast(Any, object())) == "123"


def test_x_credential_validation_uses_likes_endpoint_from_twid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, str] | None]] = []

    def fake_request_json(
        _session: object,
        url: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        calls.append((url, params))
        return {"data": {"user": {"result": {"timeline": {"instructions": []}}}}}

    monkeypatch.setattr("upvote_monitor.sources.x._request_json", fake_request_json)

    validate_x_credentials(
        auth_token="auth",
        ct0="csrf",
        twid="u%3D123",
        bearer_token=None,
        user_agent="agent/1.0",
    )

    assert [url for url, _params in calls] == [LIKES_URL]
    assert calls[0][1] is not None
    assert '"userId":"123"' in calls[0][1]["variables"]
    assert '"count":1' in calls[0][1]["variables"]


def test_source_providers_skip_unconfigured_reddit(engine: Engine) -> None:
    with Session(engine) as session:
        session.add(
            SourceSettings(
                source=REDDIT_SOURCE,
                enabled=True,
                options_json=encode_options({"page_limit": 10}),
            )
        )
        session.commit()

        providers = get_source_providers(session)

    assert providers == []


def _reddit_no_media_child_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "all_awardings": [],
        "allow_live_comments": False,
        "approved_at_utc": None,
        "approved_by": None,
        "archived": False,
        "author": "poster",
        "author_flair_background_color": None,
        "author_flair_css_class": None,
        "author_flair_template_id": None,
        "author_flair_text": None,
        "author_flair_text_color": None,
        "author_is_blocked": False,
        "awarders": [],
        "banned_at_utc": None,
        "banned_by": None,
        "category": None,
        "can_gild": False,
        "can_mod_post": False,
        "clicked": False,
        "content_categories": None,
        "contest_mode": False,
        "created": 1_700_000_000,
        "created_utc": 1_700_000_000,
        "discussion_type": None,
        "distinguished": None,
        "domain": "self.test",
        "downs": 0,
        "edited": False,
        "gilded": 0,
        "gildings": {},
        "hidden": False,
        "hide_score": False,
        "id": "poll123",
        "is_created_from_ads_ui": False,
        "is_crosspostable": False,
        "is_meta": False,
        "is_original_content": False,
        "is_reddit_media_domain": False,
        "is_robot_indexable": True,
        "is_self": True,
        "is_video": False,
        "likes": True,
        "link_flair_background_color": None,
        "link_flair_css_class": None,
        "link_flair_richtext": [],
        "link_flair_text": None,
        "link_flair_type": "text",
        "locked": False,
        "media": None,
        "media_embed": {},
        "media_only": False,
        "mod_note": None,
        "mod_reason_by": None,
        "mod_reason_title": None,
        "mod_reports": [],
        "name": "t3_poll123",
        "no_follow": False,
        "num_comments": 0,
        "num_crossposts": 0,
        "num_reports": None,
        "over_18": False,
        "permalink": "/r/test/comments/poll123/title/",
        "pinned": False,
        "poll_data": None,
        "pwls": 6,
        "quarantine": False,
        "removal_reason": None,
        "removed_by": None,
        "removed_by_category": None,
        "report_reasons": None,
        "saved": False,
        "score": 1,
        "secure_media": None,
        "secure_media_embed": {},
        "selftext": "body",
        "selftext_html": None,
        "spoiler": False,
        "stickied": False,
        "subreddit": "test",
        "subreddit_id": "t5_test",
        "subreddit_name_prefixed": "r/test",
        "subreddit_subscribers": 1,
        "suggested_sort": None,
        "title": "A poll",
        "top_awarded_type": None,
        "total_awards_received": 0,
        "treatment_tags": [],
        "send_replies": True,
        "subreddit_type": "public",
        "ups": 1,
        "upvote_ratio": 1.0,
        "url": "https://www.reddit.com/r/test/comments/poll123/title/",
        "user_reports": [],
        "view_count": None,
        "visited": False,
        "wls": 6,
    }
    data.update(overrides)
    return data


def test_reddit_upvoted_response_accepts_poll_data_object() -> None:
    poll_data = {
        "prediction_status": None,
        "resolved_option_id": None,
        "total_stake_amount": None,
        "user_selection": None,
        "user_won_amount": None,
        "voting_end_timestamp": 1_700_000_000_000,
        "options": [
            {
                "id": "1",
                "text": "Yes",
                "vote_count": 10,
            }
        ],
        "tournament_id": None,
    }

    response = UpvotedResponse.model_validate(
        {
            "kind": "Listing",
            "data": {
                "after": None,
                "before": None,
                "children": [
                    {
                        "kind": "t3",
                        "data": _reddit_no_media_child_data(poll_data=poll_data),
                    }
                ],
                "dist": 1,
                "geo_filter": "",
                "modhash": "",
            },
        }
    )

    child = response.data.children[0]
    assert child.data.post_hint == "no_media"
    assert child.data.poll_data == poll_data


def test_reddit_upvoted_generator_stops_at_page_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "kind": "Listing",
                "data": {
                    "after": "next-page",
                    "dist": 0,
                    "modhash": "",
                    "geo_filter": "",
                    "children": [],
                    "before": None,
                },
            }

    class FakeSession:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}
            self.calls = 0

        def mount(self, _prefix: str, _adapter: object) -> None:
            pass

        def get(
            self,
            _url: str,
            *,
            params: dict[str, object],
            timeout: int,
        ) -> FakeResponse:
            assert params["limit"] == 100
            assert timeout == 60
            self.calls += 1
            return FakeResponse()

    fake_session = FakeSession()
    monkeypatch.setattr(
        "upvote_monitor.upvoted.requests.Session",
        lambda: fake_session,
    )

    list(
        upvoted_posts_generator(
            username="myusername",
            session_cookie="cookie",
            user_agent="agent/1.0",
            page_size=100,
            page_limit=3,
        )
    )

    assert fake_session.calls == 3
