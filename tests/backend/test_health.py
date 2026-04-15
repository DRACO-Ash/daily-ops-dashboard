from unittest.mock import AsyncMock

import pytest
from app.db.session import get_db
from app.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def override_get_db():
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.execute = AsyncMock()
    yield mock_session


app.dependency_overrides[get_db] = override_get_db


@pytest.mark.asyncio
async def test_health_returns_ok() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
