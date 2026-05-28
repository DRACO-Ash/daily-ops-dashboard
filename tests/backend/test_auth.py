import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.session import get_db
from app.main import app
from app.models.user import User, UserRole
from httpx import ASGITransport, AsyncClient


def _make_user(
    username: str = "alice",
    password: str = "secret",
    role: UserRole = UserRole.ANALYST,
    is_active: bool = True,
) -> User:
    now = datetime.now(timezone.utc)
    return User(
        id=uuid.uuid4(),
        username=username,
        email=None,
        password_hash=hash_password(password),
        role=role.value,
        is_active=is_active,
        created_at=now,
        updated_at=now,
    )


def _override_db(user: Optional[User]):
    async def _get_db():
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = user
        session.execute = AsyncMock(return_value=result)
        session.commit = AsyncMock()
        yield session

    return _get_db


@pytest.fixture(autouse=True)
def _restore_db_override():
    prior = app.dependency_overrides.get(get_db)
    yield
    if prior is not None:
        app.dependency_overrides[get_db] = prior
    else:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def audit_calls(monkeypatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_write_audit(db, **kwargs):
        calls.append(kwargs)
        return None

    monkeypatch.setattr("app.api.v1.routes.auth.write_audit", fake_write_audit)
    return calls


@pytest.fixture(autouse=True)
def revoked_jtis(monkeypatch) -> set[str]:
    revoked: set[str] = set()

    async def fake_is_revoked(db, jti):
        return jti in revoked

    async def fake_revoke(db, *, jti, user_id, expires_at):
        revoked.add(jti)

    monkeypatch.setattr("app.api.v1.routes.auth.is_revoked", fake_is_revoked)
    monkeypatch.setattr("app.api.v1.routes.auth.revoke", fake_revoke)
    return revoked


def test_hash_and_verify_password() -> None:
    hashed = hash_password("hunter2")
    assert verify_password("hunter2", hashed)
    assert not verify_password("wrong", hashed)


def test_access_token_round_trip() -> None:
    subject = str(uuid.uuid4())
    token = create_access_token(subject)
    decoded = decode_token(token)
    assert decoded is not None
    assert decoded["sub"] == subject
    assert decoded["type"] == "access"


def test_refresh_token_carries_type_refresh() -> None:
    subject = str(uuid.uuid4())
    token = create_refresh_token(subject)
    decoded = decode_token(token)
    assert decoded is not None
    assert decoded["type"] == "refresh"


def test_decode_token_returns_none_on_garbage() -> None:
    assert decode_token("not.a.real.jwt") is None


def test_decode_token_returns_none_on_expired_token() -> None:
    token = create_access_token(str(uuid.uuid4()), expires_delta=timedelta(seconds=-10))
    assert decode_token(token) is None


async def test_login_returns_tokens_on_success() -> None:
    user = _make_user(username="alice", password="secret")
    app.dependency_overrides[get_db] = _override_db(user)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "secret"},
        )

    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"


async def test_login_rejects_wrong_password() -> None:
    user = _make_user(username="alice", password="secret")
    app.dependency_overrides[get_db] = _override_db(user)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "wrong"},
        )

    assert response.status_code == 401


async def test_login_rejects_unknown_user() -> None:
    app.dependency_overrides[get_db] = _override_db(None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": "ghost", "password": "secret"},
        )

    assert response.status_code == 401


async def test_login_rejects_inactive_user() -> None:
    user = _make_user(username="alice", password="secret", is_active=False)
    app.dependency_overrides[get_db] = _override_db(user)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "secret"},
        )

    assert response.status_code == 401


async def test_me_returns_current_user_for_valid_token() -> None:
    user = _make_user(username="alice")
    app.dependency_overrides[get_db] = _override_db(user)
    token = create_access_token(str(user.id))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json()["username"] == "alice"


async def test_me_rejects_missing_token() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/auth/me")

    assert response.status_code == 401


async def test_me_rejects_refresh_token_used_as_access() -> None:
    user = _make_user(username="alice")
    app.dependency_overrides[get_db] = _override_db(user)
    refresh = create_refresh_token(str(user.id))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {refresh}"},
        )

    assert response.status_code == 401


async def test_me_rejects_garbage_token() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer not.a.real.jwt"},
        )

    assert response.status_code == 401


async def test_elsets_ingest_requires_auth() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/elsets/ingest",
            json={"epoch_gte": "2025-01-01T00:00:00Z"},
        )

    assert response.status_code == 401


async def test_refresh_returns_new_tokens() -> None:
    user = _make_user(username="alice")
    app.dependency_overrides[get_db] = _override_db(user)
    refresh_token = create_refresh_token(str(user.id))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )

    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["refresh_token"] != refresh_token
    assert body["token_type"] == "bearer"


async def test_refresh_rejects_access_token_used_as_refresh() -> None:
    user = _make_user(username="alice")
    app.dependency_overrides[get_db] = _override_db(user)
    access = create_access_token(str(user.id))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": access},
        )

    assert response.status_code == 401


