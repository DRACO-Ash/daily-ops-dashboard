from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import require_role
from app.models.audit import AuditLog
from app.models.user import User, UserRole
from app.schemas.audit import AuditLogPage, AuditLogRead

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=AuditLogPage)
async def list_audit_log(
    action_type: Optional[str] = Query(None),
    user_id: Optional[UUID] = Query(None),
    since: Optional[datetime] = Query(None),
    until: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(require_role(UserRole.OPERATOR, UserRole.ADMIN)),
) -> AuditLogPage:
    base = select(AuditLog)
    conditions = []
    if action_type is not None:
        conditions.append(AuditLog.action_type == action_type)
    if user_id is not None:
        conditions.append(AuditLog.user_id == user_id)
    if since is not None:
        conditions.append(AuditLog.timestamp >= since)
    if until is not None:
        conditions.append(AuditLog.timestamp <= until)
    if conditions:
        base = base.where(*conditions)

    count_stmt = select(sa_func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    items_stmt = base.order_by(AuditLog.timestamp.desc()).limit(limit).offset(offset)
    items_result = await db.execute(items_stmt)
    items = items_result.scalars().all()

    return AuditLogPage(
        items=[AuditLogRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )
