from dataclasses import dataclass, field

from sqlmodel import Session, select

from upvote_monitor.db.models import AppSettings, ReviewItem, SourceRule
from upvote_monitor.enums import (
    ApprovalMode,
    ApprovalStatus,
    DownloadStatus,
    ListType,
    RuleTargetType,
)
from upvote_monitor.services.media_workflow import set_item_media_approval
from upvote_monitor.sources.reddit import normalize_reddit_community


RuleKey = tuple[str, RuleTargetType, str]


def normalize_rule_target(
    source: str,
    target_type: RuleTargetType,
    value: str,
) -> str:
    if target_type == RuleTargetType.COMMUNITY and source == "reddit":
        return normalize_reddit_community(value)
    if target_type == RuleTargetType.AUTHOR:
        return value.strip().lower().removeprefix("@")
    return value.strip().lower()


def _community_rule_key(item: ReviewItem) -> RuleKey | None:
    if item.community_name is None:
        return None
    return (
        item.source,
        RuleTargetType.COMMUNITY,
        normalize_rule_target(
            item.source,
            RuleTargetType.COMMUNITY,
            item.community_name,
        ),
    )


def _author_rule_key(item: ReviewItem) -> RuleKey | None:
    if item.author_name is None:
        return None
    return (
        item.source,
        RuleTargetType.AUTHOR,
        normalize_rule_target(
            item.source,
            RuleTargetType.AUTHOR,
            item.author_name,
        ),
    )


def _rule_keys_for_item(item: ReviewItem) -> set[RuleKey]:
    keys = {_community_rule_key(item), _author_rule_key(item)}
    return {key for key in keys if key is not None}


def compute_initial_status(
    item: ReviewItem,
    mode: ApprovalMode,
    whitelist: set[RuleKey],
    blacklist: set[RuleKey],
) -> ApprovalStatus:
    rule_keys = _rule_keys_for_item(item)

    if rule_keys & blacklist:
        return ApprovalStatus.REJECTED

    if rule_keys & whitelist:
        return ApprovalStatus.APPROVED

    if mode == ApprovalMode.AUTO:
        return ApprovalStatus.APPROVED

    return ApprovalStatus.UNDER_REVIEW


def load_rule_sets(session: Session) -> tuple[set[RuleKey], set[RuleKey]]:
    entries = session.exec(select(SourceRule)).all()
    whitelist = {
        (e.source, e.target_type, e.target_value)
        for e in entries
        if e.rule_type == ListType.WHITELIST
    }
    blacklist = {
        (e.source, e.target_type, e.target_value)
        for e in entries
        if e.rule_type == ListType.BLACKLIST
    }
    return whitelist, blacklist


@dataclass
class RecomputePendingItemsResult:
    source: str
    target_type: RuleTargetType
    target_value: str
    updated: int = 0
    approved: int = 0
    rejected: int = 0
    approved_item_ids: list[str] = field(default_factory=list)


def recompute_pending_items_for_rule(
    session: Session,
    source: str,
    target_type: RuleTargetType,
    target_value: str,
) -> RecomputePendingItemsResult:
    settings = session.get(AppSettings, 1)
    if settings is None:
        msg = "App settings not initialized"
        raise RuntimeError(msg)

    normalized = normalize_rule_target(source, target_type, target_value)
    whitelist, blacklist = load_rule_sets(session)

    pending_items = session.exec(
        select(ReviewItem).where(
            ReviewItem.approval_status == ApprovalStatus.UNDER_REVIEW
        )
    ).all()
    matching_items = []
    for item in pending_items:
        if item.source != source:
            continue
        if target_type == RuleTargetType.COMMUNITY:
            if item.community_name is None:
                continue
            item_target = normalize_rule_target(
                source, target_type, item.community_name
            )
            if item_target != normalized:
                continue
        elif target_type == RuleTargetType.AUTHOR:
            if item.author_name is None:
                continue
            item_target = normalize_rule_target(source, target_type, item.author_name)
            if item_target != normalized:
                continue
        matching_items.append(item)

    result = RecomputePendingItemsResult(
        source=source,
        target_type=target_type,
        target_value=normalized,
    )
    for item in matching_items:
        new_status = compute_initial_status(
            item,
            settings.approval_mode,
            whitelist,
            blacklist,
        )
        if new_status == ApprovalStatus.UNDER_REVIEW:
            continue

        set_item_media_approval(session, item, new_status)
        result.updated += 1

        if new_status == ApprovalStatus.REJECTED:
            result.rejected += 1
        elif new_status == ApprovalStatus.APPROVED:
            result.approved += 1
            if item.download_status in (
                DownloadStatus.PENDING,
                DownloadStatus.FAILED,
            ):
                result.approved_item_ids.append(item.id)

    if result.updated:
        session.commit()

    return result
