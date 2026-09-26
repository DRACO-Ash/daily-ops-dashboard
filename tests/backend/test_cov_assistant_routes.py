import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.v1.routes import assistant as routes
from app.config import settings
from app.db.session import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.assistant_evaluation import AssistantEvaluation
from app.models.event_summary import EventSummary
from app.models.notification import Notification
from app.models.user import User, UserRole
from app.services.assistant import AssistantError
from httpx import ASGITransport, AsyncClient

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def _make_user(role: UserRole = UserRole.OPERATOR) -> User:
    return User(
        id=uuid.uuid4(),
        username=f"user-{role.value}",
        email=None,
        password_hash="not-used-in-this-test",
        role=role.value,
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def _make_notification(**overrides: Any) -> Notification:
    fields: dict[str, Any] = {
        "id": uuid.uuid4(),
        "udl_id": f"udl-{uuid.uuid4().hex[:6]}",
        "udl_created_at": NOW,
        "raw": {},
        "created_at": NOW,
        "updated_at": NOW,
    }
    fields.update(overrides)
    return Notification(**fields)


def _make_evaluation(
    notification_id: uuid.UUID,
    actions: Optional[list[Any]] = None,
    error: Optional[str] = None,
    evaluated_at: datetime = NOW,
) -> AssistantEvaluation:
    return AssistantEvaluation(
        id=uuid.uuid4(),
        notification_id=notification_id,
        summary="summary",
        structured={"summary": "summary", "next_actions": actions or []},
        procedures_used=[],
        model="claude-test",
        error=error,
        evaluated_at=evaluated_at,
    )


def _make_summary(event_key: str, error: Optional[str] = None) -> EventSummary:
    return EventSummary(
        id=uuid.uuid4(),
        event_key=event_key,
        narrative=f"Narrative for {event_key}.",
        source_notification_ids=[],
        publication_count=3,
        model="claude-test",
        error=error,
        created_at=NOW,
        updated_at=NOW,
    )


def _scalars_result(rows: list[Any]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


def _override_user(user: User):
    async def _get():
        return user

    return _get


def _override_db(session: AsyncMock):
    async def _get_db():
        yield session

    return _get_db


def _session(results: list[Any]) -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.execute = AsyncMock(side_effect=results)
    return session


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


@pytest.fixture
def user() -> User:
    u = _make_user()
    app.dependency_overrides[get_current_user] = _override_user(u)
    return u


@pytest.fixture
def audit_calls(monkeypatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_write_audit(db, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(routes, "write_audit", fake_write_audit)
    return calls


async def _get(path: str, **kwargs: Any):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path, **kwargs)


async def _post(path: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(path)


# _rollup_urgency


def test_rollup_urgency_pending_without_evaluation() -> None:
    assert routes._rollup_urgency(None) == ("pending", None)


def test_rollup_urgency_pending_when_evaluation_errored() -> None:
    ev = _make_evaluation(uuid.uuid4(), actions=[{"urgency": "high", "action": "x"}], error="e")
    assert routes._rollup_urgency(ev) == ("pending", None)


def test_rollup_urgency_none_when_no_actions() -> None:
    ev = _make_evaluation(uuid.uuid4())
    ev.structured = None
    assert routes._rollup_urgency(ev) == ("none", None)


def test_rollup_urgency_picks_highest_and_skips_non_dicts() -> None:
    actions = [
        "not a dict",
        {"urgency": "low", "action": "Log it"},
        {"urgency": "HIGH", "action": "Escalate now"},
        {"urgency": "medium", "action": "Check later"},
    ]
    ev = _make_evaluation(uuid.uuid4(), actions=actions)
    assert routes._rollup_urgency(ev) == ("high", "Escalate now")


def test_rollup_urgency_does_not_borrow_lower_urgency_action_text() -> None:
    actions = [
        {"urgency": "low", "action": "Log it"},
        {"urgency": "high", "action": None},
    ]
    ev = _make_evaluation(uuid.uuid4(), actions=actions)
    assert routes._rollup_urgency(ev) == ("high", None)


def test_rollup_urgency_blank_urgency_defaults_to_low() -> None:
    ev = _make_evaluation(uuid.uuid4(), actions=[{"urgency": "", "action": "Note it"}])
    assert routes._rollup_urgency(ev) == ("low", "Note it")


# GET /assistant/feed


async def test_feed_requires_authentication() -> None:
    response = await _get("/api/v1/assistant/feed")
    assert response.status_code == 401


async def test_feed_empty_window_uses_default_hours(monkeypatch, user) -> None:
    monkeypatch.setattr(settings, "background_notification_window_hours", 48)
    session = _session([_scalars_result([])])
    app.dependency_overrides[get_db] = _override_db(session)

    response = await _get("/api/v1/assistant/feed")

    assert response.status_code == 200
    assert response.json() == {"items": [], "window_hours": 48}
    assert session.execute.await_count == 1


async def test_feed_rejects_out_of_range_params(user) -> None:
    app.dependency_overrides[get_db] = _override_db(_session([]))
    response = await _get("/api/v1/assistant/feed", params={"hours": 0})
    assert response.status_code == 422
    response = await _get("/api/v1/assistant/feed", params={"limit": 501})
    assert response.status_code == 422


async def test_feed_joins_evaluations_and_summaries_and_sorts(user) -> None:
    high = _make_notification(event_id="EVT-1", udl_created_at=NOW - timedelta(hours=5))
    low_new = _make_notification(notso_identifier="NOTSO-2", udl_created_at=NOW)
    low_old = _make_notification(udl_id="udl-3", udl_created_at=NOW - timedelta(hours=1))
    pending = _make_notification(udl_id="udl-4", udl_created_at=None)

    stale = _make_evaluation(high.id, actions=[], evaluated_at=NOW - timedelta(days=1))
    fresh = _make_evaluation(high.id, actions=[{"urgency": "high", "action": "Escalate"}])
    older_after = _make_evaluation(high.id, actions=[], evaluated_at=NOW - timedelta(days=2))
    low_eval_a = _make_evaluation(low_new.id, actions=[{"urgency": "low", "action": "Log"}])
    low_eval_b = _make_evaluation(low_old.id, actions=[{"urgency": "low", "action": "Log"}])

    summaries = [_make_summary("EVT-1"), _make_summary("NOTSO-2", error="failed")]
    session = _session(
        [
            _scalars_result([low_new, low_old, high, pending]),
            _scalars_result([stale, fresh, older_after, low_eval_a, low_eval_b]),
            _scalars_result(summaries),
        ]
    )
    app.dependency_overrides[get_db] = _override_db(session)

    response = await _get("/api/v1/assistant/feed", params={"hours": 24, "limit": 10})

    assert response.status_code == 200
    body = response.json()
    assert body["window_hours"] == 24
    items = body["items"]
    assert [i["notification"]["id"] for i in items] == [
        str(high.id),
        str(low_new.id),
        str(low_old.id),
        str(pending.id),
    ]
    first = items[0]
    assert first["urgency"] == "high"
    assert first["top_action"] == "Escalate"
    assert first["evaluation"]["id"] == str(fresh.id)
    assert first["event_key"] == "EVT-1"
    assert first["event_summary"] == "Narrative for EVT-1."
    assert first["event_publication_count"] == 3
    errored = items[1]
    assert errored["event_key"] == "NOTSO-2"
    assert errored["event_summary"] is None
    assert errored["event_publication_count"] == 3
    last = items[3]
    assert last["urgency"] == "pending"
    assert last["evaluation"] is None
    assert last["event_summary"] is None
    assert last["event_publication_count"] is None
    assert session.execute.await_count == 3


async def test_summaries_by_key_short_circuits_on_empty() -> None:
    db = AsyncMock()
    assert await routes._summaries_by_key(db, []) == {}
    db.execute.assert_not_awaited()


# GET /assistant/evaluation/{id}


async def test_get_evaluation_returns_latest(monkeypatch, user) -> None:
    nid = uuid.uuid4()
    ev = _make_evaluation(nid)
    fake = AsyncMock(return_value=ev)
    monkeypatch.setattr(routes, "get_latest_evaluation", fake)
    app.dependency_overrides[get_db] = _override_db(_session([]))

    response = await _get(f"/api/v1/assistant/evaluation/{nid}")

    assert response.status_code == 200
    assert response.json()["id"] == str(ev.id)
    assert fake.await_args.args[1] == nid


async def test_get_evaluation_404_when_missing(monkeypatch, user) -> None:
    monkeypatch.setattr(routes, "get_latest_evaluation", AsyncMock(return_value=None))
    app.dependency_overrides[get_db] = _override_db(_session([]))

    response = await _get(f"/api/v1/assistant/evaluation/{uuid.uuid4()}")

    assert response.status_code == 404
    assert "POST to /evaluate" in response.json()["detail"]


async def test_get_evaluation_rejects_bad_uuid(user) -> None:
    app.dependency_overrides[get_db] = _override_db(_session([]))
    response = await _get("/api/v1/assistant/evaluation/not-a-uuid")
    assert response.status_code == 422


# POST /assistant/evaluate/{id}


async def test_evaluate_success_writes_audit_and_commits(monkeypatch, user, audit_calls) -> None:
    nid = uuid.uuid4()
    ev = _make_evaluation(nid)
    ev.procedures_used = ["p1", "p2"]
    monkeypatch.setattr(routes, "evaluate_notification", AsyncMock(return_value=ev))
    session = _session([])
    app.dependency_overrides[get_db] = _override_db(session)

    response = await _post(f"/api/v1/assistant/evaluate/{nid}")

    assert response.status_code == 200
    assert response.json()["id"] == str(ev.id)
    assert audit_calls == [
        {
            "action_type": "assistant.evaluate",
            "entity_type": "notification",
            "entity_id": str(nid),
            "user_id": user.id,
            "ip_address": "127.0.0.1",
            "detail": {
                "evaluation_id": str(ev.id),
                "model": "claude-test",
                "procedures_used": ["p1", "p2"],
                "had_error": False,
            },
        }
    ]
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(ev)


async def test_evaluate_audit_flags_error_evaluation(monkeypatch, user, audit_calls) -> None:
    ev = _make_evaluation(uuid.uuid4(), error="Anthropic API error: down")
    monkeypatch.setattr(routes, "evaluate_notification", AsyncMock(return_value=ev))
    app.dependency_overrides[get_db] = _override_db(_session([]))

    response = await _post(f"/api/v1/assistant/evaluate/{ev.notification_id}")

    assert response.status_code == 200
    assert response.json()["error"] == "Anthropic API error: down"
    assert audit_calls[0]["detail"]["had_error"] is True


@pytest.mark.parametrize(
    ("message", "status_code"),
    [("Notification not found", 404), ("ANTHROPIC_API_KEY is not configured", 502)],
)
async def test_evaluate_maps_assistant_errors(
    monkeypatch, user, audit_calls, message: str, status_code: int
) -> None:
    monkeypatch.setattr(
        routes, "evaluate_notification", AsyncMock(side_effect=AssistantError(message))
    )
    session = _session([])
    app.dependency_overrides[get_db] = _override_db(session)

    response = await _post(f"/api/v1/assistant/evaluate/{uuid.uuid4()}")

    assert response.status_code == status_code
    assert response.json()["detail"] == message
    assert audit_calls == []
    session.commit.assert_not_awaited()


async def test_evaluate_requires_authentication() -> None:
    response = await _post(f"/api/v1/assistant/evaluate/{uuid.uuid4()}")
    assert response.status_code == 401
