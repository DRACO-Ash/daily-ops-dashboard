"""Auth route error paths not covered by test_auth.py: malformed refresh/logout claims."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from app.api.v1.routes import auth as auth_routes
from app.config import settings
from app.core.security import create_refresh_token, hash_password
from app.db.session import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.user import User, UserRole
from httpx import ASGITransport, AsyncClient


def _make_user(is_active: bool = True) -> User:
    now = datetime.now(timezone.utc)
    return User(
        id=uuid.uuid4(),
        username="alice",
        email="alice@example.test",
        password_hash=hash_password("secret"),
        role=UserRole.OPERATOR.value,
        is_active=is_active,
        created_at=now,
        updated_at=now,
    )


def _signed(claims: dict[str, Any]) -> str:
    return jwt.encode(claims, settings.app_secret_key, algorithm=settings.jwt_algorithm)


def _refresh_claims(**overrides: Any) -> dict[str, Any]:
    claims: dict[str, Any] = {
        "sub": str(uuid.uuid4()),
        "jti": str(uuid.uuid4()),
        "type": "refresh",
        "exp": datetime.now(timezone.utc) + timedelta(days=1),
    }
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


class _DB:
    def __init__(self, user: Optional[User]) -> None:
        self.session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = user
        self.session.execute = AsyncMock(return_value=result)
        self.session.commit = AsyncMock()
        app.dependency_overrides[get_db] = self._get_db

    async def _get_db(self):
        yield self.session


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


@pytest.fixture(autouse=True)
def audit_calls(monkeypatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_write_audit(db, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(auth_routes, "write_audit", fake_write_audit)
    return calls


@pytest.fixture(autouse=True)
def revoked(monkeypatch) -> dict[str, Any]:
    store: dict[str, Any] = {}

    async def fake_is_revoked(db, jti):
        return jti in store

    async def fake_revoke(db, *, jti, user_id, expires_at):
        store[jti] = (user_id, expires_at)

    monkeypatch.setattr(auth_routes, "is_revoked", fake_is_revoked)
    monkeypatch.setattr(auth_routes, "revoke", fake_revoke)
    return store


async def _post(path: str, token: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(path, json={"refresh_token": token})


@pytest.mark.parametrize(
    ("claims", "reason"),
    [
        ({"sub": ""}, "missing_subject"),
        ({"jti": ""}, "missing_jti"),
        ({"sub": "not-a-uuid"}, "malformed_subject"),
        ({"type": "access"}, "invalid_token"),
    ],
)
async def test_refresh_rejects_bad_claims(audit_calls, revoked, claims, reason) -> None:
    db = _DB(_make_user())

    response = await _post("/api/v1/auth/refresh", _signed(_refresh_claims(**claims)))

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid refresh token"
    assert [c["detail"]["reason"] for c in audit_calls] == [reason]
    assert audit_calls[0]["action_type"] == "auth.token.refresh"
    assert audit_calls[0]["user_id"] is None
    assert revoked == {}
    db.session.commit.assert_awaited_once()


@pytest.mark.parametrize("user", [None, _make_user(is_active=False)])
async def test_refresh_rejects_missing_or_inactive_user(audit_calls, revoked, user) -> None:
    _DB(user)

    response = await _post("/api/v1/auth/refresh", create_refresh_token(str(uuid.uuid4())))

    assert response.status_code == 401
    assert audit_calls[0]["detail"]["reason"] == "inactive_user"
    assert audit_calls[0]["user_id"] == (user.id if user is not None else None)
    assert revoked == {}


async def test_refresh_success_records_expiry_of_revoked_jti(revoked) -> None:
    user = _make_user()
    _DB(user)
    exp = datetime(2030, 1, 1, tzinfo=timezone.utc)
    jti = str(uuid.uuid4())

    response = await _post(
        "/api/v1/auth/refresh", _signed(_refresh_claims(sub=str(user.id), jti=jti, exp=exp))
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] != body["refresh_token"]
    assert revoked[jti] == (user.id, exp)


@pytest.mark.parametrize(
    ("claims", "reason"),
    [
        ({"sub": ""}, "missing_claim"),
        ({"jti": ""}, "missing_claim"),
        ({"sub": "12345"}, "malformed_subject"),
        ({"type": "access"}, "invalid_token"),
    ],
)
async def test_logout_rejects_bad_claims(audit_calls, revoked, claims, reason) -> None:
    _DB(None)

    response = await _post("/api/v1/auth/logout", _signed(_refresh_claims(**claims)))

    assert response.status_code == 401
    assert audit_calls[0]["action_type"] == "auth.user.logout"
    assert audit_calls[0]["detail"] == {"success": False, "reason": reason}
    assert audit_calls[0]["user_id"] is None
    assert revoked == {}


async def test_me_returns_current_user() -> None:
    user = _make_user()

    async def _get():
        return user

    app.dependency_overrides[get_current_user] = _get
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/auth/me")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(user.id)
    assert body["username"] == "alice"
    assert body["role"] == "operator"
    assert "password_hash" not in body
