import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
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


async def test_refresh_returns_new_access_token() -> None:
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
