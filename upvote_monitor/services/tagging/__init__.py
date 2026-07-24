from upvote_monitor.services.tagging.analysis import (
    AnalysisBatchResult,
    process_pending_analysis,
)
from upvote_monitor.services.tagging.pixai_tagger import (
    PIXAI_COMPATIBLE_MODEL_REPOS,
    PIXAI_TAGGER_V0_9_ONNX_REPO_ID,
    PixAITagger,
    get_pixai_tagger,
)
from upvote_monitor.services.tagging.profiles import (
    BUILT_IN_ANALYSIS_PROFILES,
    SCORING_VERSION,
    active_analysis_profile,
    ensure_default_analysis_profiles,
    list_analysis_profiles,
)
from upvote_monitor.services.tagging.scoring import score_illustration
from upvote_monitor.services.tagging.wd_tagger import (
    DEFAULT_MODEL_REPO_ID,
    WD_COMPATIBLE_MODEL_REPOS,
    WD_EVA02_LARGE_V3_REPO_ID,
    WD_SWINV2_V3_REPO_ID,
    WD_VIT_LARGE_V3_REPO_ID,
    WDTagger,
    WDTaggerResult,
)

__all__ = [
    "BUILT_IN_ANALYSIS_PROFILES",
    "DEFAULT_MODEL_REPO_ID",
    "PIXAI_COMPATIBLE_MODEL_REPOS",
    "PIXAI_TAGGER_V0_9_ONNX_REPO_ID",
    "SCORING_VERSION",
    "WD_COMPATIBLE_MODEL_REPOS",
    "WD_EVA02_LARGE_V3_REPO_ID",
    "WD_SWINV2_V3_REPO_ID",
    "WD_VIT_LARGE_V3_REPO_ID",
    "AnalysisBatchResult",
    "PixAITagger",
    "WDTagger",
    "WDTaggerResult",
    "active_analysis_profile",
    "ensure_default_analysis_profiles",
    "get_pixai_tagger",
    "list_analysis_profiles",
    "process_pending_analysis",
    "score_illustration",
]
