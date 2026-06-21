from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from fastapi import BackgroundTasks
from PIL import Image
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from upvote_monitor.api.items import analyze_item_endpoint
from upvote_monitor.db.models import (
    AnalysisProfile,
    AppSettings,
    DEFAULT_ANALYSIS_PROFILE_ID,
    MediaAnalysis,
    MediaAttachment,
    ReviewItem,
)
from upvote_monitor.enums import (
    AnalysisStatus,
    ApprovalMode,
    ApprovalStatus,
    DownloadStatus,
)
from upvote_monitor.schemas.items import ItemDetail
from upvote_monitor.services.ingest import IngestResult
from upvote_monitor.services.download import DownloadBatchResult
from upvote_monitor.services.refresh import create_refresh_run, execute_refresh_run
from upvote_monitor.services.tagging.analysis import (
    TaggerUnavailableError,
    analyze_item,
    process_pending_analysis,
)
from upvote_monitor.services.tagging.profiles import (
    BUILT_IN_ANALYSIS_PROFILES,
    SCORING_VERSION,
    ensure_default_analysis_profiles,
)
import upvote_monitor.services.tagging.pixai_tagger as pixai_tagger_module
from upvote_monitor.services.tagging.pixai_tagger import (
    PIXAI_TAGGER_V0_9_ONNX_REPO_ID,
    PixAITagger,
    _scores_to_probabilities,
)
from upvote_monitor.services.tagging.scoring import score_illustration
from upvote_monitor.services.tagging.wd_tagger import (
    WD_COMPATIBLE_MODEL_REPOS,
    WD_EVA02_LARGE_V3_REPO_ID,
    WD_SWINV2_V3_REPO_ID,
    WD_VIT_LARGE_V3_REPO_ID,
    WDTaggerResult,
    get_wd_tagger,
)

TEST_PROFILE_ID = "fake-wd-default"


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


class FakeTagger:
    model_name = "fake/wd"
    model_version = "test"

    def __init__(self, result: WDTaggerResult | None = None) -> None:
        self.result = result or WDTaggerResult(
            ratings={"safe": 0.96},
            general_tags={
                "manga": 0.94,
                "lineart": 0.88,
                "1girl": 0.92,
                "solo": 0.86,
            },
            character_tags={"hatsune_miku": 0.91},
        )
        self.paths: list[Path] = []

    def tag_image(self, path: Path) -> WDTaggerResult:
        self.paths.append(path)
        return self.result


def make_item(
    item_id: str,
    *,
    approval_status: ApprovalStatus = ApprovalStatus.UNDER_REVIEW,
) -> ReviewItem:
    return ReviewItem(
        id=item_id,
        source="reddit",
        source_item_id=item_id,
        title=f"Item {item_id}",
        author_name="author",
        author_label="u/author",
        community_name="art",
        community_label="r/art",
        item_kind="image",
        source_url=f"https://reddit.com/r/art/comments/{item_id}/item/",
        created_at=datetime.now(timezone.utc),
        approval_status=approval_status,
        download_status=DownloadStatus.PENDING,
        raw_data_json="{}",
        media_count=1,
    )


def make_attachment(
    item_id: str,
    *,
    preview_url: str = "https://example.com/preview.jpg",
) -> MediaAttachment:
    return MediaAttachment(
        item_id=item_id,
        sort_index=0,
        media_type="image",
        download_url="https://example.com/source.jpg",
        preview_url=preview_url,
        extension=".jpg",
    )


def add_settings(
    session: Session,
    *,
    tagger_enabled: bool = True,
    auto_approve_enabled: bool = True,
    threshold: float = 0.9,
    general_storage_threshold: float = 0.01,
    character_storage_threshold: float = 0.01,
    general_display_threshold: float = 0.15,
    character_display_threshold: float = 0.35,
    app_general_display_threshold: float = 0.15,
    app_character_display_threshold: float = 0.35,
    profile_id: str = TEST_PROFILE_ID,
) -> None:
    session.add(
        AnalysisProfile(
            id=profile_id,
            name="Fake WD",
            model_name=FakeTagger.model_name,
            model_version=FakeTagger.model_version,
            scoring_version=SCORING_VERSION,
            general_tag_storage_threshold=general_storage_threshold,
            character_tag_storage_threshold=character_storage_threshold,
            general_tag_display_threshold=general_display_threshold,
            character_tag_display_threshold=character_display_threshold,
            auto_approve_threshold=threshold,
        )
    )
    session.add(
        AppSettings(
            id=1,
            approval_mode=ApprovalMode.MANUAL,
            refresh_cron="0 */6 * * *",
            refresh_enabled=True,
            download_base_dir="/download",
            illustration_tagger_enabled=tagger_enabled,
            illustration_auto_approve_enabled=auto_approve_enabled,
            active_analysis_profile_id=profile_id,
            general_tag_display_threshold=app_general_display_threshold,
            character_tag_display_threshold=app_character_display_threshold,
        )
    )


