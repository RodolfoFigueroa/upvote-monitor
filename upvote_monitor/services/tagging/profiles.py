from dataclasses import dataclass

from sqlmodel import Session, select

from upvote_monitor.db.models import (
    DEFAULT_ANALYSIS_PROFILE_ID,
    AnalysisProfile,
    AppSettings,
)
from upvote_monitor.services.tagging.pixai_tagger import PIXAI_TAGGER_V0_9_ONNX_REPO_ID
from upvote_monitor.services.tagging.wd_tagger import (
    WD_EVA02_LARGE_V3_REPO_ID,
    WD_SWINV2_V3_REPO_ID,
    WD_VIT_LARGE_V3_REPO_ID,
)

SCORING_VERSION = "illustration-v1"
WD_PREPROCESSING_VERSION = "wd-rgba-white-square-bgr-lanczos-v1"
PIXAI_PREPROCESSING_VERSION = "pixai-config-normalize-rgb-v1"
WD_SWINV2_V3_REVISION = "627aef95638667ddcaa3ac8ae625e88ea5b02f51"
WD_SWINV2_V3_MODEL_SHA256 = (
    "e6774bff34d43bd49f75a47db4ef217dce701c9847b546523eb85ff6dbba1db1"
)
WD_EVA02_LARGE_V3_PROFILE_ID = "wd-eva02-large-v3-b25b82a0"
WD_EVA02_LARGE_V3_REVISION = "b25b82a03f7282e41aa2f257a52c7583b710bd1c"
WD_EVA02_LARGE_V3_MODEL_SHA256 = (
    "9e768793060c7939b277ccb382783e8670e8a042d29d77aa736be0c8cc898bfc"
)
WD_VIT_LARGE_V3_PROFILE_ID = "wd-vit-large-v3-ae469aa2"
WD_VIT_LARGE_V3_REVISION = "ae469aa2e4706a3af08d3673cf73a11d1add314c"
WD_VIT_LARGE_V3_MODEL_SHA256 = (
    "e4c8001b000a6c98f2db10794f7c406daa79873d071d6ca924330fa053fa1845"
)
PIXAI_V0_9_ONNX_PROFILE_ID = "pixai-v0-9-onnx-d8cf6669"
PIXAI_V0_9_ONNX_REVISION = "d8cf666911a2c3d10d586d7823259192313c7eb7"
PIXAI_V0_9_ONNX_MODEL_SHA256 = (
    "a8d479098b5e23f253543c93df42391736abbb77c21c2efd3a513b9cda7b3657"
)
DEFAULT_GENERAL_TAG_STORAGE_THRESHOLD = 0.01
DEFAULT_CHARACTER_TAG_STORAGE_THRESHOLD = 0.01
DEFAULT_GENERAL_TAG_DISPLAY_THRESHOLD = 0.15
DEFAULT_CHARACTER_TAG_DISPLAY_THRESHOLD = 0.35
DEPRECATED_BUILT_IN_ANALYSIS_PROFILE_IDS = (
    "wd-v1-4-vit-v2",
    "wd-swinv2-v3-default",
    "wd-eva02-large-v3",
    "wd-vit-large-v3",
    "pixai-v0-9-onnx",
)


@dataclass(frozen=True)
class BuiltInAnalysisProfile:
    id: str
    name: str
    model_name: str
    model_version: str
    model_revision: str
    model_sha256: str
    preprocessing_version: str
    scoring_version: str
    general_tag_storage_threshold: float
    character_tag_storage_threshold: float
    general_tag_display_threshold: float
    character_tag_display_threshold: float
    auto_approve_threshold: float
    enabled: bool = True


