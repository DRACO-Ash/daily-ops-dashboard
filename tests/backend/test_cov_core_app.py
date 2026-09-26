"""Coverage for app lifespan, DB session factory, auth dependencies and security helpers."""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from app import main as app_main
from app.config import settings
from app.core import security
from app.db import session as db_session
from app.dependencies import get_current_user, require_role
from app.models.user import User, UserRole
from fastapi import HTTPException

# Lifespan --------------------------------------------------------------


def _forever_loop(started: list[str], cancelled: list[str], name: str):
    def _factory():
        async def _run():
            started.append(name)
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.append(name)
                raise

        return _run()

    return _factory


def _patch_loops(monkeypatch, started: list[str], cancelled: list[str]) -> None:
    for name in ("notification_loop", "maneuver_loop", "mattermost_loop"):
        monkeypatch.setattr(app_main, name, _forever_loop(started, cancelled, name))


async def test_lifespan_starts_and_cancels_background_loops(monkeypatch) -> None:
    started: list[str] = []
    cancelled: list[str] = []
    _patch_loops(monkeypatch, started, cancelled)
    monkeypatch.setattr(settings, "background_refresh_enabled", True)

    async with app_main.app.router.lifespan_context(app_main.app):
        await asyncio.sleep(0)
        assert sorted(started) == ["maneuver_loop", "mattermost_loop", "notification_loop"]
        assert cancelled == []

    assert sorted(cancelled) == sorted(started)


async def test_lifespan_disabled_starts_nothing(monkeypatch) -> None:
    started: list[str] = []
    cancelled: list[str] = []
    _patch_loops(monkeypatch, started, cancelled)
    monkeypatch.setattr(settings, "background_refresh_enabled", False)

    async with app_main.app.router.lifespan_context(app_main.app):
        await asyncio.sleep(0)

    assert started == []
    assert cancelled == []


async def test_lifespan_logs_task_that_fails_on_cancel(monkeypatch, caplog) -> None:
    started: list[str] = []
    cancelled: list[str] = []
    _patch_loops(monkeypatch, started, cancelled)

    def _failing_factory():
        async def _run():
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError as exc:
                raise RuntimeError("cleanup failed") from exc

        return _run()

    monkeypatch.setattr(app_main, "mattermost_loop", _failing_factory)
    monkeypatch.setattr(settings, "background_refresh_enabled", True)

    with caplog.at_level(logging.ERROR, logger="app.main"):
        async with app_main.app.router.lifespan_context(app_main.app):
            await asyncio.sleep(0)

    assert sorted(cancelled) == ["maneuver_loop", "notification_loop"]
    assert "Background task exited with error" in caplog.text


# DB session ------------------------------------------------------------


def test_get_engine_uses_database_url(monkeypatch) -> None:
    captured: dict = {}

    def fake_create(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return "engine"

    monkeypatch.setattr(db_session, "create_async_engine", fake_create)

    assert db_session.get_engine() == "engine"
    assert captured["url"] == settings.database_url
    assert captured["url"].startswith("postgresql+asyncpg://")
    assert captured["pool_pre_ping"] is True
    assert captured["echo"] is False


def test_get_session_factory_disables_expire_on_commit(monkeypatch) -> None:
    captured: dict = {}

    def fake_sessionmaker(engine, **kwargs):
        captured["engine"] = engine
        captured.update(kwargs)
        return "factory"

    monkeypatch.setattr(db_session, "get_engine", lambda: "engine")
    monkeypatch.setattr(db_session, "async_sessionmaker", fake_sessionmaker)

    assert db_session.get_session_factory() == "factory"
    assert captured == {"engine": "engine", "expire_on_commit": False}


async def test_get_db_yields_session_and_closes_it(monkeypatch) -> None:
    events: list[str] = []
    fake_session = object()

    class _Ctx:
        async def __aenter__(self):
            events.append("enter")
            return fake_session

        async def __aexit__(self, *exc_info):
            events.append("exit")

    monkeypatch.setattr(db_session, "get_session_factory", lambda: _Ctx)

    gen = db_session.get_db()
    assert await gen.__anext__() is fake_session
    assert events == ["enter"]
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()
    assert events == ["enter", "exit"]


# Dependencies ----------------------------------------------------------


def _user(is_active: bool = True, role: UserRole = UserRole.ANALYST) -> User:
    now = datetime.now(timezone.utc)
    return User(
        id=uuid.uuid4(),
        username="bob",
        email=None,
        password_hash="x",
        role=role.value,
        is_active=is_active,
        created_at=now,
        updated_at=now,
    )


def _db_returning(user):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = user
    db.execute = AsyncMock(return_value=result)
    return db


async def test_get_current_user_returns_active_user() -> None:
    user = _user()
    db = _db_returning(user)
    token = security.create_access_token(str(user.id))

    assert await get_current_user(authorization=f"Bearer {token}", db=db) is user
    db.execute.assert_awaited_once()


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "Basic abc",
        "Bearer not-a-jwt",
        f"Bearer {security.create_refresh_token(str(uuid.uuid4()))}",
        f"Bearer {security.create_access_token('')}",
        f"Bearer {security.create_access_token('not-a-uuid')}",
    ],
)
async def test_get_current_user_rejects_bad_tokens(authorization) -> None:
    db = _db_returning(_user())

    with pytest.raises(HTTPException) as info:
        await get_current_user(authorization=authorization, db=db)

    assert info.value.status_code == 401
    assert info.value.headers == {"WWW-Authenticate": "Bearer"}
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("user", [None, _user(is_active=False)])
async def test_get_current_user_rejects_missing_or_inactive(user) -> None:
    token = security.create_access_token(str(uuid.uuid4()))

    with pytest.raises(HTTPException) as info:
        await get_current_user(authorization=f"Bearer {token}", db=_db_returning(user))

    assert info.value.status_code == 401


async def test_require_role_allows_and_denies() -> None:
    checker = require_role(UserRole.ADMIN)
    admin = _user(role=UserRole.ADMIN)

    assert await checker(current_user=admin) is admin
    with pytest.raises(HTTPException) as info:
        await checker(current_user=_user(role=UserRole.OPERATOR))
    assert info.value.status_code == 403


# Security --------------------------------------------------------------


def test_verify_password_returns_false_for_malformed_hash() -> None:
    assert security.verify_password("secret", "not-a-bcrypt-hash") is False


def test_verify_password_rejects_non_ascii_hash() -> None:
    assert security.verify_password("secret", "café") is False


def test_long_passwords_truncate_at_72_bytes() -> None:
    hashed = security.hash_password("a" * 72)
    assert security.verify_password("a" * 72 + "ignored-suffix", hashed) is True
    assert security.verify_password("a" * 71, hashed) is False


def test_tokens_carry_unique_jti() -> None:
    subject = str(uuid.uuid4())
    first = security.decode_token(security.create_refresh_token(subject))
    second = security.decode_token(security.create_refresh_token(subject))
    assert first is not None
    assert second is not None
    assert first["jti"] != second["jti"]


def test_decode_rejects_token_signed_with_other_key(monkeypatch) -> None:
    token = security.create_access_token(str(uuid.uuid4()))
    monkeypatch.setattr(settings, "app_secret_key", "a-different-secret-key-0123456789abcdef")
    assert security.decode_token(token) is None


def test_decode_token_rejects_token_without_expiry() -> None:
    import jwt as pyjwt
    from app.config import settings
    from app.core.security import decode_token

    token = pyjwt.encode(
        {"sub": "u", "type": "refresh", "jti": "j"},
        settings.app_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    assert decode_token(token) is None
