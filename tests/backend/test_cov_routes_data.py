"""Route coverage for notifications, elsets, maneuvers, audit and health."""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.v1.routes import elsets as elsets_routes
from app.api.v1.routes import notifications as notifications_routes
from app.config import settings
from app.db.session import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.elset import Elset
from app.models.maneuver import Maneuver
from app.models.notification import Notification
from app.models.user import User, UserRole
from app.services.elset_ingest import IngestResult
from app.services.notification_ingest import NotificationIngestResult
from app.services.udl_client import UDLAuthError, UDLClientError
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


def _make_user(role: UserRole = UserRole.ANALYST) -> User:
    return User(
        id=uuid.uuid4(),
        username=f"user-{role.value}",
        email=None,
        password_hash="unused",
        role=role.value,
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def _notification(**overrides: Any) -> Notification:
    fields = {
        "id": uuid.uuid4(),
        "udl_id": "n-1",
        "msg_type": "TACREP_NOTSO",
        "status": "OPEN",
        "sat_no": 44910,
        "sat_ids": ["44910"],
        "raw": {"id": "n-1"},
        "created_at": NOW,
        "updated_at": NOW,
    }
    fields.update(overrides)
    return Notification(**fields)


def _elset() -> Elset:
    return Elset(
        id=uuid.uuid4(),
        udl_id="e-1",
        sat_no=25544,
        epoch=NOW,
        mean_motion=15.5,
        raw={"id": "e-1"},
        created_at=NOW,
        updated_at=NOW,
    )


def _maneuver() -> Maneuver:
    return Maneuver(
        id=uuid.uuid4(),
        udl_id="m-1",
        sat_no=25544,
        mnvr_type="DOCKING",
        delta_v=0.5,
        raw={"id": "m-1"},
        created_at=NOW,
        updated_at=NOW,
    )


def _page_result(total: int, rows: list) -> list[MagicMock]:
    count_result = MagicMock()
    count_result.scalar_one.return_value = total
    items_result = MagicMock()
    items_result.scalars.return_value.all.return_value = rows
    return [count_result, items_result]


def _one_result(row) -> list[MagicMock]:
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    return [result]


class _SessionRecorder:
    """Installs a get_db override and keeps the session for assertions."""

    def __init__(self, results: Optional[list] = None, execute_error=None) -> None:
        self.session = AsyncMock()
        if execute_error is not None:
            self.session.execute = AsyncMock(side_effect=execute_error)
        else:
            self.session.execute = AsyncMock(side_effect=results or [])
        app.dependency_overrides[get_db] = self._get_db

    async def _get_db(self):
        yield self.session

    def sql(self, index: int) -> str:
        stmt = self.session.execute.call_args_list[index].args[0]
        return str(stmt.compile(dialect=postgresql.dialect()))


def _login_as(user: User) -> None:
    async def _get():
        return user

    app.dependency_overrides[get_current_user] = _get


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
def analyst() -> User:
    user = _make_user()
    _login_as(user)
    return user


class _FakeUDLClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None


def _fake_ingest(captured: dict, result=None, error: Optional[Exception] = None):
    async def _ingest(db, **kwargs):
        captured.update(kwargs)
        if error is not None:
            raise error
        return result

    return _ingest


async def _request(method: str, url: str, **kwargs):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, url, **kwargs)


# Notifications ---------------------------------------------------------


