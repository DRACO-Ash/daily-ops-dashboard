from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.event_timer import EventTimer
from app.models.user import User
from app.schemas.event_timer import EventTimerCreate, EventTimerList, EventTimerRead
from app.services.audit import write_audit

router = APIRouter(prefix="/event-timers", tags=["event-timers"])

# Dismissed timers fall off the active list after this long. Long
# enough that an operator scrolling back through a shift can still
# see what was acknowledged; short enough that the active list stays
# uncluttered across shifts.
_INCLUDE_DISMISSED_WINDOW = timedelta(hours=12)


@router.get("", response_model=EventTimerList)
async def list_active_timers(
    include_dismissed: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> EventTimerList:
    stmt = select(EventTimer).order_by(EventTimer.target_time.asc())
    if not include_dismissed:
        cutoff = datetime.now(timezone.utc) - _INCLUDE_DISMISSED_WINDOW
        stmt = stmt.where(
            or_(
                EventTimer.dismissed_at.is_(None),
                EventTimer.dismissed_at >= cutoff,
            )
        )
    items = (await db.execute(stmt)).scalars().all()
    return EventTimerList(items=[EventTimerRead.model_validate(t) for t in items])


@router.post("", response_model=EventTimerRead, status_code=status.HTTP_201_CREATED)
async def create_timer(
    payload: EventTimerCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EventTimerRead:
    target = payload.target_time
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    timer = EventTimer(
        event_key=payload.event_key,
        label=payload.label.strip(),
        target_time=target,
        pre_alert_minutes=payload.pre_alert_minutes,
        shift_date=payload.shift_date,
        created_by=current_user.id,
    )
    db.add(timer)
    await db.flush()

    ip = request.client.host if request.client else None
    await write_audit(
        db,
        action_type="event_timer.create",
        entity_type="event_timer",
        entity_id=str(timer.id),
        user_id=current_user.id,
        ip_address=ip,
        detail={
            "label": timer.label,
            "event_key": timer.event_key,
            "target_time": timer.target_time.isoformat(),
            "pre_alert_minutes": timer.pre_alert_minutes,
        },
    )
    await db.commit()
    await db.refresh(timer)
    return EventTimerRead.model_validate(timer)


async def _load_timer(db: AsyncSession, timer_id: UUID) -> EventTimer:
    timer: Optional[EventTimer] = (
        await db.execute(select(EventTimer).where(EventTimer.id == timer_id))
    ).scalar_one_or_none()
    if timer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timer not found")
    return timer


@router.post("/{timer_id}/acknowledge-pre-alert", response_model=EventTimerRead)
async def acknowledge_pre_alert(
    timer_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EventTimerRead:
    timer = await _load_timer(db, timer_id)
    if timer.pre_alert_fired_at is None:
        timer.pre_alert_fired_at = datetime.now(timezone.utc)
        await db.flush()
        ip = request.client.host if request.client else None
        await write_audit(
            db,
            action_type="event_timer.acknowledge_pre_alert",
            entity_type="event_timer",
            entity_id=str(timer.id),
            user_id=current_user.id,
            ip_address=ip,
            detail={"label": timer.label},
        )
        await db.commit()
        await db.refresh(timer)
    return EventTimerRead.model_validate(timer)


@router.post("/{timer_id}/dismiss", response_model=EventTimerRead)
async def dismiss_timer(
    timer_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EventTimerRead:
    timer = await _load_timer(db, timer_id)
    if timer.dismissed_at is None:
        now = datetime.now(timezone.utc)
        timer.dismissed_at = now
        timer.dismissed_by = current_user.id
        if timer.pre_alert_fired_at is None:
            timer.pre_alert_fired_at = now
        await db.flush()
        ip = request.client.host if request.client else None
        await write_audit(
            db,
            action_type="event_timer.dismiss",
            entity_type="event_timer",
            entity_id=str(timer.id),
            user_id=current_user.id,
            ip_address=ip,
            detail={"label": timer.label, "target_time": timer.target_time.isoformat()},
        )
        await db.commit()
        await db.refresh(timer)
    return EventTimerRead.model_validate(timer)


@router.delete("/{timer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_timer(
    timer_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    timer = await _load_timer(db, timer_id)
    label = timer.label
    await db.delete(timer)
    ip = request.client.host if request.client else None
    await write_audit(
        db,
        action_type="event_timer.delete",
        entity_type="event_timer",
        entity_id=str(timer_id),
        user_id=current_user.id,
        ip_address=ip,
        detail={"label": label},
    )
    await db.commit()