BUILT_IN_ANALYSIS_PROFILES = (
    BuiltInAnalysisProfile(
        id=DEFAULT_ANALYSIS_PROFILE_ID,
        name="WD SwinV2 v3",
        model_name=WD_SWINV2_V3_REPO_ID,
        model_version=WD_SWINV2_V3_REVISION,
        model_revision=WD_SWINV2_V3_REVISION,
        model_sha256=WD_SWINV2_V3_MODEL_SHA256,
        preprocessing_version=WD_PREPROCESSING_VERSION,
        scoring_version=SCORING_VERSION,
        general_tag_storage_threshold=DEFAULT_GENERAL_TAG_STORAGE_THRESHOLD,
        character_tag_storage_threshold=DEFAULT_CHARACTER_TAG_STORAGE_THRESHOLD,
        general_tag_display_threshold=DEFAULT_GENERAL_TAG_DISPLAY_THRESHOLD,
        character_tag_display_threshold=DEFAULT_CHARACTER_TAG_DISPLAY_THRESHOLD,
        auto_approve_threshold=0.90,
    ),
    BuiltInAnalysisProfile(
        id=WD_EVA02_LARGE_V3_PROFILE_ID,
        name="WD EVA02 Large v3",
        model_name=WD_EVA02_LARGE_V3_REPO_ID,
        model_version=WD_EVA02_LARGE_V3_REVISION,
        model_revision=WD_EVA02_LARGE_V3_REVISION,
        model_sha256=WD_EVA02_LARGE_V3_MODEL_SHA256,
        preprocessing_version=WD_PREPROCESSING_VERSION,
        scoring_version=SCORING_VERSION,
        general_tag_storage_threshold=DEFAULT_GENERAL_TAG_STORAGE_THRESHOLD,
        character_tag_storage_threshold=DEFAULT_CHARACTER_TAG_STORAGE_THRESHOLD,
        general_tag_display_threshold=DEFAULT_GENERAL_TAG_DISPLAY_THRESHOLD,
        character_tag_display_threshold=DEFAULT_CHARACTER_TAG_DISPLAY_THRESHOLD,
        auto_approve_threshold=0.92,
    ),
    BuiltInAnalysisProfile(
        id=WD_VIT_LARGE_V3_PROFILE_ID,
        name="WD ViT Large v3",
        model_name=WD_VIT_LARGE_V3_REPO_ID,
        model_version=WD_VIT_LARGE_V3_REVISION,
        model_revision=WD_VIT_LARGE_V3_REVISION,
        model_sha256=WD_VIT_LARGE_V3_MODEL_SHA256,
        preprocessing_version=WD_PREPROCESSING_VERSION,
        scoring_version=SCORING_VERSION,
        general_tag_storage_threshold=DEFAULT_GENERAL_TAG_STORAGE_THRESHOLD,
        character_tag_storage_threshold=DEFAULT_CHARACTER_TAG_STORAGE_THRESHOLD,
        general_tag_display_threshold=DEFAULT_GENERAL_TAG_DISPLAY_THRESHOLD,
        character_tag_display_threshold=DEFAULT_CHARACTER_TAG_DISPLAY_THRESHOLD,
        auto_approve_threshold=0.92,
    ),
    BuiltInAnalysisProfile(
        id=PIXAI_V0_9_ONNX_PROFILE_ID,
        name="PixAI Tagger v0.9 ONNX",
        model_name=PIXAI_TAGGER_V0_9_ONNX_REPO_ID,
        model_version=PIXAI_V0_9_ONNX_REVISION,
        model_revision=PIXAI_V0_9_ONNX_REVISION,
        model_sha256=PIXAI_V0_9_ONNX_MODEL_SHA256,
        preprocessing_version=PIXAI_PREPROCESSING_VERSION,
        scoring_version=SCORING_VERSION,
        general_tag_storage_threshold=0.30,
        character_tag_storage_threshold=0.85,
        general_tag_display_threshold=DEFAULT_GENERAL_TAG_DISPLAY_THRESHOLD,
        character_tag_display_threshold=DEFAULT_CHARACTER_TAG_DISPLAY_THRESHOLD,
        auto_approve_threshold=0.97,
    ),
)


def _sync_profile(row: AnalysisProfile, profile: BuiltInAnalysisProfile) -> bool:
    changed = False
    values = {
        "name": profile.name,
        "model_name": profile.model_name,
        "model_version": profile.model_version,
        "model_revision": profile.model_revision,
        "model_sha256": profile.model_sha256,
        "preprocessing_version": profile.preprocessing_version,
        "scoring_version": profile.scoring_version,
        "general_tag_storage_threshold": profile.general_tag_storage_threshold,
        "character_tag_storage_threshold": profile.character_tag_storage_threshold,
        "general_tag_display_threshold": profile.general_tag_display_threshold,
        "character_tag_display_threshold": profile.character_tag_display_threshold,
        "auto_approve_threshold": profile.auto_approve_threshold,
        "enabled": profile.enabled,
    }
    for field, value in values.items():
        if getattr(row, field) != value:
            setattr(row, field, value)
            changed = True
    return changed


def ensure_default_analysis_profiles(session: Session) -> None:
    changed = False
    for profile in BUILT_IN_ANALYSIS_PROFILES:
        row = session.get(AnalysisProfile, profile.id)
        if row is None:
            session.add(
                AnalysisProfile(
                    id=profile.id,
                    name=profile.name,
                    model_name=profile.model_name,
                    model_version=profile.model_version,
                    model_revision=profile.model_revision,
                    model_sha256=profile.model_sha256,
                    preprocessing_version=profile.preprocessing_version,
                    scoring_version=profile.scoring_version,
                    general_tag_storage_threshold=(
                        profile.general_tag_storage_threshold
                    ),
                    character_tag_storage_threshold=(
                        profile.character_tag_storage_threshold
                    ),
                    general_tag_display_threshold=(
                        profile.general_tag_display_threshold
                    ),
                    character_tag_display_threshold=(
                        profile.character_tag_display_threshold
                    ),
                    auto_approve_threshold=profile.auto_approve_threshold,
                    enabled=profile.enabled,
                ),
            )
            changed = True
        elif _sync_profile(row, profile):
            session.add(row)
            changed = True

    for profile_id in DEPRECATED_BUILT_IN_ANALYSIS_PROFILE_IDS:
        row = session.get(AnalysisProfile, profile_id)
        if row is not None and row.enabled:
            row.enabled = False
            session.add(row)
            changed = True

    settings = session.get(AppSettings, 1)
    if (
        settings is not None
        and settings.active_analysis_profile_id
        in DEPRECATED_BUILT_IN_ANALYSIS_PROFILE_IDS
    ):
        settings.active_analysis_profile_id = DEFAULT_ANALYSIS_PROFILE_ID
        session.add(settings)
        changed = True

    if changed:
        session.commit()


def list_analysis_profiles(session: Session) -> list[AnalysisProfile]:
    return list(
        session.exec(select(AnalysisProfile).order_by(AnalysisProfile.name)).all(),
    )


def active_analysis_profile(session: Session) -> AnalysisProfile | None:
    settings = session.get(AppSettings, 1)
    if settings is None:
        return None

    profile = session.get(AnalysisProfile, settings.active_analysis_profile_id)
    if profile is not None and profile.enabled:
        return profile

    fallback = session.get(AnalysisProfile, DEFAULT_ANALYSIS_PROFILE_ID)
    if fallback is not None and fallback.enabled:
        settings.active_analysis_profile_id = fallback.id
        session.add(settings)
        session.commit()
        session.refresh(settings)
        return fallback

    return None
