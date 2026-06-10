from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.maneuver import Maneuver
from app.models.user import User
from app.schemas.maneuver import ManeuverDetail, ManeuverPage, ManeuverRead

router = APIRouter(prefix="/maneuvers", tags=["maneuvers"])

ManeuverSortColumn = Literal[
    "sat_no",
    "event_start_time",
    "event_stop_time",
    "mnvr_type",
    "udl_created_at",
    "created_at",
]


@router.get("", response_model=ManeuverPage)
async def list_maneuvers(
    sat_no: Optional[int] = Query(None),
    mnvr_type: Optional[str] = Query(None),
    event_start_time_gte: Optional[datetime] = Query(None),
    event_start_time_lte: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort_by: ManeuverSortColumn = Query("event_start_time"),
    sort_dir: Literal["asc", "desc"] = Query("desc"),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> ManeuverPage:
    base = select(Maneuver)
    conditions = []
    if sat_no is not None:
        conditions.append(Maneuver.sat_no == sat_no)
    if mnvr_type is not None:
        conditions.append(Maneuver.mnvr_type == mnvr_type)
    if event_start_time_gte is not None:
        conditions.append(Maneuver.event_start_time >= event_start_time_gte)
    if event_start_time_lte is not None:
        conditions.append(Maneuver.event_start_time <= event_start_time_lte)
    if conditions:
        base = base.where(*conditions)

    count_stmt = select(sa_func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    sort_column = getattr(Maneuver, sort_by)
    order = sort_column.asc() if sort_dir == "asc" else sort_column.desc()
    items_stmt = (
        base.order_by(order.nullslast(), Maneuver.created_at.desc()).limit(limit).offset(offset)
    )
    items = (await db.execute(items_stmt)).scalars().all()

    return ManeuverPage(
        items=[ManeuverRead.model_validate(m) for m in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{maneuver_id}", response_model=ManeuverDetail)
async def get_maneuver(
    maneuver_id: UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> ManeuverDetail:
    row = (
        await db.execute(select(Maneuver).where(Maneuver.id == maneuver_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maneuver not found")
    return ManeuverDetail.model_validate(row)
