import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.db.session import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.mattermost_message import MattermostMessage
from app.models.user import User, UserRole
from httpx import ASGITransport, AsyncClient


def _make_user(role: UserRole = UserRole.ANALYST) -> User:
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


def _make_message(post_id: str, channel_id: str = "chan1") -> MattermostMessage:
    now = datetime.now(timezone.utc)
    return MattermostMessage(
        id=uuid.uuid4(),
        mm_post_id=post_id,
        channel_id=channel_id,
        channel_name="Ops",
        user_id="u1",
        user_display_name="alice",
        posted_at=now,
        message=f"message {post_id}",
        post_type=None,
        raw={"id": post_id},
        created_at=now,
        updated_at=now,
    )


def _override_current_user(user: User):
    async def _get():
        return user

    return _get


def _override_db(rows: list[MattermostMessage], total: int, captured: list):
    async def _get_db():
        session = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = total
        items_result = MagicMock()
        items_result.scalars.return_value.all.return_value = rows

        async def _execute(stmt, *args, **kwargs):
            captured.append(stmt)
            return count_result if len(captured) == 1 else items_result

        session.execute = AsyncMock(side_effect=_execute)
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


async def _get(params: dict | None = None):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get("/api/v1/mattermost/messages", params=params)


async def test_messages_requires_authentication() -> None:
    response = await _get()
    assert response.status_code == 401


async def test_messages_default_page_without_filters() -> None:
    captured: list = []
    rows = [_make_message("p1"), _make_message("p2")]
    app.dependency_overrides[get_current_user] = _override_current_user(_make_user())
    app.dependency_overrides[get_db] = _override_db(rows, 2, captured)

    response = await _get()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["limit"] == 100
    assert body["offset"] == 0
    assert [item["mm_post_id"] for item in body["items"]] == ["p1", "p2"]
    assert body["items"][0]["user_display_name"] == "alice"
    assert "raw" not in body["items"][0]
    assert len(captured) == 2
    items_sql = str(captured[1])
    assert "WHERE" not in items_sql
    assert "ORDER BY mattermost_message.posted_at DESC" in items_sql


async def test_messages_applies_all_filters_and_paging() -> None:
    captured: list = []
    app.dependency_overrides[get_current_user] = _override_current_user(_make_user())
    app.dependency_overrides[get_db] = _override_db([_make_message("p9")], 57, captured)

    response = await _get(
        {
            "channel_id": "chan1",
            "user_id": "u1",
            "posted_at_gte": "2025-03-01T00:00:00Z",
            "limit": 10,
            "offset": 20,
        }
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 57
    assert body["limit"] == 10
    assert body["offset"] == 20
    assert len(body["items"]) == 1

    compiled = captured[1].compile()
    sql = str(compiled)
    assert "mattermost_message.channel_id = :channel_id_1" in sql
    assert "mattermost_message.user_id = :user_id_1" in sql
    assert "mattermost_message.posted_at >= :posted_at_1" in sql
    assert compiled.params["channel_id_1"] == "chan1"
    assert compiled.params["user_id_1"] == "u1"
    assert compiled.params["param_1"] == 10
    assert compiled.params["param_2"] == 20
    assert "count" in str(captured[0]).lower()


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 501}, {"offset": -1}])
async def test_messages_rejects_out_of_range_paging(params: dict) -> None:
    captured: list = []
    app.dependency_overrides[get_current_user] = _override_current_user(_make_user())
    app.dependency_overrides[get_db] = _override_db([], 0, captured)

    response = await _get(params)

    assert response.status_code == 422
    assert captured == []
