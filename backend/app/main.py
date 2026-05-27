from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routes import elsets, health
from app.config import settings
from app.core.logging import configure_logging

configure_logging()

app = FastAPI(
    title="Daily Operations Dashboard",
    version="0.1.0",
    docs_url="/api/docs" if settings.app_env == "development" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(health.router, prefix="/api/v1")
app.include_router(elsets.router, prefix="/api/v1")
