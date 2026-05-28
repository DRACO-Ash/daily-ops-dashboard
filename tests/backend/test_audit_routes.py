import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.db.session import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.audit import AuditLog
from app.models.user import User, UserRole
from httpx import ASGITransport, AsyncClient


def _make_user(role: UserRole = UserRole.ADMIN) -> User:
    now = datetime.now(timezone.utc)
    return User(
        id=uuid.uuid4(),
        username=f"user-{role.value}",
        email=None,
        password_hash="not-used-in-this-test",
        role=role.value,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def _make_audit(action_type: str = "udl.elset.ingest") -> AuditLog:
    return AuditLog(
        id=uuid.uuid4(),
        timestamp=datetime.now(timezone.utc),
        user_id=uuid.uuid4(),
        action_type=action_type,
        entity_type="elset_ingest_run",
        entity_id=None,
        ip_address="127.0.0.1",
        detail='{"success": true}',
        previous_hash=None,
        entry_hash="a" * 64,
    )


def _override_current_user(user: User):
    async def _get():
        return user

    return _get


def _override_db_for_audit(rows: list[AuditLog], total: int):
    async def _get_db():
        session = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = total
        items_result = MagicMock()
        items_result.scalars.return_value.all.return_value = rows
        session.execute = AsyncMock(side_effect=[count_result, items_result])
        yield session

    return _get_db


@pytest.fixture(autouse=True)
def _restore_overrides():
    prior_db = app.dependency_overrides.get(get_db)
    prior_user = app.dependency_overrides.get(get_current_user)
    yield
    if prior_db is not None:
        app.dependency_overrides[get_db] = prior_db
    else:
        app.dependency_overrides.pop(get_db, None)
    if prior_user is not None:
        app.dependency_overrides[get_current_user] = prior_user
    else:
        app.dependency_overrides.pop(get_current_user, None)


async def test_audit_rejects_analyst_with_403() -> None:
    analyst = _make_user(role=UserRole.ANALYST)
    app.dependency_overrides[get_current_user] = _override_current_user(analyst)
    app.dependency_overrides[get_db] = _override_db_for_audit([], 0)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/audit")

    assert response.status_code == 403


async def test_audit_accepts_operator() -> None:
    operator = _make_user(role=UserRole.OPERATOR)
    app.dependency_overrides[get_current_user] = _override_current_user(operator)
    rows = [_make_audit(), _make_audit("auth.user.login")]
    app.dependency_overrides[get_db] = _override_db_for_audit(rows, len(rows))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/audit")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    assert body["items"][0]["action_type"] == "udl.elset.ingest"


async def test_audit_accepts_admin_and_returns_page_shape() -> None:
    admin = _make_user(role=UserRole.ADMIN)
    app.dependency_overrides[get_current_user] = _override_current_user(admin)
    rows = [_make_audit()]
    app.dependency_overrides[get_db] = _override_db_for_audit(rows, 42)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/audit",
            params={"action_type": "udl.elset.ingest", "limit": 20, "offset": 0},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert body["total"] == 42
    assert len(body["items"]) == 1
    assert "entry_hash" in body["items"][0]


async def test_audit_requires_authentication() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/audit")

    assert response.status_code == 401
