from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import Session, select

from upvote_monitor.api.deps import get_db_session
from upvote_monitor.db.models import SourceRule
from upvote_monitor.enums import ListType, RuleTargetType
from upvote_monitor.schemas.rules import RuleEntry, RuleEntryRequest, RuleListsResponse
from upvote_monitor.services.approval import recompute_pending_items_for_rule
from upvote_monitor.services.download import run_download_background
from upvote_monitor.services.refresh_status import broadcast_review_queue_changed

router = APIRouter(prefix="/rules", tags=["rules"])


def _entry_from_rule(rule: SourceRule) -> RuleEntry:
    return RuleEntry(
        source=rule.source,
        target_type=rule.target_type,
        target_value=rule.target_value,
        target_label=rule.target_label,
    )


def _load_lists(session: Session) -> RuleListsResponse:
    entries = session.exec(select(SourceRule)).all()
    whitelist = sorted(
        (
            _entry_from_rule(entry)
            for entry in entries
            if entry.rule_type == ListType.WHITELIST
        ),
        key=lambda entry: (entry.source, entry.target_type.value, entry.target_value),
    )
    blacklist = sorted(
        (
            _entry_from_rule(entry)
            for entry in entries
            if entry.rule_type == ListType.BLACKLIST
        ),
        key=lambda entry: (entry.source, entry.target_type.value, entry.target_value),
    )
    return RuleListsResponse(whitelist=whitelist, blacklist=blacklist)


def _recompute_and_queue_downloads(
    session: Session,
    body: RuleEntryRequest,
    background_tasks: BackgroundTasks,
) -> None:
    target_value = body.normalized_target_value()
    result = recompute_pending_items_for_rule(
        session,
        body.source,
        body.target_type,
        target_value,
    )
    for item_id in result.approved_item_ids:
        background_tasks.add_task(run_download_background, item_id)
    broadcast_review_queue_changed(
        source=body.source,
        target_type=body.target_type.value,
        target_value=target_value,
    )


def _find_rule(
    session: Session,
    rule_type: ListType,
    body: RuleEntryRequest,
) -> SourceRule | None:
    return session.exec(
        select(SourceRule).where(
            SourceRule.source == body.source,
            SourceRule.rule_type == rule_type,
            SourceRule.target_type == body.target_type,
            SourceRule.target_value == body.normalized_target_value(),
        ),
    ).first()


@router.get("")
def get_rules(
    session: Annotated[Session, Depends(get_db_session)],
) -> RuleListsResponse:
    return _load_lists(session)


@router.post("/whitelist")
def add_to_whitelist(
    body: RuleEntryRequest,
    background_tasks: BackgroundTasks,
    session: Annotated[Session, Depends(get_db_session)],
) -> RuleListsResponse:
    existing = _find_rule(session, ListType.WHITELIST, body)
    if existing is None:
        session.add(
            SourceRule(
                source=body.source,
                rule_type=ListType.WHITELIST,
                target_type=body.target_type,
                target_value=body.normalized_target_value(),
                target_label=body.target_label(),
            ),
        )
        session.commit()
    _recompute_and_queue_downloads(session, body, background_tasks)
    return _load_lists(session)


@router.delete(
    "/whitelist/{source}/{target_type}/{target_value}",
)
def remove_from_whitelist(
    source: str,
    target_type: RuleTargetType,
    target_value: str,
    background_tasks: BackgroundTasks,
    session: Annotated[Session, Depends(get_db_session)],
) -> RuleListsResponse:
    body = RuleEntryRequest(
        source=source,
        target_type=target_type,
        target_value=target_value,
    )
    entry = _find_rule(session, ListType.WHITELIST, body)
    if entry is None:
        raise HTTPException(status_code=404, detail="Rule not in whitelist")
    session.delete(entry)
    session.commit()
    _recompute_and_queue_downloads(session, body, background_tasks)
    return _load_lists(session)


@router.post("/blacklist")
def add_to_blacklist(
    body: RuleEntryRequest,
    background_tasks: BackgroundTasks,
    session: Annotated[Session, Depends(get_db_session)],
) -> RuleListsResponse:
    existing = _find_rule(session, ListType.BLACKLIST, body)
    if existing is None:
        session.add(
            SourceRule(
                source=body.source,
                rule_type=ListType.BLACKLIST,
                target_type=body.target_type,
                target_value=body.normalized_target_value(),
                target_label=body.target_label(),
            ),
        )
        session.commit()
    _recompute_and_queue_downloads(session, body, background_tasks)
    return _load_lists(session)


@router.delete(
    "/blacklist/{source}/{target_type}/{target_value}",
)
def remove_from_blacklist(
    source: str,
    target_type: RuleTargetType,
    target_value: str,
    background_tasks: BackgroundTasks,
    session: Annotated[Session, Depends(get_db_session)],
) -> RuleListsResponse:
    body = RuleEntryRequest(
        source=source,
        target_type=target_type,
        target_value=target_value,
    )
    entry = _find_rule(session, ListType.BLACKLIST, body)
    if entry is None:
        raise HTTPException(status_code=404, detail="Rule not in blacklist")
    session.delete(entry)
    session.commit()
    _recompute_and_queue_downloads(session, body, background_tasks)
    return _load_lists(session)
