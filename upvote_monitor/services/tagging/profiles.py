from dataclasses import dataclass

from sqlmodel import Session, select

from upvote_monitor.db.models import (
    DEFAULT_ANALYSIS_PROFILE_ID,
    AnalysisProfile,
    AppSettings,
)

SCORING_VERSION = "illustration-v1"
DEFAULT_GENERAL_TAG_STORAGE_THRESHOLD = 0.01
DEFAULT_CHARACTER_TAG_STORAGE_THRESHOLD = 0.01
DEFAULT_GENERAL_TAG_DISPLAY_THRESHOLD = 0.15
DEFAULT_CHARACTER_TAG_DISPLAY_THRESHOLD = 0.35


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
        model_name="SmilingWolf/wd-swinv2-tagger-v3",
        model_version="main",
        scoring_version=SCORING_VERSION,
        general_tag_storage_threshold=DEFAULT_GENERAL_TAG_STORAGE_THRESHOLD,
        character_tag_storage_threshold=DEFAULT_CHARACTER_TAG_STORAGE_THRESHOLD,
        general_tag_display_threshold=DEFAULT_GENERAL_TAG_DISPLAY_THRESHOLD,
        character_tag_display_threshold=DEFAULT_CHARACTER_TAG_DISPLAY_THRESHOLD,
        auto_approve_threshold=0.90,
    ),
    BuiltInAnalysisProfile(
        id="wd-v1-4-vit-v2",
        name="WD v1.4 ViT v2",
        model_name="SmilingWolf/wd-v1-4-vit-tagger-v2",
        model_version="main",
        scoring_version=SCORING_VERSION,
        general_tag_storage_threshold=DEFAULT_GENERAL_TAG_STORAGE_THRESHOLD,
        character_tag_storage_threshold=DEFAULT_CHARACTER_TAG_STORAGE_THRESHOLD,
        general_tag_display_threshold=DEFAULT_GENERAL_TAG_DISPLAY_THRESHOLD,
        character_tag_display_threshold=DEFAULT_CHARACTER_TAG_DISPLAY_THRESHOLD,
        auto_approve_threshold=0.90,
    ),
)


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

    if changed:
        session.commit()


def list_analysis_profiles(session: Session) -> list[AnalysisProfile]:
    return list(session.exec(select(AnalysisProfile).order_by(AnalysisProfile.name)).all())


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
