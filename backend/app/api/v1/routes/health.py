from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(db: AsyncSession = None) -> dict:  # type: ignore
    async with get_db() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ok"}
