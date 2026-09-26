import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.config import settings
from app.services import background_refresh as br
from app.services.udl_client import UDLAuthError, UDLClientError
from sqlalchemy.dialects import postgresql

T0 = datetime(2025, 3, 1, tzinfo=timezone.utc)


class _Factory:
    """Stand-in for async_sessionmaker: each call yields a fresh AsyncMock session."""

    def __init__(self, results: Optional[list[Any]] = None) -> None:
        self.results = list(results or [])
        self.sessions: list[AsyncMock] = []

    def __call__(self):
        @asynccontextmanager
        async def _cm():
            db = AsyncMock()
            if self.results:
                db.execute = AsyncMock(return_value=self.results.pop(0))
            self.sessions.append(db)
            yield db

        return _cm()


class _FakeUDL:
    entered = 0

    async def __aenter__(self):
        type(self).entered += 1
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


def _install_factory(monkeypatch: pytest.MonkeyPatch, factory: _Factory) -> None:
    monkeypatch.setattr(br, "get_session_factory", lambda: factory)


def _rows_result(ids: list[Any]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = [(i,) for i in ids]
    return result


def _scalars_result(items: list[Any]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result


def _pub(event_id: str, offset_min: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        event_id=event_id,
        notso_identifier=None,
        udl_id=None,
        udl_created_at=T0 + timedelta(minutes=offset_min),
        created_at=T0,
    )


# Notifications / maneuvers pull -------------------------------------


@pytest.fixture
def udl(monkeypatch: pytest.MonkeyPatch) -> type[_FakeUDL]:
    _FakeUDL.entered = 0
    monkeypatch.setattr(br, "UDLClient", _FakeUDL)
    return _FakeUDL


async def test_pull_notifications_passes_window_and_filters(
    monkeypatch: pytest.MonkeyPatch, udl: type[_FakeUDL]
) -> None:
    factory = _Factory()
    _install_factory(monkeypatch, factory)
    monkeypatch.setattr(settings, "background_notification_window_hours", 5)
    ingest = AsyncMock()
    monkeypatch.setattr(br, "ingest_notifications", ingest)

    before = datetime.now(timezone.utc)
    await br._pull_notifications_once()

    ingest.assert_awaited_once()
    args, kwargs = ingest.await_args
    assert args[0] is factory.sessions[0]
    assert isinstance(kwargs["client"], _FakeUDL)
    assert kwargs["msg_type"] == "TACREP_NOTSO"
    assert kwargs["data_mode"] == "REAL"
    assert kwargs["source"] == "JCO"
    after = datetime.now(timezone.utc)
    window = timedelta(hours=5)
    assert before - window <= kwargs["created_at_gte"] <= after - window


@pytest.mark.parametrize(
    ("exc", "level", "text"),
    [
        (UDLAuthError("bad creds"), logging.WARNING, "UDL auth failed"),
        (UDLClientError("503"), logging.WARNING, "Notification ingest failed"),
        (RuntimeError("kaboom"), logging.ERROR, "crashed unexpectedly"),
    ],
)
async def test_pull_notifications_swallows_errors(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    udl: type[_FakeUDL],
    exc: Exception,
    level: int,
    text: str,
) -> None:
    _install_factory(monkeypatch, _Factory())
    monkeypatch.setattr(br, "ingest_notifications", AsyncMock(side_effect=exc))

    with caplog.at_level(logging.WARNING, logger=br.__name__):
        await br._pull_notifications_once()

    matching = [r for r in caplog.records if text in r.getMessage()]
    assert len(matching) == 1
    assert matching[0].levelno == level
    assert not any("ingest complete" in r.getMessage() for r in caplog.records)


async def test_pull_maneuvers_passes_window(
    monkeypatch: pytest.MonkeyPatch, udl: type[_FakeUDL]
) -> None:
    factory = _Factory()
    _install_factory(monkeypatch, factory)
    monkeypatch.setattr(settings, "background_maneuver_window_hours", 48)
    ingest = AsyncMock()
    monkeypatch.setattr(br, "ingest_maneuvers", ingest)

    before = datetime.now(timezone.utc)
    await br._pull_maneuvers_once()

    args, kwargs = ingest.await_args
    assert args[0] is factory.sessions[0]
    assert kwargs["data_mode"] == "REAL"
    after = datetime.now(timezone.utc)
    window = timedelta(hours=48)
    assert before - window <= kwargs["event_start_time_gte"] <= after - window


@pytest.mark.parametrize(
    ("exc", "text"),
    [
        (UDLAuthError("bad creds"), "Maneuver ingest skipped"),
        (UDLClientError("503"), "Maneuver ingest failed"),
        (ValueError("bad row"), "Maneuver ingest crashed"),
    ],
)
async def test_pull_maneuvers_swallows_errors(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    udl: type[_FakeUDL],
    exc: Exception,
    text: str,
) -> None:
    _install_factory(monkeypatch, _Factory())
    monkeypatch.setattr(br, "ingest_maneuvers", AsyncMock(side_effect=exc))

    with caplog.at_level(logging.WARNING, logger=br.__name__):
        await br._pull_maneuvers_once()

    assert any(text in r.getMessage() for r in caplog.records)


# Mattermost pull ---------------------------------------------------


async def test_pull_mattermost_ingests_with_session(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = _Factory()
    _install_factory(monkeypatch, factory)
    ingest = AsyncMock()
    monkeypatch.setattr(br, "ingest_mattermost_messages", ingest)

    await br._pull_mattermost_once()

    ingest.assert_awaited_once_with(factory.sessions[0])


async def test_pull_mattermost_swallows_crash(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _install_factory(monkeypatch, _Factory())
    monkeypatch.setattr(br, "ingest_mattermost_messages", AsyncMock(side_effect=OSError("db")))

    with caplog.at_level(logging.ERROR, logger=br.__name__):
        await br._pull_mattermost_once()

    assert any("Mattermost ingest crashed" in r.getMessage() for r in caplog.records)


# Auto-evaluate -----------------------------------------------------


async def test_auto_evaluate_disabled_does_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "background_auto_evaluate", False)
    get_factory = MagicMock()
    monkeypatch.setattr(br, "get_session_factory", get_factory)

    await br._auto_evaluate_phase()

    get_factory.assert_not_called()


async def test_auto_evaluate_no_pending_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "background_auto_evaluate", True)
    factory = _Factory([_rows_result([])])
    _install_factory(monkeypatch, factory)
    evaluate = AsyncMock()
    monkeypatch.setattr(br, "evaluate_notification", evaluate)

    await br._auto_evaluate_phase()

    evaluate.assert_not_awaited()
    assert len(factory.sessions) == 1


async def test_auto_evaluate_commits_each_and_recovers_from_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "background_auto_evaluate", True)
    monkeypatch.setattr(settings, "background_max_evaluations_per_cycle", 7)
    ids = ["n1", "n2", "n3"]
    factory = _Factory([_rows_result(ids)])
    _install_factory(monkeypatch, factory)
    evaluate = AsyncMock(
        side_effect=[
            SimpleNamespace(error=None),
            RuntimeError("claude exploded"),
            SimpleNamespace(error="HTTP 500 transient"),
        ]
    )
    monkeypatch.setattr(br, "evaluate_notification", evaluate)

    await br._auto_evaluate_phase()

    assert [c.args[1] for c in evaluate.await_args_list] == ids
    stmt = factory.sessions[0].execute.await_args.args[0]
    compiled = stmt.compile(dialect=postgresql.dialect())
    assert "DISTINCT ON" in str(compiled)
    assert 7 in compiled.params.values()
    s1, s2, s3 = factory.sessions[1:]
    s1.commit.assert_awaited_once()
    s2.commit.assert_not_awaited()
    s2.rollback.assert_awaited_once()
    s3.commit.assert_awaited_once()


async def test_auto_evaluate_stops_on_persistent_anthropic_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "background_auto_evaluate", True)
    factory = _Factory([_rows_result(["n1", "n2", "n3"])])
    _install_factory(monkeypatch, factory)
    evaluate = AsyncMock(
        return_value=SimpleNamespace(error="Your credit balance is too low to access the API")
    )
    monkeypatch.setattr(br, "evaluate_notification", evaluate)

    await br._auto_evaluate_phase()

    evaluate.assert_awaited_once()
    assert len(factory.sessions) == 2


