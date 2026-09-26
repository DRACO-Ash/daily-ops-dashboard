import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.v1.routes import event_timers as timer_routes
from app.db.session import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.event_timer import EventTimer
from app.models.user import User, UserRole
from httpx import ASGITransport, AsyncClient

FROZEN_NOW = datetime(2027, 2, 10, 12, 0, tzinfo=timezone.utc)


class _FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz: Optional[Any] = None) -> datetime:
        return FROZEN_NOW if tz is not None else FROZEN_NOW.replace(tzinfo=None)


def _make_user(role: UserRole = UserRole.OPERATOR) -> User:
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


def _timer(
    target: datetime,
    recurrence: str = "none",
    pre_alert_fired_at: Optional[datetime] = None,
    dismissed_at: Optional[datetime] = None,
) -> EventTimer:
    stamp = datetime(2027, 1, 1, tzinfo=timezone.utc)
    return EventTimer(
        id=uuid.uuid4(),
        event_key="launch:soyuz",
        label="Soyuz launch",
        target_time=target,
        pre_alert_minutes=10,
        recurrence=recurrence,
        pre_alert_fired_at=pre_alert_fired_at,
        dismissed_at=dismissed_at,
        dismissed_by=None,
        created_by=None,
        shift_date=None,
        created_at=stamp,
        updated_at=stamp,
    )


def _fill_db_defaults(obj: Any) -> None:
    now = datetime.now(timezone.utc)
    if obj.id is None:
        obj.id = uuid.uuid4()
    if obj.created_at is None:
        obj.created_at = now
    if obj.updated_at is None:
        obj.updated_at = now


def _scalar(value: Any) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _scalars(values: list[Any]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


def _session(results: list[Any]) -> AsyncMock:
    session = AsyncMock()
    session.added = []
    session.execute = AsyncMock(side_effect=results)
    session.add = MagicMock(side_effect=session.added.append)

    async def _flush() -> None:
        for obj in session.added:
            _fill_db_defaults(obj)

    async def _refresh(obj: Any) -> None:
        _fill_db_defaults(obj)

    session.flush = AsyncMock(side_effect=_flush)
    session.refresh = AsyncMock(side_effect=_refresh)
    return session


def _install(session: AsyncMock, user: Optional[User] = None) -> User:
    async def _get_db():
        yield session

    current = user or _make_user()

    async def _get_user():
        return current

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _get_user
    return current


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _sql(session: AsyncMock) -> str:
    stmt = session.execute.await_args.args[0]
    return str(stmt.compile(compile_kwargs={"literal_binds": False}))


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

    monkeypatch.setattr(timer_routes, "write_audit", fake_write_audit)
    return calls


@pytest.fixture
def frozen_now(monkeypatch) -> datetime:
    monkeypatch.setattr(timer_routes, "datetime", _FrozenDateTime)
    return FROZEN_NOW


# Recurrence helpers --------------------------------------------


@pytest.mark.parametrize(
    ("recurrence", "expected"),
    [
        ("daily", datetime(2027, 1, 2, 9, 0, tzinfo=timezone.utc)),
        ("weekly", datetime(2027, 1, 8, 9, 0, tzinfo=timezone.utc)),
        ("monthly", datetime(2027, 2, 1, 9, 0, tzinfo=timezone.utc)),
    ],
)
def test_advance_steps_by_recurrence(recurrence: str, expected: datetime) -> None:
    start = datetime(2027, 1, 1, 9, 0, tzinfo=timezone.utc)
    assert timer_routes._advance(start, recurrence) == expected


def test_advance_rejects_unknown_recurrence() -> None:
    with pytest.raises(ValueError, match="Unknown recurrence"):
        timer_routes._advance(datetime(2026, 1, 1, tzinfo=timezone.utc), "none")


def test_advance_monthly_clamps_to_month_end() -> None:
    jan_31 = datetime(2027, 1, 31, 9, 0, tzinfo=timezone.utc)
    assert timer_routes._advance(jan_31, "monthly") == datetime(
        2027, 2, 28, 9, 0, tzinfo=timezone.utc
    )


def test_next_future_occurrence_skips_missed_cycles(frozen_now: datetime) -> None:
    target = datetime(2027, 2, 7, 9, 0, tzinfo=timezone.utc)
    nxt = timer_routes._next_future_occurrence(target, "daily")
    assert nxt == datetime(2027, 2, 11, 9, 0, tzinfo=timezone.utc)
    assert nxt > frozen_now


def test_next_future_occurrence_future_target_advances_once(frozen_now: datetime) -> None:
    target = datetime(2027, 2, 12, 9, 0, tzinfo=timezone.utc)
    assert timer_routes._next_future_occurrence(target, "weekly") == datetime(
        2027, 2, 19, 9, 0, tzinfo=timezone.utc
    )


# List ----------------------------------------------------------


async def test_timers_require_authentication() -> None:
    async with _client() as client:
        response = await client.get("/api/v1/event-timers")

    assert response.status_code == 401


async def test_list_hides_long_dismissed_by_default() -> None:
    timers = [_timer(FROZEN_NOW), _timer(FROZEN_NOW + timedelta(hours=1))]
    session = _session([_scalars(timers)])
    _install(session, _make_user(UserRole.ANALYST))

    async with _client() as client:
        response = await client.get("/api/v1/event-timers")

    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]
    assert ids == [str(t.id) for t in timers]
    sql = _sql(session)
    assert "event_timer.dismissed_at IS NULL" in sql
    assert "event_timer.dismissed_at >=" in sql
    assert "ORDER BY event_timer.target_time ASC" in sql


