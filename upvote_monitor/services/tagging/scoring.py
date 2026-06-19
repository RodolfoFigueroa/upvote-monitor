from collections.abc import Mapping

POSITIVE_TAG_WEIGHTS = {
    "anime_screencap": 0.30,
    "manga": 0.30,
    "comic": 0.22,
    "lineart": 0.24,
    "sketch": 0.24,
    "traditional_media": 0.20,
    "watercolor": 0.18,
    "chibi": 0.18,
    "1girl": 0.16,
    "1boy": 0.16,
    "2girls": 0.14,
    "2boys": 0.14,
    "solo": 0.08,
    "no_humans": 0.06,
    "scenery": 0.10,
    "landscape": 0.10,
    "monochrome": 0.08,
    "greyscale": 0.08,
}

NEGATIVE_TAG_WEIGHTS = {
    "realistic": 0.30,
    "photorealistic": 0.40,
    "photo_background": 0.24,
    "cosplay": 0.34,
    "figurine": 0.22,
    "3d": 0.18,
    "food": 0.16,
}


def score_illustration(
    general_tags: Mapping[str, float],
    character_tags: Mapping[str, float],
    ratings: Mapping[str, float],
) -> float:
    positive = sum(
        weight * general_tags.get(tag, 0.0)
        for tag, weight in POSITIVE_TAG_WEIGHTS.items()
    )
    negative = sum(
        weight * general_tags.get(tag, 0.0)
        for tag, weight in NEGATIVE_TAG_WEIGHTS.items()
    )

    high_general = [score for score in general_tags.values() if score >= 0.35]
    high_characters = [score for score in character_tags.values() if score >= 0.35]
    top_general = sorted(general_tags.values(), reverse=True)[:12]

    density_evidence = min(0.25, len(high_general) * 0.025)
    top_tag_evidence = min(0.28, sum(top_general) * 0.035)
    character_evidence = min(0.16, len(high_characters) * 0.08)
    rating_evidence = min(0.10, (max(ratings.values()) if ratings else 0.0) * 0.10)

    max_general = max(general_tags.values()) if general_tags else 0.0
    max_character = max(character_tags.values()) if character_tags else 0.0
    out_of_domain_penalty = 0.30 if max(max_general, max_character) < 0.25 else 0.0

    score = (
        0.08
        + positive
        + density_evidence
        + top_tag_evidence
        + character_evidence
        + rating_evidence
        - negative
        - out_of_domain_penalty
    )
    return max(0.0, min(1.0, score))
