from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.revoked_jti import RevokedJti


async def is_revoked(db: AsyncSession, jti: str) -> bool:
    result = await db.execute(select(RevokedJti.jti).where(RevokedJti.jti == jti).limit(1))
    return result.scalar_one_or_none() is not None


async def revoke(
    db: AsyncSession,
    *,
    jti: str,
    user_id: Optional[UUID],
    expires_at: datetime,
) -> None:
    if await is_revoked(db, jti):
        return
    db.add(RevokedJti(jti=jti, user_id=user_id, expires_at=expires_at))
    await db.flush()