def test_scoring_prefers_danbooru_like_illustration_tags() -> None:
    illustration = score_illustration(
        {
            "manga": 0.95,
            "lineart": 0.90,
            "1girl": 0.93,
            "solo": 0.87,
        },
        {},
        {"safe": 0.97},
    )
    photo = score_illustration(
        {
            "realistic": 0.91,
            "photo_background": 0.82,
            "food": 0.74,
        },
        {},
        {"general": 0.60},
    )

    assert illustration >= 0.9
    assert photo < 0.5


def test_default_settings_use_swinv2_profile() -> None:
    settings = AppSettings()

    assert settings.active_analysis_profile_id == DEFAULT_ANALYSIS_PROFILE_ID


def test_default_analysis_profiles_include_best_smilingwolf_v3_models(
    engine: Engine,
) -> None:
    with Session(engine) as session:
        ensure_default_analysis_profiles(session)

        profiles = {
            profile.id: profile
            for profile in session.exec(select(AnalysisProfile)).all()
        }
        assert {profile.id for profile in BUILT_IN_ANALYSIS_PROFILES} <= set(profiles)
        assert len(BUILT_IN_ANALYSIS_PROFILES) == 4
        assert profiles[DEFAULT_ANALYSIS_PROFILE_ID].model_name == WD_SWINV2_V3_REPO_ID
        assert profiles["wd-eva02-large-v3"].model_name == WD_EVA02_LARGE_V3_REPO_ID
        assert profiles["wd-eva02-large-v3"].auto_approve_threshold == 0.92
        assert profiles["wd-vit-large-v3"].model_name == WD_VIT_LARGE_V3_REPO_ID
        assert profiles["wd-vit-large-v3"].auto_approve_threshold == 0.92
        assert profiles["pixai-v0-9-onnx"].model_name == (
            PIXAI_TAGGER_V0_9_ONNX_REPO_ID
        )
        assert profiles["pixai-v0-9-onnx"].general_tag_storage_threshold == 0.30
        assert profiles["pixai-v0-9-onnx"].character_tag_storage_threshold == 0.85
        assert profiles["pixai-v0-9-onnx"].auto_approve_threshold == 0.97
        assert profiles["pixai-v0-9-onnx"].enabled is True
        assert "wd-v1-4-vit-v2" not in profiles
        assert WD_COMPATIBLE_MODEL_REPOS == (
            WD_SWINV2_V3_REPO_ID,
            WD_EVA02_LARGE_V3_REPO_ID,
            WD_VIT_LARGE_V3_REPO_ID,
        )


def test_default_analysis_profiles_disable_deprecated_v2_profile(
    engine: Engine,
) -> None:
    with Session(engine) as session:
        session.add(
            AnalysisProfile(
                id="wd-v1-4-vit-v2",
                name="WD v1.4 ViT v2",
                model_name="SmilingWolf/wd-v1-4-vit-tagger-v2",
                model_version="main",
                scoring_version=SCORING_VERSION,
                general_tag_storage_threshold=0.01,
                character_tag_storage_threshold=0.01,
                general_tag_display_threshold=0.15,
                character_tag_display_threshold=0.35,
                auto_approve_threshold=0.90,
                enabled=True,
            )
        )
        session.add(
            AppSettings(
                id=1,
                approval_mode=ApprovalMode.MANUAL,
                refresh_cron="0 */6 * * *",
                refresh_enabled=True,
                download_base_dir="/download",
                active_analysis_profile_id="wd-v1-4-vit-v2",
            )
        )
        session.commit()

        ensure_default_analysis_profiles(session)

        deprecated_profile = session.get(AnalysisProfile, "wd-v1-4-vit-v2")
        settings = session.get(AppSettings, 1)
        assert deprecated_profile is not None
        assert deprecated_profile.enabled is False
        assert settings is not None
        assert settings.active_analysis_profile_id == DEFAULT_ANALYSIS_PROFILE_ID


