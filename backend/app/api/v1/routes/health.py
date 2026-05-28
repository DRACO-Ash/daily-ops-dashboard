from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_db

router = APIRouter(tags=["health"])

APP_VERSION = "0.2.0"


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)) -> dict:  # type: ignore[assignment]
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/health/detailed")
async def health_detailed(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    components: dict[str, str] = {}

    try:
        await db.execute(text("SELECT 1"))
        components["database"] = "ok"
    except Exception:
        components["database"] = "down"

    udl_configured = bool(settings.udl_username and settings.udl_password)
    components["udl_credentials"] = "configured" if udl_configured else "missing"

    overall = "ok" if components["database"] == "ok" else "degraded"

    return {
        "status": overall,
        "version": APP_VERSION,
        "environment": settings.app_env,
        "components": components,
    }