async def test_list_include_dismissed_drops_filter() -> None:
    dismissed = _timer(FROZEN_NOW, dismissed_at=FROZEN_NOW - timedelta(days=3))
    session = _session([_scalars([dismissed])])
    _install(session)

    async with _client() as client:
        response = await client.get("/api/v1/event-timers", params={"include_dismissed": "true"})

    assert response.status_code == 200
    assert response.json()["items"][0]["dismissed_at"] is not None
    assert "WHERE" not in _sql(session)


# Create --------------------------------------------------------


async def test_create_timer_assumes_utc_for_naive_time(audit_calls: list[dict[str, Any]]) -> None:
    session = _session([])
    user = _install(session)

    async with _client() as client:
        response = await client.post(
            "/api/v1/event-timers",
            json={
                "label": "  Conjunction TCA  ",
                "target_time": "2027-03-01T14:30:00",
                "event_key": "cdm:123",
                "pre_alert_minutes": 15,
                "recurrence": "daily",
                "shift_date": "2027-03-01",
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["label"] == "Conjunction TCA"
    assert datetime.fromisoformat(body["target_time"]) == datetime(
        2027, 3, 1, 14, 30, tzinfo=timezone.utc
    )
    assert body["pre_alert_minutes"] == 15
    assert body["recurrence"] == "daily"
    assert body["created_by"] == str(user.id)
    assert body["shift_date"] == "2027-03-01"
    assert len(session.added) == 1
    session.commit.assert_awaited_once()
    audit = audit_calls[0]
    assert audit["action_type"] == "event_timer.create"
    assert audit["entity_id"] == body["id"]
    assert audit["user_id"] == user.id
    assert audit["detail"] == {
        "label": "Conjunction TCA",
        "event_key": "cdm:123",
        "target_time": "2027-03-01T14:30:00+00:00",
        "pre_alert_minutes": 15,
        "recurrence": "daily",
    }


async def test_create_timer_keeps_explicit_offset(audit_calls: list[dict[str, Any]]) -> None:
    _install(_session([]))

    async with _client() as client:
        response = await client.post(
            "/api/v1/event-timers",
            json={"label": "Pass", "target_time": "2027-03-01T14:30:00+02:00"},
        )

    assert response.status_code == 201
    body = response.json()
    assert datetime.fromisoformat(body["target_time"]) == datetime(
        2027, 3, 1, 12, 30, tzinfo=timezone.utc
    )
    assert body["pre_alert_minutes"] == 5
    assert body["recurrence"] == "none"
    assert audit_calls[0]["detail"]["target_time"] == "2027-03-01T14:30:00+02:00"


@pytest.mark.parametrize(
    "payload",
    [
        {"target_time": "2027-03-01T14:30:00Z"},
        {"label": "", "target_time": "2027-03-01T14:30:00Z"},
        {"label": "x", "target_time": "not-a-date"},
        {"label": "x", "target_time": "2027-03-01T14:30:00Z", "recurrence": "hourly"},
        {"label": "x", "target_time": "2027-03-01T14:30:00Z", "pre_alert_minutes": -1},
        {"label": "x", "target_time": "2027-03-01T14:30:00Z", "pre_alert_minutes": 721},
    ],
)
async def test_create_timer_validates_payload(
    payload: dict[str, Any], audit_calls: list[dict[str, Any]]
) -> None:
    session = _session([])
    _install(session)

    async with _client() as client:
        response = await client.post("/api/v1/event-timers", json=payload)

    assert response.status_code == 422
    session.add.assert_not_called()
    assert audit_calls == []


# Acknowledge ---------------------------------------------------


async def test_acknowledge_pre_alert_stamps_once(
    frozen_now: datetime, audit_calls: list[dict[str, Any]]
) -> None:
    timer = _timer(FROZEN_NOW + timedelta(minutes=5))
    session = _session([_scalar(timer)])
    user = _install(session)

    async with _client() as client:
        response = await client.post(f"/api/v1/event-timers/{timer.id}/acknowledge-pre-alert")

    assert response.status_code == 200
    assert datetime.fromisoformat(response.json()["pre_alert_fired_at"]) == frozen_now
    session.commit.assert_awaited_once()
    assert audit_calls == [
        {
            "action_type": "event_timer.acknowledge_pre_alert",
            "entity_type": "event_timer",
            "entity_id": str(timer.id),
            "user_id": user.id,
            "ip_address": "127.0.0.1",
            "detail": {"label": "Soyuz launch"},
        }
    ]


async def test_acknowledge_pre_alert_is_idempotent(audit_calls: list[dict[str, Any]]) -> None:
    earlier = datetime(2027, 2, 1, tzinfo=timezone.utc)
    timer = _timer(FROZEN_NOW, pre_alert_fired_at=earlier)
    session = _session([_scalar(timer)])
    _install(session)

    async with _client() as client:
        response = await client.post(f"/api/v1/event-timers/{timer.id}/acknowledge-pre-alert")

    assert response.status_code == 200
    assert datetime.fromisoformat(response.json()["pre_alert_fired_at"]) == earlier
    session.commit.assert_not_awaited()
    assert audit_calls == []


@pytest.mark.parametrize("suffix", ["/acknowledge-pre-alert", "/dismiss"])
async def test_timer_actions_return_404_for_missing_timer(
    suffix: str, audit_calls: list[dict[str, Any]]
) -> None:
    session = _session([_scalar(None)])
    _install(session)

    async with _client() as client:
        response = await client.post(f"/api/v1/event-timers/{uuid.uuid4()}{suffix}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Timer not found"
    session.commit.assert_not_awaited()
    assert audit_calls == []


# Dismiss -------------------------------------------------------


async def test_dismiss_one_shot_timer_marks_dismissed(
    frozen_now: datetime, audit_calls: list[dict[str, Any]]
) -> None:
    timer = _timer(FROZEN_NOW - timedelta(minutes=2))
    session = _session([_scalar(timer)])
    user = _install(session)

    async with _client() as client:
        response = await client.post(f"/api/v1/event-timers/{timer.id}/dismiss")

    assert response.status_code == 200
    body = response.json()
    assert datetime.fromisoformat(body["dismissed_at"]) == frozen_now
    assert body["dismissed_by"] == str(user.id)
    assert datetime.fromisoformat(body["pre_alert_fired_at"]) == frozen_now
    session.commit.assert_awaited_once()
    assert audit_calls[0]["action_type"] == "event_timer.dismiss"
    assert audit_calls[0]["detail"] == {
        "label": "Soyuz launch",
        "target_time": timer.target_time.isoformat(),
    }


async def test_dismiss_one_shot_keeps_existing_pre_alert_stamp(frozen_now: datetime) -> None:
    fired = FROZEN_NOW - timedelta(minutes=12)
    timer = _timer(FROZEN_NOW - timedelta(minutes=2), pre_alert_fired_at=fired)
    _install(_session([_scalar(timer)]))

    async with _client() as client:
        response = await client.post(f"/api/v1/event-timers/{timer.id}/dismiss")

    assert response.status_code == 200
    assert datetime.fromisoformat(response.json()["pre_alert_fired_at"]) == fired


async def test_dismiss_recurring_timer_rolls_forward(
    frozen_now: datetime, audit_calls: list[dict[str, Any]]
) -> None:
    previous = datetime(2027, 2, 8, 9, 0, tzinfo=timezone.utc)
    timer = _timer(previous, recurrence="daily", pre_alert_fired_at=previous)
    session = _session([_scalar(timer)])
    _install(session)

    async with _client() as client:
        response = await client.post(f"/api/v1/event-timers/{timer.id}/dismiss")

    assert response.status_code == 200
    body = response.json()
    assert datetime.fromisoformat(body["target_time"]) == datetime(
        2027, 2, 11, 9, 0, tzinfo=timezone.utc
    )
    assert body["dismissed_at"] is None
    assert body["pre_alert_fired_at"] is None
    session.commit.assert_awaited_once()
    assert audit_calls[0]["action_type"] == "event_timer.roll_forward"
    assert audit_calls[0]["detail"] == {
        "label": "Soyuz launch",
        "recurrence": "daily",
        "previous_target": previous.isoformat(),
        "next_target": "2027-02-11T09:00:00+00:00",
    }


async def test_dismiss_already_dismissed_is_noop(audit_calls: list[dict[str, Any]]) -> None:
    dismissed = datetime(2027, 2, 9, tzinfo=timezone.utc)
    timer = _timer(FROZEN_NOW, dismissed_at=dismissed)
    session = _session([_scalar(timer)])
    _install(session)

    async with _client() as client:
        response = await client.post(f"/api/v1/event-timers/{timer.id}/dismiss")

    assert response.status_code == 200
    assert datetime.fromisoformat(response.json()["dismissed_at"]) == dismissed
    session.commit.assert_not_awaited()
    assert audit_calls == []


# Delete --------------------------------------------------------


async def test_delete_timer_removes_and_audits(audit_calls: list[dict[str, Any]]) -> None:
    timer = _timer(FROZEN_NOW)
    session = _session([_scalar(timer)])
    user = _install(session)

    async with _client() as client:
        response = await client.delete(f"/api/v1/event-timers/{timer.id}")

    assert response.status_code == 204
    session.delete.assert_awaited_once_with(timer)
    session.commit.assert_awaited_once()
    assert audit_calls == [
        {
            "action_type": "event_timer.delete",
            "entity_type": "event_timer",
            "entity_id": str(timer.id),
            "user_id": user.id,
            "ip_address": "127.0.0.1",
            "detail": {"label": "Soyuz launch"},
        }
    ]


async def test_delete_missing_timer_returns_404(audit_calls: list[dict[str, Any]]) -> None:
    session = _session([_scalar(None)])
    _install(session)

    async with _client() as client:
        response = await client.delete(f"/api/v1/event-timers/{uuid.uuid4()}")

    assert response.status_code == 404
    session.delete.assert_not_awaited()
    assert audit_calls == []


async def test_delete_rejects_non_uuid() -> None:
    _install(_session([]))

    async with _client() as client:
        response = await client.delete("/api/v1/event-timers/12345")

    assert response.status_code == 422