async def test_login_success_emits_audit_row(audit_calls) -> None:
    user = _make_user(username="alice", password="secret")
    app.dependency_overrides[get_db] = _override_db(user)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "secret"},
        )

    assert response.status_code == 200
    assert len(audit_calls) == 1
    call = audit_calls[0]
    assert call["action_type"] == "auth.user.login"
    assert call["entity_type"] == "user"
    assert call["entity_id"] == str(user.id)
    assert call["user_id"] == user.id
    assert call["detail"]["success"] is True
    assert call["detail"]["username"] == "alice"
    assert "reason" not in call["detail"]


async def test_login_wrong_password_emits_audit_with_reason(audit_calls) -> None:
    user = _make_user(username="alice", password="secret")
    app.dependency_overrides[get_db] = _override_db(user)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "wrong"},
        )

    assert response.status_code == 401
    assert len(audit_calls) == 1
    call = audit_calls[0]
    assert call["action_type"] == "auth.user.login"
    assert call["user_id"] == user.id
    assert call["detail"]["success"] is False
    assert call["detail"]["reason"] == "wrong_password"


async def test_login_unknown_user_emits_audit_without_user_id(audit_calls) -> None:
    app.dependency_overrides[get_db] = _override_db(None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": "ghost", "password": "secret"},
        )

    assert response.status_code == 401
    assert len(audit_calls) == 1
    call = audit_calls[0]
    assert call["action_type"] == "auth.user.login"
    assert call["user_id"] is None
    assert call["entity_id"] is None
    assert call["detail"]["success"] is False
    assert call["detail"]["reason"] == "unknown_user"
    assert call["detail"]["username"] == "ghost"


async def test_login_inactive_user_emits_audit(audit_calls) -> None:
    user = _make_user(username="alice", password="secret", is_active=False)
    app.dependency_overrides[get_db] = _override_db(user)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "secret"},
        )

    assert response.status_code == 401
    assert len(audit_calls) == 1
    call = audit_calls[0]
    assert call["detail"]["reason"] == "inactive_user"
    assert call["user_id"] == user.id


async def test_refresh_success_emits_audit_row(audit_calls) -> None:
    user = _make_user(username="alice")
    app.dependency_overrides[get_db] = _override_db(user)
    refresh_token = create_refresh_token(str(user.id))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )

    assert response.status_code == 200
    assert len(audit_calls) == 1
    call = audit_calls[0]
    assert call["action_type"] == "auth.token.refresh"
    assert call["user_id"] == user.id
    assert call["detail"]["success"] is True


async def test_refresh_invalid_token_emits_audit_with_no_user(audit_calls) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "garbage"},
        )

    assert response.status_code == 401
    assert len(audit_calls) == 1
    call = audit_calls[0]
    assert call["action_type"] == "auth.token.refresh"
    assert call["user_id"] is None
    assert call["detail"]["success"] is False
    assert call["detail"]["reason"] == "invalid_token"


async def test_logout_revokes_refresh_and_returns_204(audit_calls, revoked_jtis) -> None:
    user = _make_user(username="alice")
    app.dependency_overrides[get_db] = _override_db(user)
    refresh_token = create_refresh_token(str(user.id))
    decoded = decode_token(refresh_token)
    assert decoded is not None
    jti = decoded["jti"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": refresh_token},
        )

    assert response.status_code == 204
    assert jti in revoked_jtis
    assert len(audit_calls) == 1
    call = audit_calls[0]
    assert call["action_type"] == "auth.user.logout"
    assert call["user_id"] == user.id
    assert call["detail"]["success"] is True


async def test_logout_rejects_missing_refresh_token() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/auth/logout", json={})

    assert response.status_code == 422


async def test_logout_rejects_garbage_refresh_token(audit_calls) -> None:
    app.dependency_overrides[get_db] = _override_db(None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "not.a.real.jwt"},
        )

    assert response.status_code == 401
    assert audit_calls[0]["action_type"] == "auth.user.logout"
    assert audit_calls[0]["detail"]["reason"] == "invalid_token"


async def test_refresh_revokes_old_jti(revoked_jtis) -> None:
    user = _make_user()
    app.dependency_overrides[get_db] = _override_db(user)
    refresh_token = create_refresh_token(str(user.id))
    decoded = decode_token(refresh_token)
    assert decoded is not None
    old_jti = decoded["jti"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )

    assert response.status_code == 200
    assert old_jti in revoked_jtis


async def test_refresh_rejects_revoked_token(revoked_jtis, audit_calls) -> None:
    user = _make_user()
    app.dependency_overrides[get_db] = _override_db(user)
    refresh_token = create_refresh_token(str(user.id))
    decoded = decode_token(refresh_token)
    assert decoded is not None
    revoked_jtis.add(decoded["jti"])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )

    assert response.status_code == 401
    assert audit_calls[0]["detail"]["reason"] == "revoked_token"


async def test_logout_rejects_already_revoked_refresh(revoked_jtis, audit_calls) -> None:
    user = _make_user()
    app.dependency_overrides[get_db] = _override_db(user)
    refresh_token = create_refresh_token(str(user.id))
    decoded = decode_token(refresh_token)
    assert decoded is not None
    revoked_jtis.add(decoded["jti"])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": refresh_token},
        )

    assert response.status_code == 401
    assert audit_calls[0]["detail"]["reason"] == "already_revoked"
