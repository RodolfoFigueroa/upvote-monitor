import re

from upvote_monitor.db.models import DEFAULT_ANALYSIS_PROFILE_ID
from upvote_monitor.services.tagging.profiles import BUILT_IN_ANALYSIS_PROFILES


def test_built_in_profiles_have_complete_immutable_identity() -> None:
    sha_pattern = re.compile(r"^[0-9a-f]{40}$")
    checksum_pattern = re.compile(r"^[0-9a-f]{64}$")

    assert DEFAULT_ANALYSIS_PROFILE_ID.endswith(
        BUILT_IN_ANALYSIS_PROFILES[0].model_revision[:8],
    )
    for profile in BUILT_IN_ANALYSIS_PROFILES:
        assert sha_pattern.fullmatch(profile.model_revision)
        assert profile.model_version == profile.model_revision
        assert checksum_pattern.fullmatch(profile.model_sha256)
        assert profile.preprocessing_version
        assert profile.scoring_version
        assert profile.model_revision[:8] in profile.id
        assert profile.model_version != "main"
