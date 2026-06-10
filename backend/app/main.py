import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routes import assistant, audit, auth, elsets, health, notifications, procedures
from app.config import settings
from app.core.logging import configure_logging
from app.core.request_id import REQUEST_ID_HEADER, RequestIDMiddleware
from app.services.background_refresh import background_refresh_loop

configure_logging()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task: asyncio.Task | None = None
    if settings.background_refresh_enabled:
        task = asyncio.create_task(background_refresh_loop())
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Background refresh task exited with error")


app = FastAPI(
    title="Daily Operations Dashboard",
    version="0.2.0",
    docs_url="/api/docs" if settings.app_env == "development" else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(RequestIDMiddleware)

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
app.include_router(procedures.router, prefix="/api/v1")
app.include_router(assistant.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