def test_wd_tagger_rejects_incompatible_model_repo() -> None:
    with pytest.raises(ValueError, match="not supported by the WD tagger"):
        get_wd_tagger("unsupported/model")


def test_pixai_tagger_rejects_incompatible_model_repo() -> None:
    with pytest.raises(ValueError, match="not supported by the PixAI tagger"):
        PixAITagger(repo_id="unsupported/model")


def test_pixai_tagger_maps_onnx_scores_to_general_and_character_tags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_path = tmp_path / "model.onnx"
    tags_path = tmp_path / "selected_tags.csv"
    preprocess_path = tmp_path / "preprocess.json"
    image_path = tmp_path / "image.png"

    model_path.write_bytes(b"onnx")
    tags_path.write_text(
        "\n".join(
            [
                "name,category",
                "manga,0",
                "hatsune_miku,4",
                "ignored_copyright,3",
            ]
        ),
        encoding="utf-8",
    )
    preprocess_path.write_text(
        (
            '{"stages": ['
            '{"type": "resize", "size": [2, 2]}, '
            '{"type": "to_tensor"}, '
            '{"type": "normalize", "mean": [0.5, 0.5, 0.5], '
            '"std": [0.5, 0.5, 0.5]}'
            "]}"
        ),
        encoding="utf-8",
    )
    Image.new("RGBA", (1, 1), (255, 0, 0, 255)).save(image_path)

    paths = {
        "model.onnx": model_path,
        "selected_tags.csv": tags_path,
        "preprocess.json": preprocess_path,
    }

    def fake_download(
        repo_id: str,
        filename: str,
        *,
        revision: str,
        cache_dir: str,
    ) -> str:
        assert repo_id == PIXAI_TAGGER_V0_9_ONNX_REPO_ID
        assert revision == "main"
        assert cache_dir
        return str(paths[filename])

    class FakeInput:
        name = "pixel_values"
        shape = [1, 3, 2, 2]

    class FakeSession:
        instances: list["FakeSession"] = []

        def __init__(self, model: str, *, providers: list[str]) -> None:
            assert model == str(model_path)
            assert providers == ["CPUExecutionProvider"]
            self.input_array: np.ndarray | None = None
            FakeSession.instances.append(self)

        def get_inputs(self) -> list[FakeInput]:
            return [FakeInput()]

        def run(
            self,
            _output_names: object,
            inputs: dict[str, np.ndarray],
        ) -> list[np.ndarray]:
            self.input_array = inputs["pixel_values"]
            return [
                np.asarray([[42.0, 43.0]], dtype=np.float32),
                np.asarray([[2.0, -2.0, 0.25]], dtype=np.float32),
            ]

    monkeypatch.setattr(pixai_tagger_module, "hf_hub_download", fake_download)
    monkeypatch.setattr(pixai_tagger_module.ort, "InferenceSession", FakeSession)

    result = PixAITagger(cache_dir=tmp_path / "cache").tag_image(image_path)

    assert result.ratings == {}
    assert result.general_tags == {"manga": pytest.approx(0.880797)}
    assert result.character_tags == {"hatsune_miku": pytest.approx(0.119203)}
    session = FakeSession.instances[0]
    assert session.input_array is not None
    assert session.input_array.shape == (1, 3, 2, 2)
    assert session.input_array[0, :, 0, 0].tolist() == pytest.approx(
        [1.0, -1.0, -1.0]
    )


def test_pixai_scores_only_apply_sigmoid_to_logits() -> None:
    probabilities = _scores_to_probabilities(
        np.asarray([0.20, 0.70], dtype=np.float32)
    )
    logits = _scores_to_probabilities(np.asarray([-2.0, 2.0], dtype=np.float32))

    assert probabilities.tolist() == pytest.approx([0.20, 0.70])
    assert logits.tolist() == pytest.approx([0.119203, 0.880797])