async def test_list_notifications_applies_every_filter_and_sort(analyst) -> None:
    rows = [_notification(), _notification(udl_id="n-2", sat_no=None, sat_ids=None)]
    recorder = _SessionRecorder(_page_result(9, rows))

    response = await _request(
        "GET",
        "/api/v1/notifications",
        params={
            "msg_type": "TACREP_NOTSO",
            "event_type": "other",
            "status": "OPEN",
            "sat_no": 44910,
            "effective_from_gte": "2026-01-01T00:00:00Z",
            "effective_from_lte": "2026-12-31T00:00:00Z",
            "created_at_gte": "2026-05-01T00:00:00Z",
            "limit": 2,
            "offset": 4,
            "sort_by": "sat_no",
            "sort_dir": "asc",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 9
    assert body["limit"] == 2
    assert body["offset"] == 4
    assert [item["udl_id"] for item in body["items"]] == ["n-1", "n-2"]
    assert body["items"][0]["sat_ids"] == ["44910"]

    count_sql = recorder.sql(0)
    assert "count(*)" in count_sql
    assert "DISTINCT ON" in count_sql
    for fragment in (
        "notification.msg_type = ",
        "notification.event_type = ",
        "notification.status = ",
        "notification.sat_no = ",
        "notification.effective_from >= ",
        "notification.effective_from <= ",
        "notification.udl_created_at >= ",
    ):
        assert fragment in count_sql
    items_sql = recorder.sql(1)
    assert "ORDER BY anon_1.sat_no ASC NULLS LAST, anon_1.created_at DESC" in items_sql


async def test_list_notifications_default_sort_is_desc(analyst) -> None:
    recorder = _SessionRecorder(_page_result(0, []))

    response = await _request("GET", "/api/v1/notifications")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}
    assert "anon_1.udl_created_at DESC NULLS LAST" in recorder.sql(1)
    assert "WHERE" not in recorder.sql(0)


async def test_list_notifications_rejects_unknown_sort_column(analyst) -> None:
    _SessionRecorder([])
    response = await _request("GET", "/api/v1/notifications", params={"sort_by": "raw"})
    assert response.status_code == 422


async def test_list_notifications_requires_auth() -> None:
    response = await _request("GET", "/api/v1/notifications")
    assert response.status_code == 401


async def test_get_notification_found(analyst) -> None:
    row = _notification()
    _SessionRecorder(_one_result(row))

    response = await _request("GET", f"/api/v1/notifications/{row.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(row.id)
    assert body["raw"] == {"id": "n-1"}


async def test_get_notification_not_found(analyst) -> None:
    _SessionRecorder(_one_result(None))
    response = await _request("GET", f"/api/v1/notifications/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Notification not found"


async def test_notification_ingest_passes_payload_and_user(analyst, monkeypatch) -> None:
    captured: dict = {}
    result = NotificationIngestResult(pulled=4, inserted=2, updated=1, skipped=1)
    monkeypatch.setattr(notifications_routes, "UDLClient", _FakeUDLClient)
    monkeypatch.setattr(
        notifications_routes, "ingest_notifications", _fake_ingest(captured, result)
    )
    _SessionRecorder([])

    response = await _request(
        "POST",
        "/api/v1/notifications/ingest",
        json={"created_at_gte": "2026-06-01T00:00:00Z", "source": "JCO", "max_results": 3},
    )

    assert response.status_code == 200
    assert response.json() == {"pulled": 4, "inserted": 2, "updated": 1, "skipped": 1}
    assert captured["msg_type"] == "TACREP_NOTSO"
    assert captured["source"] == "JCO"
    assert captured["max_results"] == 3
    assert captured["created_at_gte"] == NOW.replace(hour=0)
    assert captured["user_id"] == analyst.id
    assert captured["ip_address"] == "127.0.0.1"
    assert isinstance(captured["client"], _FakeUDLClient)


@pytest.mark.parametrize(
    "error", [UDLAuthError("UDL rejected credentials (401)."), UDLClientError("boom")]
)
async def test_notification_ingest_maps_udl_errors_to_502(analyst, monkeypatch, error) -> None:
    monkeypatch.setattr(notifications_routes, "UDLClient", _FakeUDLClient)
    monkeypatch.setattr(notifications_routes, "ingest_notifications", _fake_ingest({}, error=error))
    _SessionRecorder([])

    response = await _request("POST", "/api/v1/notifications/ingest", json={})

    assert response.status_code == 502
    assert response.json()["detail"] == str(error)


async def test_notification_refresh_runs_pipeline(analyst, monkeypatch) -> None:
    calls: list[str] = []

    async def fake_run():
        calls.append("ran")

    monkeypatch.setattr(notifications_routes, "run_pull_notifications_now", fake_run)

    response = await _request("POST", "/api/v1/notifications/refresh")

    assert response.status_code == 202
    assert response.json() == {"status": "complete"}
    assert calls == ["ran"]


@pytest.mark.parametrize("error", [UDLAuthError("bad creds"), UDLClientError("udl down")])
async def test_notification_refresh_maps_udl_errors(analyst, monkeypatch, error) -> None:
    async def fake_run():
        raise error

    monkeypatch.setattr(notifications_routes, "run_pull_notifications_now", fake_run)

    response = await _request("POST", "/api/v1/notifications/refresh")

    assert response.status_code == 502
    assert response.json()["detail"] == str(error)


# Elsets ----------------------------------------------------------------


async def test_list_elsets_filters_and_sorts(analyst) -> None:
    recorder = _SessionRecorder(_page_result(1, [_elset()]))

    response = await _request(
        "GET",
        "/api/v1/elsets",
        params={
            "sat_no": 25544,
            "epoch_gte": "2026-01-01T00:00:00Z",
            "epoch_lte": "2026-12-31T00:00:00Z",
            "sort_by": "mean_motion",
            "sort_dir": "asc",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["sat_no"] == 25544
    assert body["items"][0]["mean_motion"] == pytest.approx(15.5)
    count_sql = recorder.sql(0)
    assert "elset.sat_no = " in count_sql
    assert "elset.epoch >= " in count_sql
    assert "elset.epoch <= " in count_sql
    assert "ORDER BY elset.mean_motion ASC NULLS LAST" in recorder.sql(1)


async def test_list_elsets_defaults(analyst) -> None:
    recorder = _SessionRecorder(_page_result(0, []))

    response = await _request("GET", "/api/v1/elsets")

    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert "WHERE" not in recorder.sql(0)
    assert "ORDER BY elset.epoch DESC NULLS LAST" in recorder.sql(1)


async def test_get_elset_found_and_missing(analyst) -> None:
    row = _elset()
    _SessionRecorder(_one_result(row))
    found = await _request("GET", f"/api/v1/elsets/{row.id}")
    assert found.status_code == 200
    assert found.json()["raw"] == {"id": "e-1"}

    _SessionRecorder(_one_result(None))
    missing = await _request("GET", f"/api/v1/elsets/{uuid.uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Elset not found"


async def test_elset_ingest_passes_payload(analyst, monkeypatch) -> None:
    captured: dict = {}
    result = IngestResult(pulled=2, inserted=1, updated=1, skipped=0)
    monkeypatch.setattr(elsets_routes, "UDLClient", _FakeUDLClient)
    monkeypatch.setattr(elsets_routes, "ingest_elsets", _fake_ingest(captured, result))
    _SessionRecorder([])

    response = await _request(
        "POST",
        "/api/v1/elsets/ingest",
        json={"epoch_gte": "2026-06-01T12:00:00Z", "sat_no": 25544, "max_results": 9},
    )

    assert response.status_code == 200
    assert response.json() == {"pulled": 2, "inserted": 1, "updated": 1, "skipped": 0}
    assert captured["epoch_gte"] == NOW
    assert captured["sat_no"] == 25544
    assert captured["max_results"] == 9
    assert captured["user_id"] == analyst.id


async def test_elset_ingest_requires_epoch(analyst) -> None:
    _SessionRecorder([])
    response = await _request("POST", "/api/v1/elsets/ingest", json={})
    assert response.status_code == 422


@pytest.mark.parametrize("error", [UDLAuthError("401"), UDLClientError("500")])
async def test_elset_ingest_maps_udl_errors(analyst, monkeypatch, error) -> None:
    monkeypatch.setattr(elsets_routes, "UDLClient", _FakeUDLClient)
    monkeypatch.setattr(elsets_routes, "ingest_elsets", _fake_ingest({}, error=error))
    _SessionRecorder([])

    response = await _request(
        "POST", "/api/v1/elsets/ingest", json={"epoch_gte": "2026-06-01T00:00:00Z"}
    )

    assert response.status_code == 502
    assert response.json()["detail"] == str(error)


# Maneuvers -------------------------------------------------------------


async def test_list_maneuvers_filters_and_sorts(analyst) -> None:
    recorder = _SessionRecorder(_page_result(3, [_maneuver()]))

    response = await _request(
        "GET",
        "/api/v1/maneuvers",
        params={
            "sat_no": 25544,
            "mnvr_type": "DOCKING",
            "event_start_time_gte": "2026-01-01T00:00:00Z",
            "event_start_time_lte": "2026-12-31T00:00:00Z",
            "sort_by": "mnvr_type",
            "sort_dir": "asc",
            "limit": 1,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["limit"] == 1
    assert body["items"][0]["mnvr_type"] == "DOCKING"
    assert body["items"][0]["delta_v"] == pytest.approx(0.5)
    count_sql = recorder.sql(0)
    for fragment in (
        "maneuver.sat_no = ",
        "maneuver.mnvr_type = ",
        "maneuver.event_start_time >= ",
        "maneuver.event_start_time <= ",
    ):
        assert fragment in count_sql
    assert "ORDER BY maneuver.mnvr_type ASC NULLS LAST, maneuver.created_at DESC" in recorder.sql(1)


async def test_list_maneuvers_defaults(analyst) -> None:
    recorder = _SessionRecorder(_page_result(0, []))

    response = await _request("GET", "/api/v1/maneuvers")

    assert response.status_code == 200
    assert "WHERE" not in recorder.sql(0)
    assert "ORDER BY maneuver.event_start_time DESC NULLS LAST" in recorder.sql(1)


async def test_list_maneuvers_rejects_limit_out_of_range(analyst) -> None:
    _SessionRecorder([])
    response = await _request("GET", "/api/v1/maneuvers", params={"limit": 501})
    assert response.status_code == 422


async def test_get_maneuver_found_and_missing(analyst) -> None:
    row = _maneuver()
    _SessionRecorder(_one_result(row))
    found = await _request("GET", f"/api/v1/maneuvers/{row.id}")
    assert found.status_code == 200
    assert found.json()["udl_id"] == "m-1"

    _SessionRecorder(_one_result(None))
    missing = await _request("GET", f"/api/v1/maneuvers/{uuid.uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Maneuver not found"


# Audit -----------------------------------------------------------------


async def test_audit_filters_by_user_and_time_window() -> None:
    _login_as(_make_user(UserRole.ADMIN))
    recorder = _SessionRecorder(_page_result(0, []))
    target = uuid.uuid4()

    response = await _request(
        "GET",
        "/api/v1/audit",
        params={
            "user_id": str(target),
            "since": "2026-01-01T00:00:00Z",
            "until": "2026-02-01T00:00:00Z",
        },
    )

    assert response.status_code == 200
    count_sql = recorder.sql(0)
    assert "audit.audit_log.user_id = " in count_sql
    assert "audit.audit_log.timestamp >= " in count_sql
    assert "audit.audit_log.timestamp <= " in count_sql
    assert "ORDER BY audit.audit_log.timestamp DESC" in recorder.sql(1)


# Health ----------------------------------------------------------------


async def test_health_detailed_ok_with_credentials(monkeypatch) -> None:
    monkeypatch.setattr(settings, "udl_username", "u")
    monkeypatch.setattr(settings, "udl_password", "p")
    recorder = _SessionRecorder([MagicMock()])

    response = await _request("GET", "/api/v1/health/detailed")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.2.0"
    assert body["environment"] == settings.app_env
    assert body["components"] == {"database": "ok", "udl_credentials": "configured"}
    assert "SELECT 1" in str(recorder.session.execute.call_args.args[0])


async def test_health_detailed_degraded_when_db_down(monkeypatch) -> None:
    monkeypatch.setattr(settings, "udl_username", "")
    _SessionRecorder(execute_error=ConnectionRefusedError("db down"))

    response = await _request("GET", "/api/v1/health/detailed")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["components"] == {"database": "down", "udl_credentials": "missing"}
