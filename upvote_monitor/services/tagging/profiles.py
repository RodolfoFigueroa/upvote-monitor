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
DEFAULT_GENERAL_TAG_STORAGE_THRESHOLD = 0.01
DEFAULT_CHARACTER_TAG_STORAGE_THRESHOLD = 0.01
DEFAULT_GENERAL_TAG_DISPLAY_THRESHOLD = 0.15
DEFAULT_CHARACTER_TAG_DISPLAY_THRESHOLD = 0.35
DEPRECATED_BUILT_IN_ANALYSIS_PROFILE_IDS = ("wd-v1-4-vit-v2",)


@dataclass(frozen=True)
class BuiltInAnalysisProfile:
    id: str
    name: str
    model_name: str
    model_version: str
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
        model_version="main",
        scoring_version=SCORING_VERSION,
        general_tag_storage_threshold=DEFAULT_GENERAL_TAG_STORAGE_THRESHOLD,
        character_tag_storage_threshold=DEFAULT_CHARACTER_TAG_STORAGE_THRESHOLD,
        general_tag_display_threshold=DEFAULT_GENERAL_TAG_DISPLAY_THRESHOLD,
        character_tag_display_threshold=DEFAULT_CHARACTER_TAG_DISPLAY_THRESHOLD,
        auto_approve_threshold=0.90,
    ),
    BuiltInAnalysisProfile(
        id="wd-eva02-large-v3",
        name="WD EVA02 Large v3",
        model_name=WD_EVA02_LARGE_V3_REPO_ID,
        model_version="main",
        scoring_version=SCORING_VERSION,
        general_tag_storage_threshold=DEFAULT_GENERAL_TAG_STORAGE_THRESHOLD,
        character_tag_storage_threshold=DEFAULT_CHARACTER_TAG_STORAGE_THRESHOLD,
        general_tag_display_threshold=DEFAULT_GENERAL_TAG_DISPLAY_THRESHOLD,
        character_tag_display_threshold=DEFAULT_CHARACTER_TAG_DISPLAY_THRESHOLD,
        auto_approve_threshold=0.92,
    ),
    BuiltInAnalysisProfile(
        id="wd-vit-large-v3",
        name="WD ViT Large v3",
        model_name=WD_VIT_LARGE_V3_REPO_ID,
        model_version="main",
        scoring_version=SCORING_VERSION,
        general_tag_storage_threshold=DEFAULT_GENERAL_TAG_STORAGE_THRESHOLD,
        character_tag_storage_threshold=DEFAULT_CHARACTER_TAG_STORAGE_THRESHOLD,
        general_tag_display_threshold=DEFAULT_GENERAL_TAG_DISPLAY_THRESHOLD,
        character_tag_display_threshold=DEFAULT_CHARACTER_TAG_DISPLAY_THRESHOLD,
        auto_approve_threshold=0.92,
    ),
    BuiltInAnalysisProfile(
        id="pixai-v0-9-onnx",
        name="PixAI Tagger v0.9 ONNX",
        model_name=PIXAI_TAGGER_V0_9_ONNX_REPO_ID,
        model_version="main",
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
                )
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
        session.exec(select(AnalysisProfile).order_by(AnalysisProfile.name)).all()
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
