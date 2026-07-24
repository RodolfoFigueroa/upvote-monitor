from pydantic import BaseModel, field_validator

from upvote_monitor.enums import RuleTargetType
from upvote_monitor.services.approval import normalize_rule_target
from upvote_monitor.sources.reddit import reddit_community_label


class RuleEntry(BaseModel):
    source: str = "reddit"
    target_type: RuleTargetType = RuleTargetType.COMMUNITY
    target_value: str
    target_label: str


class RuleListsResponse(BaseModel):
    whitelist: list[RuleEntry]
    blacklist: list[RuleEntry]


class RuleEntryRequest(BaseModel):
    source: str = "reddit"
    target_type: RuleTargetType = RuleTargetType.COMMUNITY
    target_value: str

    @field_validator("source")
    @classmethod
    def normalize_source(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            msg = "source must not be empty"
            raise ValueError(msg)
        return normalized

    @field_validator("target_value")
    @classmethod
    def target_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            msg = "target_value must not be empty"
            raise ValueError(msg)
        return value

    def normalized_target_value(self) -> str:
        return normalize_rule_target(self.source, self.target_type, self.target_value)

    def target_label(self) -> str:
        if self.source == "reddit" and self.target_type == RuleTargetType.COMMUNITY:
            return reddit_community_label(self.target_value)
        if self.target_type == RuleTargetType.AUTHOR:
            return f"@{self.normalized_target_value()}"
        return self.normalized_target_value()