# Event summaries ---------------------------------------------------


def test_summary_is_stale_rules() -> None:
    older = _pub("E", 0)
    newer = _pub("E", 10)
    newer.udl_created_at = None
    newer.created_at = T0 + timedelta(hours=1)
    pubs = [older, newer]

    assert br._summary_is_stale(None, pubs) is True
    fresh = SimpleNamespace(latest_notification_id=newer.id, publication_count=2)
    assert br._summary_is_stale(fresh, pubs) is False
    wrong_latest = SimpleNamespace(latest_notification_id=older.id, publication_count=2)
    assert br._summary_is_stale(wrong_latest, pubs) is True
    wrong_count = SimpleNamespace(latest_notification_id=newer.id, publication_count=1)
    assert br._summary_is_stale(wrong_count, pubs) is True


async def test_event_summary_no_publications(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = _Factory([_scalars_result([])])
    _install_factory(monkeypatch, factory)
    generate = AsyncMock()
    monkeypatch.setattr(br, "generate_event_summary", generate)

    await br._event_summary_phase()

    assert len(factory.sessions) == 1
    generate.assert_not_awaited()


async def test_event_summary_all_fresh_skips_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pub = _pub("E1")
    existing = SimpleNamespace(event_key="E1", latest_notification_id=pub.id, publication_count=1)
    factory = _Factory([_scalars_result([pub]), _scalars_result([existing])])
    _install_factory(monkeypatch, factory)
    generate = AsyncMock()
    monkeypatch.setattr(br, "generate_event_summary", generate)

    await br._event_summary_phase()

    generate.assert_not_awaited()
    assert len(factory.sessions) == 2


async def test_event_summary_refreshes_stale_up_to_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "background_max_event_summaries_per_cycle", 2)
    a1, a2, b1, c1 = _pub("A", 0), _pub("A", 5), _pub("B", 1), _pub("C", 2)
    fresh_b = SimpleNamespace(event_key="B", latest_notification_id=b1.id, publication_count=1)
    factory = _Factory([_scalars_result([a1, b1, a2, c1]), _scalars_result([fresh_b])])
    _install_factory(monkeypatch, factory)
    generate = AsyncMock(side_effect=[RuntimeError("summary crashed"), SimpleNamespace(error=None)])
    monkeypatch.setattr(br, "generate_event_summary", generate)

    await br._event_summary_phase()

    calls = [(c.args[1], c.args[2]) for c in generate.await_args_list]
    assert calls == [("A", [a1, a2]), ("C", [c1])]
    crash_session, ok_session = factory.sessions[2:]
    crash_session.rollback.assert_awaited_once()
    crash_session.commit.assert_not_awaited()
    ok_session.commit.assert_awaited_once()


