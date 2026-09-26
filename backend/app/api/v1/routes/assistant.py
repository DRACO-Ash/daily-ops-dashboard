from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.assistant_evaluation import AssistantEvaluation
from app.models.event_summary import EventSummary
from app.models.notification import Notification
from app.models.user import User
from app.schemas.assistant import (
    AssistantEvaluationRead,
    AssistantFeed,
    AssistantFeedItem,
)
from app.schemas.notification import NotificationRead
from app.services.assistant import (
    AssistantError,
    evaluate_notification,
    get_latest_evaluation,
)
from app.services.audit import write_audit
from app.services.event_summary import compute_event_key
from app.services.notification_query import aliased_deduped_notifications

router = APIRouter(prefix="/assistant", tags=["assistant"])

_URGENCY_RANK = {"high": 3, "medium": 2, "low": 1, "none": 0, "pending": -1}


def _rollup_urgency(evaluation: AssistantEvaluation | None) -> tuple[str, str | None]:
    """Return (urgency, top_action_summary) for the dashboard rollup."""
    if evaluation is None:
        return "pending", None
    if evaluation.error:
        return "pending", None
    actions = (evaluation.structured or {}).get("next_actions") or []
    if not actions:
        return "none", None
    best: str = "none"
    top_action: str | None = None
    best_rank = -2
    for action in actions:
        if not isinstance(action, dict):
            continue
        urgency = str(action.get("urgency", "")).lower() or "low"
        rank = _URGENCY_RANK.get(urgency, 0)
        if rank > best_rank:
            best_rank = rank
            best = urgency
            text = action.get("action")
            top_action = text if isinstance(text, str) else None
    return best, top_action


async def _latest_evaluations(
    db: AsyncSession, notifications: list[Notification]
) -> dict[UUID, AssistantEvaluation]:
    eval_stmt = select(AssistantEvaluation).where(
        AssistantEvaluation.notification_id.in_([n.id for n in notifications])
    )
    latest_by_nid: dict[UUID, AssistantEvaluation] = {}
    for row in (await db.execute(eval_stmt)).scalars().all():
        existing = latest_by_nid.get(row.notification_id)
        if existing is None or row.evaluated_at > existing.evaluated_at:
            latest_by_nid[row.notification_id] = row
    return latest_by_nid


async def _summaries_by_key(db: AsyncSession, keys: list[str]) -> dict[str, EventSummary]:
    if not keys:
        return {}
    rows = (
        (await db.execute(select(EventSummary).where(EventSummary.event_key.in_(keys))))
        .scalars()
        .all()
    )
    return {row.event_key: row for row in rows}


def _feed_item(
    notification: Notification,
    evaluation: Optional[AssistantEvaluation],
    event_key: str,
    summary_row: Optional[EventSummary],
) -> AssistantFeedItem:
    urgency, top_action = _rollup_urgency(evaluation)
    narrative = None
    count = None
    if summary_row is not None:
        count = summary_row.publication_count
        if not summary_row.error:
            narrative = summary_row.narrative
    return AssistantFeedItem(
        notification=NotificationRead.model_validate(notification),
        evaluation=AssistantEvaluationRead.model_validate(evaluation) if evaluation else None,
        urgency=urgency,
        top_action=top_action,
        event_summary=narrative,
        event_publication_count=count,
        event_key=event_key,
    )


def _feed_sort_key(item: AssistantFeedItem) -> tuple[int, datetime]:
    created = item.notification.udl_created_at or datetime.min.replace(tzinfo=timezone.utc)
    return _URGENCY_RANK.get(item.urgency, -2), created


@router.get("/feed", response_model=AssistantFeed)
async def feed(
    limit: int = Query(100, ge=1, le=500),
    hours: Optional[int] = Query(None, ge=1, le=720),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> AssistantFeed:
    effective_hours = hours or settings.background_notification_window_hours
    window_start = datetime.now(timezone.utc) - timedelta(hours=effective_hours)
    notif_alias, _dedup_subq = aliased_deduped_notifications(
        [Notification.udl_created_at >= window_start]
    )
    notif_stmt = select(notif_alias).order_by(notif_alias.udl_created_at.desc()).limit(limit)
    notifications = list((await db.execute(notif_stmt)).scalars().all())
    if not notifications:
        return AssistantFeed(items=[], window_hours=effective_hours)

    latest_by_nid = await _latest_evaluations(db, notifications)
    event_keys_by_nid = {n.id: compute_event_key(n) for n in notifications}
    summary_by_key = await _summaries_by_key(db, list(set(event_keys_by_nid.values())))

    items = [
        _feed_item(
            n,
            latest_by_nid.get(n.id),
            event_keys_by_nid[n.id],
            summary_by_key.get(event_keys_by_nid[n.id]),
        )
        for n in notifications
    ]
    items.sort(key=_feed_sort_key, reverse=True)
    return AssistantFeed(items=items, window_hours=effective_hours)


@router.get("/evaluation/{notification_id}", response_model=AssistantEvaluationRead)
async def get_evaluation(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> AssistantEvaluationRead:
    evaluation = await get_latest_evaluation(db, notification_id)
    if evaluation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No evaluation exists for this notification yet. POST to /evaluate to create one."
            ),
        )
    return AssistantEvaluationRead.model_validate(evaluation)


@router.post("/evaluate/{notification_id}", response_model=AssistantEvaluationRead)
async def evaluate(
    notification_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssistantEvaluationRead:
    try:
        evaluation = await evaluate_notification(db, notification_id)
    except AssistantError as exc:
        if "Notification not found" in str(exc):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    ip = request.client.host if request.client else None
    await write_audit(
        db,
        action_type="assistant.evaluate",
        entity_type="notification",
        entity_id=str(notification_id),
        user_id=current_user.id,
        ip_address=ip,
        detail={
            "evaluation_id": str(evaluation.id),
            "model": evaluation.model,
            "procedures_used": evaluation.procedures_used,
            "had_error": evaluation.error is not None,
        },
    )
    await db.commit()
    await db.refresh(evaluation)
    return AssistantEvaluationRead.model_validate(evaluation)