def test_pending_analysis_persists_tags_and_auto_approves(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    preview_path = tmp_path / "preview.jpg"
    preview_path.write_bytes(b"image")
    monkeypatch.setattr(
        "upvote_monitor.services.tagging.analysis.get_or_fetch_cached_preview",
        lambda *_args, **_kwargs: preview_path,
    )

    with Session(engine) as session:
        add_settings(session)
        item = make_item("auto-illustration")
        session.add(item)
        session.add(make_attachment(item.id))
        session.commit()

        result = process_pending_analysis(session, FakeTagger())

        item = session.get(ReviewItem, "auto-illustration")
        analyses = session.exec(select(MediaAnalysis)).all()
        assert result.analyzed == 1
        assert result.approved == 1
        assert item is not None
        assert item.approval_status == ApprovalStatus.APPROVED
        assert len(analyses) == 1
        assert analyses[0].status == AnalysisStatus.COMPLETED
        assert analyses[0].illustration_score is not None
        assert "manga" in analyses[0].general_tags_json
        assert "hatsune_miku" in analyses[0].character_tags_json

        detail = ItemDetail.from_db(item, session)
        assert detail.illustration_score == analyses[0].illustration_score
        assert detail.media[0].analysis is not None
        assert detail.media[0].analysis.general_tags["manga"] == 0.94
        assert detail.media[0].analysis.character_tags["hatsune_miku"] == 0.91


def test_pending_analysis_uses_selected_eva02_profile(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    preview_path = tmp_path / "preview.jpg"
    preview_path.write_bytes(b"image")
    monkeypatch.setattr(
        "upvote_monitor.services.tagging.analysis.get_or_fetch_cached_preview",
        lambda *_args, **_kwargs: preview_path,
    )

    with Session(engine) as session:
        ensure_default_analysis_profiles(session)
        session.add(
            AppSettings(
                id=1,
                approval_mode=ApprovalMode.MANUAL,
                refresh_cron="0 */6 * * *",
                refresh_enabled=True,
                download_base_dir="/download",
                illustration_tagger_enabled=True,
                illustration_auto_approve_enabled=False,
                active_analysis_profile_id="wd-eva02-large-v3",
            )
        )
        item = make_item("eva-profile")
        session.add(item)
        session.add(make_attachment(item.id))
        session.commit()

        result = process_pending_analysis(session, FakeTagger())

        analysis = session.exec(select(MediaAnalysis)).one()
        assert result.analyzed == 1
        assert analysis.analysis_profile_id == "wd-eva02-large-v3"
        assert analysis.model_name == WD_EVA02_LARGE_V3_REPO_ID
        assert analysis.scoring_version == SCORING_VERSION


def test_pending_analysis_uses_selected_pixai_profile(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    preview_path = tmp_path / "preview.jpg"
    preview_path.write_bytes(b"image")
    monkeypatch.setattr(
        "upvote_monitor.services.tagging.analysis.get_or_fetch_cached_preview",
        lambda *_args, **_kwargs: preview_path,
    )
    calls: list[tuple[str, str]] = []

    def fake_get_pixai_tagger(repo_id: str, revision: str) -> FakeTagger:
        calls.append((repo_id, revision))
        return FakeTagger()

    monkeypatch.setattr(
        "upvote_monitor.services.tagging.analysis.get_pixai_tagger",
        fake_get_pixai_tagger,
    )

    with Session(engine) as session:
        ensure_default_analysis_profiles(session)
        session.add(
            AppSettings(
                id=1,
                approval_mode=ApprovalMode.MANUAL,
                refresh_cron="0 */6 * * *",
                refresh_enabled=True,
                download_base_dir="/download",
                illustration_tagger_enabled=True,
                illustration_auto_approve_enabled=False,
                active_analysis_profile_id="pixai-v0-9-onnx",
            )
        )
        item = make_item("pixai-profile")
        session.add(item)
        session.add(make_attachment(item.id))
        session.commit()

        result = process_pending_analysis(session)

        analysis = session.exec(select(MediaAnalysis)).one()
        assert result.analyzed == 1
        assert calls == [(PIXAI_TAGGER_V0_9_ONNX_REPO_ID, "main")]
        assert analysis.analysis_profile_id == "pixai-v0-9-onnx"
        assert analysis.model_name == PIXAI_TAGGER_V0_9_ONNX_REPO_ID
        assert analysis.scoring_version == SCORING_VERSION


def test_pending_analysis_stores_near_raw_tags_but_filters_api_display(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    preview_path = tmp_path / "preview.jpg"
    preview_path.write_bytes(b"image")
    monkeypatch.setattr(
        "upvote_monitor.services.tagging.analysis.get_or_fetch_cached_preview",
        lambda *_args, **_kwargs: preview_path,
    )

    with Session(engine) as session:
        add_settings(
            session,
            auto_approve_enabled=False,
            general_storage_threshold=0.01,
            character_storage_threshold=0.01,
            general_display_threshold=0.0,
            character_display_threshold=0.0,
            app_general_display_threshold=0.9,
            app_character_display_threshold=0.5,
        )
        item = make_item("tag-threshold")
        session.add(item)
        session.add(make_attachment(item.id))
        session.commit()

        process_pending_analysis(
            session,
            FakeTagger(
                WDTaggerResult(
                    ratings={"safe": 0.96},
                    general_tags={
                        "manga": 0.94,
                        "solo": 0.86,
                        "mid_general": 0.6,
                        "low_general": 0.1,
                    },
                    character_tags={
                        "hatsune_miku": 0.91,
                        "mid_character": 0.6,
                        "low_character": 0.2,
                    },
                )
            ),
        )

        analysis = session.exec(select(MediaAnalysis)).one()
        detail = ItemDetail.from_db(item, session)
        assert detail.media[0].analysis is not None
        assert "low_general" in analysis.general_tags_json
        assert "low_character" in analysis.character_tags_json
        assert detail.media[0].analysis.general_tags == {"manga": 0.94}
        assert detail.media[0].analysis.character_tags == {
            "hatsune_miku": 0.91,
            "mid_character": 0.6,
        }
        assert detail.media[0].analysis.stored_general_tag_count == 4
        assert detail.media[0].analysis.stored_character_tag_count == 3


def test_item_detail_uses_active_profile_and_preserves_other_analyses(
    engine: Engine,
) -> None:
    with Session(engine) as session:
        add_settings(session, auto_approve_enabled=False)
        item = make_item("multi-profile")
        attachment = make_attachment(item.id)
        session.add(item)
        session.add(attachment)
        session.commit()
        session.refresh(attachment)

        other_profile_id = "other-profile"
        session.add(
            AnalysisProfile(
                id=other_profile_id,
                name="Other Tagger",
                model_name="other/model",
                model_version="main",
                scoring_version="illustration-v2",
                general_tag_storage_threshold=0.01,
                character_tag_storage_threshold=0.01,
                general_tag_display_threshold=0.2,
                character_tag_display_threshold=0.35,
                auto_approve_threshold=0.8,
            )
        )
        assert attachment.id is not None
        session.add(
            MediaAnalysis(
                attachment_id=attachment.id,
                analysis_profile_id=TEST_PROFILE_ID,
                model_name=FakeTagger.model_name,
                model_version=FakeTagger.model_version,
                scoring_version=SCORING_VERSION,
                status=AnalysisStatus.COMPLETED,
                illustration_score=0.91,
                general_tags_json='{"manga": 0.91}',
                character_tags_json='{"hatsune_miku": 0.92}',
                ratings_json="{}",
            )
        )
        session.add(
            MediaAnalysis(
                attachment_id=attachment.id,
                analysis_profile_id=other_profile_id,
                model_name="other/model",
                model_version="main",
                scoring_version="illustration-v2",
                status=AnalysisStatus.COMPLETED,
                illustration_score=0.22,
                general_tags_json='{"realistic": 0.8}',
                character_tags_json="{}",
                ratings_json="{}",
            )
        )
        session.commit()

        detail = ItemDetail.from_db(item, session)
        assert detail.illustration_score == 0.91
        assert detail.media[0].analysis is not None
        assert detail.media[0].analysis.analysis_profile_id == TEST_PROFILE_ID
        assert len(detail.media[0].analyses) == 2

        settings = session.get(AppSettings, 1)
        assert settings is not None
        settings.active_analysis_profile_id = other_profile_id
        session.add(settings)
        session.commit()

        next_detail = ItemDetail.from_db(item, session)
        assert next_detail.illustration_score == 0.22
        assert next_detail.media[0].analysis is not None
        assert next_detail.media[0].analysis.analysis_profile_id == other_profile_id


def test_pending_analysis_skips_non_cacheable_preview(engine: Engine) -> None:
    with Session(engine) as session:
        add_settings(session)
        item = make_item("video-preview")
        session.add(item)
        session.add(
            make_attachment(item.id, preview_url="https://example.com/clip.mp4")
        )
        session.commit()

        result = process_pending_analysis(session, FakeTagger())

        analyses = session.exec(select(MediaAnalysis)).all()
        assert result.skipped == 1
        assert analyses[0].status == AnalysisStatus.SKIPPED
        stored_item = session.get(ReviewItem, item.id)
        assert stored_item is not None
        assert stored_item.approval_status == ApprovalStatus.UNDER_REVIEW


def test_manual_analyze_endpoint_force_retags_without_auto_approval(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    preview_path = tmp_path / "preview.jpg"
    preview_path.write_bytes(b"image")
    monkeypatch.setattr(
        "upvote_monitor.services.tagging.analysis.get_or_fetch_cached_preview",
        lambda *_args, **_kwargs: preview_path,
    )

    first_tagger = FakeTagger(
        WDTaggerResult(
            ratings={"safe": 0.7},
            general_tags={"realistic": 0.9, "photo_background": 0.8},
            character_tags={"real_person": 0.9},
        )
    )
    second_tagger = FakeTagger()
    taggers = [first_tagger, second_tagger]
    monkeypatch.setattr(
        "upvote_monitor.services.tagging.analysis.get_wd_tagger",
        lambda *_args, **_kwargs: taggers.pop(0),
    )

    with Session(engine) as session:
        add_settings(session, tagger_enabled=False, auto_approve_enabled=False)
        item = make_item("manual-tag")
        session.add(item)
        session.add(make_attachment(item.id))
        session.commit()

        first_detail = analyze_item_endpoint("manual-tag", BackgroundTasks(), session)
        second_detail = analyze_item_endpoint("manual-tag", BackgroundTasks(), session)

        analyses = session.exec(select(MediaAnalysis)).all()
        item = session.get(ReviewItem, "manual-tag")
        assert item is not None
        assert item.approval_status == ApprovalStatus.UNDER_REVIEW
        assert len(analyses) == 1
        assert first_detail.media[0].analysis is not None
        assert first_detail.media[0].analysis.general_tags["realistic"] == 0.9
        assert first_detail.media[0].analysis.character_tags["real_person"] == 0.9
        assert second_detail.media[0].analysis is not None
        assert second_detail.media[0].analysis.general_tags["manga"] == 0.94
        assert second_detail.media[0].analysis.character_tags["hatsune_miku"] == 0.91
        assert "realistic" not in second_detail.media[0].analysis.general_tags


def test_manual_analysis_rejects_unsupported_active_profile(engine: Engine) -> None:
    with Session(engine) as session:
        profile_id = "unsupported-profile"
        session.add(
            AnalysisProfile(
                id=profile_id,
                name="Unsupported",
                model_name="unsupported/model",
                model_version="main",
                scoring_version=SCORING_VERSION,
                general_tag_storage_threshold=0.01,
                character_tag_storage_threshold=0.01,
                general_tag_display_threshold=0.15,
                character_tag_display_threshold=0.35,
                auto_approve_threshold=0.9,
            )
        )
        session.add(
            AppSettings(
                id=1,
                approval_mode=ApprovalMode.MANUAL,
                refresh_cron="0 */6 * * *",
                refresh_enabled=True,
                download_base_dir="/download",
                illustration_tagger_enabled=True,
                illustration_auto_approve_enabled=False,
                active_analysis_profile_id=profile_id,
            )
        )
        item = make_item("unsupported-profile-item")
        session.add(item)
        session.commit()

        with pytest.raises(TaggerUnavailableError):
            analyze_item(session, item)


def test_refresh_runs_analysis_between_ingest_and_download(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_ingest(_session: Session) -> IngestResult:
        calls.append("ingest")
        return IngestResult(new_items=1, skipped=0)

    def fake_analysis(_session: Session) -> None:
        calls.append("analysis")

    def fake_downloads(_session: Session) -> DownloadBatchResult:
        calls.append("download")
        return DownloadBatchResult(triggered=0, failed=0)

    monkeypatch.setattr("upvote_monitor.services.refresh.ingest_items", fake_ingest)
    monkeypatch.setattr(
        "upvote_monitor.services.refresh.process_pending_analysis",
        fake_analysis,
    )
    monkeypatch.setattr(
        "upvote_monitor.services.refresh.process_pending_downloads",
        fake_downloads,
    )

    with Session(engine) as session:
        add_settings(session, tagger_enabled=False, auto_approve_enabled=False)
        run = create_refresh_run(session)
        execute_refresh_run(session, run.id)

    assert calls == ["ingest", "analysis", "download"]
