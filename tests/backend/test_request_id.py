from unittest.mock import AsyncMock

import pytest
from app.core.request_id import REQUEST_ID_HEADER
from app.db.session import get_db
from app.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def _override_get_db():
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.execute = AsyncMock()
    yield mock_session


@pytest.fixture(autouse=True)
def _override_db():
    prior = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override_get_db
    yield
    if prior is not None:
        app.dependency_overrides[get_db] = prior
    else:
        app.dependency_overrides.pop(get_db, None)


async def test_response_carries_request_id_header() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert REQUEST_ID_HEADER in response.headers
    assert len(response.headers[REQUEST_ID_HEADER]) > 0


async def test_request_id_is_echoed_when_supplied_by_client() -> None:
    supplied = "abc-12345-test-correlation-id"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/health",
            headers={REQUEST_ID_HEADER: supplied},
        )

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == supplied


async def test_health_detailed_returns_component_breakdown() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health/detailed")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert "version" in body
    assert "environment" in body
    assert "components" in body
    assert "database" in body["components"]
    assert "udl_credentials" in body["components"]
