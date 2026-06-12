from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.notification import Notification
from app.models.user import User
from app.schemas.notification import (
    NotificationDetail,
    NotificationIngestRequest,
    NotificationIngestResponse,
    NotificationPage,
    NotificationRead,
)
from app.services.notification_ingest import ingest_notifications
from app.services.notification_query import aliased_deduped_notifications
from app.services.udl_client import UDLAuthError, UDLClient, UDLClientError

router = APIRouter(prefix="/notifications", tags=["notifications"])

NotificationSortColumn = Literal[
    "notso_identifier",
    "notice_id",
    "msg_type",
    "event_type",
    "status",
    "publish_date",
    "effective_from",
    "effective_until",
    "sat_no",
    "udl_created_at",
    "created_at",
]


@router.get("", response_model=NotificationPage)
async def list_notifications(
    msg_type: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    sat_no: Optional[int] = Query(None),
    effective_from_gte: Optional[datetime] = Query(None),
    effective_from_lte: Optional[datetime] = Query(None),
    created_at_gte: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort_by: NotificationSortColumn = Query("udl_created_at"),
    sort_dir: Literal["asc", "desc"] = Query("desc"),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> NotificationPage:
    conditions: list = []
    if msg_type is not None:
        conditions.append(Notification.msg_type == msg_type)
    if event_type is not None:
        conditions.append(Notification.event_type == event_type)
    if status is not None:
        conditions.append(Notification.status == status)
    if sat_no is not None:
        conditions.append(Notification.sat_no == sat_no)
    if effective_from_gte is not None:
        conditions.append(Notification.effective_from >= effective_from_gte)
    if effective_from_lte is not None:
        conditions.append(Notification.effective_from <= effective_from_lte)
    if created_at_gte is not None:
        conditions.append(Notification.udl_created_at >= created_at_gte)

    notif_alias, dedup_subq = aliased_deduped_notifications(conditions)

    count_stmt = select(sa_func.count()).select_from(dedup_subq)
    total = (await db.execute(count_stmt)).scalar_one()

    sort_column = getattr(notif_alias, sort_by)
    order = sort_column.asc() if sort_dir == "asc" else sort_column.desc()
    items_stmt = (
        select(notif_alias)
        .order_by(order.nullslast(), notif_alias.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    items_result = await db.execute(items_stmt)
    items = items_result.scalars().all()

    return NotificationPage(
        items=[NotificationRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{notification_id}", response_model=NotificationDetail)
async def get_notification(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> NotificationDetail:
    result = await db.execute(select(Notification).where(Notification.id == notification_id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return NotificationDetail.model_validate(row)


@router.post("/ingest", response_model=NotificationIngestResponse)
async def trigger_notification_ingest(
    payload: NotificationIngestRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationIngestResponse:
    ip_address = request.client.host if request.client else None
    try:
        async with UDLClient() as client:
            result = await ingest_notifications(
                db,
                client=client,
                msg_type=payload.msg_type,
                created_at_gte=payload.created_at_gte,
                data_mode=payload.data_mode,
                source=payload.source,
                max_results=payload.max_results,
                user_id=current_user.id,
                ip_address=ip_address,
            )
    except UDLAuthError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except UDLClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return NotificationIngestResponse(
        pulled=result.pulled,
        inserted=result.inserted,
        updated=result.updated,
        skipped=result.skipped,
    )
