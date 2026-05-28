from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.notso import Notso
from app.models.user import User
from app.schemas.notso import (
    NotsoDetail,
    NotsoIngestRequest,
    NotsoIngestResponse,
    NotsoPage,
    NotsoRead,
)
from app.services.notso_ingest import ingest_notsos
from app.services.udl_client import UDLAuthError, UDLClient, UDLClientError

router = APIRouter(prefix="/notsos", tags=["notsos"])

NotsoSortColumn = Literal[
    "notice_id", "msg_type", "effective_from", "effective_until", "sat_no", "created_at"
]


@router.get("", response_model=NotsoPage)
async def list_notsos(
    msg_type: Optional[str] = Query(None),
    sat_no: Optional[int] = Query(None),
    effective_from_gte: Optional[datetime] = Query(None),
    effective_from_lte: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort_by: NotsoSortColumn = Query("effective_from"),
    sort_dir: Literal["asc", "desc"] = Query("desc"),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> NotsoPage:
    base = select(Notso)
    conditions = []
    if msg_type is not None:
        conditions.append(Notso.msg_type == msg_type)
    if sat_no is not None:
        conditions.append(Notso.sat_no == sat_no)
    if effective_from_gte is not None:
        conditions.append(Notso.effective_from >= effective_from_gte)
    if effective_from_lte is not None:
        conditions.append(Notso.effective_from <= effective_from_lte)
    if conditions:
        base = base.where(*conditions)

    count_stmt = select(sa_func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    sort_column = getattr(Notso, sort_by)
    order = sort_column.asc() if sort_dir == "asc" else sort_column.desc()
    items_stmt = (
        base.order_by(order.nullslast(), Notso.created_at.desc()).limit(limit).offset(offset)
    )
    items_result = await db.execute(items_stmt)
    items = items_result.scalars().all()

    return NotsoPage(
        items=[NotsoRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{notso_id}", response_model=NotsoDetail)
async def get_notso(
    notso_id: UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> NotsoDetail:
    result = await db.execute(select(Notso).where(Notso.id == notso_id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notso not found")
    return NotsoDetail.model_validate(row)


@router.post("/ingest", response_model=NotsoIngestResponse)
async def trigger_notso_ingest(
    payload: NotsoIngestRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotsoIngestResponse:
    ip_address = request.client.host if request.client else None
    try:
        async with UDLClient() as client:
            result = await ingest_notsos(
                db,
                client=client,
                effective_from_gte=payload.effective_from_gte,
                msg_type=payload.msg_type,
                max_results=payload.max_results,
                user_id=current_user.id,
                ip_address=ip_address,
            )
    except UDLAuthError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except UDLClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return NotsoIngestResponse(
        pulled=result.pulled,
        inserted=result.inserted,
        updated=result.updated,
        skipped=result.skipped,
    )
