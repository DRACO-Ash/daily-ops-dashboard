from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.mattermost_message import MattermostMessage
from app.models.user import User
from app.schemas.mattermost import MattermostMessagePage, MattermostMessageRead

router = APIRouter(prefix="/mattermost", tags=["mattermost"])


@router.get("/messages", response_model=MattermostMessagePage)
async def list_messages(
    channel_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    posted_at_gte: Optional[datetime] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> MattermostMessagePage:
    base = select(MattermostMessage)
    conditions = []
    if channel_id is not None:
        conditions.append(MattermostMessage.channel_id == channel_id)
    if user_id is not None:
        conditions.append(MattermostMessage.user_id == user_id)
    if posted_at_gte is not None:
        conditions.append(MattermostMessage.posted_at >= posted_at_gte)
    if conditions:
        base = base.where(*conditions)

    count_stmt = select(sa_func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    items_stmt = base.order_by(MattermostMessage.posted_at.desc()).limit(limit).offset(offset)
    items = (await db.execute(items_stmt)).scalars().all()

    return MattermostMessagePage(
        items=[MattermostMessageRead.model_validate(m) for m in items],
        total=total,
        limit=limit,
        offset=offset,
    )
