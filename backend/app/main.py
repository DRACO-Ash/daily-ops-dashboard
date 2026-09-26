import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routes import (
    assistant,
    audit,
    auth,
    elsets,
    event_timers,
    health,
    maneuvers,
    mattermost,
    notifications,
    procedures,
    shift_log,
)
from app.config import settings
from app.core.logging import configure_logging
from app.core.request_id import REQUEST_ID_HEADER, RequestIDMiddleware
from app.core.spa import SecurityHeadersMiddleware, mount_spa
from app.services.background_refresh import (
    maneuver_loop,
    mattermost_loop,
    notification_loop,
)

configure_logging()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    tasks: list[asyncio.Task] = []
    if settings.background_refresh_enabled:
        tasks.append(asyncio.create_task(notification_loop()))
        tasks.append(asyncio.create_task(maneuver_loop()))
        tasks.append(asyncio.create_task(mattermost_loop()))
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Background task exited with error")


app = FastAPI(
    title="Daily Operations Dashboard",
    version="0.2.0",
    docs_url="/api/docs" if settings.app_env == "development" else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.app_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER],
    expose_headers=[REQUEST_ID_HEADER],
)

app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(elsets.router, prefix="/api/v1")
app.include_router(notifications.router, prefix="/api/v1")
app.include_router(maneuvers.router, prefix="/api/v1")
app.include_router(mattermost.router, prefix="/api/v1")
app.include_router(procedures.router, prefix="/api/v1")
app.include_router(shift_log.router, prefix="/api/v1")
app.include_router(event_timers.router, prefix="/api/v1")
app.include_router(assistant.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")

# Registered last so every API route above takes precedence.
mount_spa(app, settings.static_dir)
