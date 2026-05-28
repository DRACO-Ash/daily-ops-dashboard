from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.elset import Elset
from app.models.user import User
from app.schemas.elset import (
    ElsetDetail,
    ElsetIngestRequest,
    ElsetIngestResponse,
    ElsetPage,
    ElsetRead,
)
from app.services.elset_ingest import ingest_elsets
from app.services.udl_client import UDLAuthError, UDLClient, UDLClientError

router = APIRouter(prefix="/elsets", tags=["elsets"])


@router.get("", response_model=ElsetPage)
async def list_elsets(
    sat_no: Optional[int] = Query(None),
    epoch_gte: Optional[datetime] = Query(None),
    epoch_lte: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> ElsetPage:
    base = select(Elset)
    conditions = []
    if sat_no is not None:
        conditions.append(Elset.sat_no == sat_no)
    if epoch_gte is not None:
        conditions.append(Elset.epoch >= epoch_gte)
    if epoch_lte is not None:
        conditions.append(Elset.epoch <= epoch_lte)
    if conditions:
        base = base.where(*conditions)

    count_stmt = select(sa_func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    items_stmt = base.order_by(Elset.epoch.desc()).limit(limit).offset(offset)
    items_result = await db.execute(items_stmt)
    items = items_result.scalars().all()

    return ElsetPage(
        items=[ElsetRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{elset_id}", response_model=ElsetDetail)
async def get_elset(
    elset_id: UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> ElsetDetail:
    result = await db.execute(select(Elset).where(Elset.id == elset_id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Elset not found")
    return ElsetDetail.model_validate(row)


@router.post("/ingest", response_model=ElsetIngestResponse)
async def trigger_ingest(
    payload: ElsetIngestRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ElsetIngestResponse:
    ip_address = request.client.host if request.client else None
    try:
        async with UDLClient() as client:
            result = await ingest_elsets(
                db,
                client=client,
                epoch_gte=payload.epoch_gte,
                sat_no=payload.sat_no,
                max_results=payload.max_results,
                user_id=current_user.id,
                ip_address=ip_address,
            )
    except UDLAuthError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except UDLClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return ElsetIngestResponse(
        pulled=result.pulled,
        inserted=result.inserted,
        updated=result.updated,
        skipped=result.skipped,
    )