async def test_event_summary_stops_on_persistent_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "background_max_event_summaries_per_cycle", 10)
    pubs = [_pub("A"), _pub("B"), _pub("C")]
    factory = _Factory([_scalars_result(pubs), _scalars_result([])])
    _install_factory(monkeypatch, factory)
    generate = AsyncMock(return_value=SimpleNamespace(error="rate limit exceeded"))
    monkeypatch.setattr(br, "generate_event_summary", generate)

    await br._event_summary_phase()

    generate.assert_awaited_once()


async def test_refresh_event_summary_return_values(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = _Factory()
    generate = AsyncMock(return_value=SimpleNamespace(error="temporary glitch"))
    monkeypatch.setattr(br, "generate_event_summary", generate)

    assert await br._refresh_event_summary(factory, "K", []) is True
    generate.return_value = SimpleNamespace(error="invalid api key")
    assert await br._refresh_event_summary(factory, "K", []) is False
    assert all(s.commit.await_count == 1 for s in factory.sessions)


# Cycle and loops ---------------------------------------------------


def _record_phases(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    order: list[str] = []
    for name in ("_pull_notifications_once", "_auto_evaluate_phase", "_event_summary_phase"):

        async def _phase(label: str = name) -> None:
            order.append(label)

        monkeypatch.setattr(br, name, _phase)
    return order


async def test_run_pull_notifications_now_runs_phases_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = _record_phases(monkeypatch)

    await br.run_pull_notifications_now()

    assert order == ["_pull_notifications_once", "_auto_evaluate_phase", "_event_summary_phase"]


def _bounded_sleep(monkeypatch: pytest.MonkeyPatch, allowed: int) -> list[float]:
    """Patch asyncio.sleep so the loop cancels after `allowed` sleeps."""
    sleeps: list[float] = []

    async def _sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) > allowed:
            raise asyncio.CancelledError

    monkeypatch.setattr(br.asyncio, "sleep", _sleep)
    return sleeps


async def test_make_loop_survives_crash_and_stops_on_cancel(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    sleeps = _bounded_sleep(monkeypatch, allowed=1)
    work = AsyncMock(side_effect=[RuntimeError("cycle boom"), None])

    with caplog.at_level(logging.ERROR, logger=br.__name__):
        with pytest.raises(asyncio.CancelledError):
            await br._make_loop("test", work, 42)()

    assert work.await_count == 2
    assert sleeps == [42, 42]
    assert any("test cycle crashed" in r.getMessage() for r in caplog.records)


async def test_make_loop_propagates_cancel_from_work(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps = _bounded_sleep(monkeypatch, allowed=10)
    work = AsyncMock(side_effect=asyncio.CancelledError)

    with pytest.raises(asyncio.CancelledError):
        await br._make_loop("test", work, 1)()

    work.assert_awaited_once()
    assert sleeps == []


@pytest.mark.parametrize(
    ("loop_name", "phase", "interval_setting"),
    [
        ("notification_loop", "_notification_cycle", "background_notification_interval_seconds"),
        ("maneuver_loop", "_pull_maneuvers_once", "background_maneuver_interval_seconds"),
        ("mattermost_loop", "_pull_mattermost_once", "mattermost_interval_seconds"),
    ],
)
async def test_public_loops_wire_phase_and_interval(
    monkeypatch: pytest.MonkeyPatch, loop_name: str, phase: str, interval_setting: str
) -> None:
    monkeypatch.setattr(settings, interval_setting, 123)
    sleeps = _bounded_sleep(monkeypatch, allowed=1)
    work = AsyncMock()
    monkeypatch.setattr(br, phase, work)

    with pytest.raises(asyncio.CancelledError):
        await getattr(br, loop_name)()

    assert work.await_count == 2
    assert sleeps == [123, 123]
