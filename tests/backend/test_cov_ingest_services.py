"""Coverage for the UDL ingest services (maneuver, elset, notification).

The DB session is an AsyncMock: the first execute returns the existing
udl_id lookup, the second receives the upsert statement, which is compiled
against the Postgres dialect so the mapped rows can be asserted directly.
"""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.services import elset_ingest, maneuver_ingest, notification_ingest
from sqlalchemy.dialects import postgresql

EPOCH = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)


class _FakeUDLClient:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = records
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get_maneuvers(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("maneuvers", kwargs))
        return self.records

    async def get_elsets(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("elsets", kwargs))
        return self.records

    async def get_notifications(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("notifications", kwargs))
        return self.records


def _make_db(existing_ids: list[str]) -> AsyncMock:
    session = AsyncMock()
    existing_result = MagicMock()
    existing_result.all.return_value = [(udl_id,) for udl_id in existing_ids]
    session.execute = AsyncMock(side_effect=[existing_result, MagicMock()])
    session.commit = AsyncMock()
    return session


def _compiled_upsert(session: AsyncMock):
    stmt = session.execute.call_args_list[1].args[0]
    return stmt.compile(dialect=postgresql.dialect())


@pytest.fixture
def audit_calls(monkeypatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_write_audit(db, **kwargs):
        calls.append(kwargs)

    for module in (maneuver_ingest, elset_ingest, notification_ingest):
        monkeypatch.setattr(module, "write_audit", fake_write_audit)
    return calls


# Maneuver mapping ------------------------------------------------------


def test_maneuver_map_full_record() -> None:
    record = {
        "id": "m-1",
        "dataMode": "REAL",
        "source": "18SDS",
        "classificationMarking": "U",
        "createdBy": "sys",
        "origNetwork": "OPS1",
        "origin": "SPACECOM",
        "createdAt": "2026-06-01T01:02:03Z",
        "satNo": "25544",
        "eventStartTime": "2026-06-01T02:00:00Z",
        "eventStopTime": datetime(2026, 6, 1, 3, 0, tzinfo=timezone.utc),
        "mnvrType": "STATIONKEEPING",
        "description": "burn",
        "deltaV": "0.25",
        "thrustMag": 12,
        "thrustDuration": "30.5",
        "propulsionType": "CHEMICAL",
        "maneuverStatus": "CONFIRMED",
        "responsibleNation": "US",
    }
    mapped = maneuver_ingest._map_udl_record(record)
    assert mapped is not None
    assert mapped["udl_id"] == "m-1"
    assert mapped["raw"] is record
    assert mapped["sat_no"] == 25544
    assert mapped["udl_created_at"] == datetime(2026, 6, 1, 1, 2, 3, tzinfo=timezone.utc)
    assert mapped["event_start_time"] == datetime(2026, 6, 1, 2, 0, tzinfo=timezone.utc)
    assert mapped["event_stop_time"] == record["eventStopTime"]
    assert mapped["delta_v"] == pytest.approx(0.25)
    assert mapped["thrust_magnitude"] == pytest.approx(12.0)
    assert mapped["thrust_duration"] == pytest.approx(30.5)
    assert mapped["origin"] == "SPACECOM"
    assert mapped["responsible_nation"] == "US"
    assert mapped["maneuver_status"] == "CONFIRMED"


def test_maneuver_map_drops_blank_and_unparseable_values() -> None:
    record = {
        "id": 77,
        "source": "",
        "description": None,
        "satNo": "not-a-number",
        "createdAt": "garbage-date",
        "eventStartTime": "",
        "eventStopTime": 12345,
        "deltaV": "fast",
        "thrustMag": None,
    }
    mapped = maneuver_ingest._map_udl_record(record)
    assert mapped is not None
    assert mapped["udl_id"] == "77"
    for key in (
        "source",
        "description",
        "sat_no",
        "udl_created_at",
        "event_start_time",
        "event_stop_time",
        "delta_v",
        "thrust_magnitude",
        "thrust_duration",
    ):
        assert key not in mapped


def test_maneuver_map_requires_id() -> None:
    assert maneuver_ingest._map_udl_record({"satNo": 1}) is None
    assert maneuver_ingest._map_udl_record({"id": ""}) is None


# Maneuver ingest -------------------------------------------------------


async def test_ingest_maneuvers_counts_inserts_updates_and_skips(audit_calls) -> None:
    records = [
        {"id": "m-1", "satNo": 1, "deltaV": 0.1},
        {"id": "m-2", "mnvrType": "DOCKING"},
        {"satNo": 3},
    ]
    client = _FakeUDLClient(records)
    db = _make_db(existing_ids=["m-2"])
    user_id = maneuver_ingest.uuid.uuid4()

    result = await maneuver_ingest.ingest_maneuvers(
        db,
        client,
        event_start_time_gte=EPOCH,
        sat_no=1,
        data_mode="REAL",
        max_results=10,
        user_id=user_id,
        ip_address="10.0.0.1",
    )

    assert result == maneuver_ingest.ManeuverIngestResult(
        pulled=3, inserted=1, updated=1, skipped=1
    )
    assert client.calls == [
        (
            "maneuvers",
            {
                "event_start_time_gte": EPOCH,
                "sat_no": 1,
                "data_mode": "REAL",
                "max_results": 10,
            },
        )
    ]
    compiled = _compiled_upsert(db)
    assert "ON CONFLICT ON CONSTRAINT uq_maneuver_udl_id DO UPDATE" in str(compiled)
    # Keys are backfilled with None so both rows share one column set.
    assert compiled.params["udl_id_m0"] == "m-1"
    assert compiled.params["mnvr_type_m0"] is None
    assert compiled.params["mnvr_type_m1"] == "DOCKING"
    assert compiled.params["delta_v_m1"] is None
    db.commit.assert_awaited_once()

    assert len(audit_calls) == 1
    audit = audit_calls[0]
    assert audit["action_type"] == "udl.maneuver.ingest"
    assert audit["entity_type"] == "maneuver_ingest_run"
    assert audit["user_id"] == user_id
    assert audit["ip_address"] == "10.0.0.1"
    assert audit["detail"]["event_start_time_gte"] == EPOCH.isoformat()
    assert audit["detail"]["data_mode"] == "REAL"
    assert audit["detail"]["inserted"] == 1
    assert audit["detail"]["updated"] == 1
    assert audit["detail"]["skipped"] == 1


async def test_ingest_maneuvers_with_no_usable_rows_skips_upsert(audit_calls) -> None:
    client = _FakeUDLClient([{"satNo": 1}])
    db = AsyncMock()

    result = await maneuver_ingest.ingest_maneuvers(db, client, event_start_time_gte=EPOCH)

    assert result == maneuver_ingest.ManeuverIngestResult(
        pulled=1, inserted=0, updated=0, skipped=1
    )
    db.execute.assert_not_awaited()
    db.commit.assert_awaited_once()
    assert audit_calls[0]["detail"]["pulled"] == 1


# Elset mapping ---------------------------------------------------------


def test_elset_map_accepts_alternate_keys_and_datetime_epoch() -> None:
    epoch = datetime(2026, 6, 2, tzinfo=timezone.utc)
    record = {
        "idElset": "e-9",
        "noradCatId": "44910",
        "epochDate": epoch,
        "meanMotion": 1.0027,
        "line1": "1 44910U",
    }
    mapped = elset_ingest._map_udl_record(record)
    assert mapped is not None
    assert mapped["udl_id"] == "e-9"
    assert mapped["sat_no"] == 44910
    assert mapped["epoch"] is epoch
    assert mapped["mean_motion"] == pytest.approx(1.0027)
    assert mapped["line1"] == "1 44910U"
    assert "bstar" not in mapped


def test_elset_map_rejects_unparseable_epoch_string() -> None:
    assert elset_ingest._map_udl_record({"id": "e", "satNo": 1, "epoch": "never"}) is None


def test_elset_map_rejects_unexpected_epoch_type() -> None:
    assert elset_ingest._map_udl_record({"id": "e", "satNo": 1, "epoch": 1717200000}) is None


def test_elset_map_rejects_non_integer_sat_no() -> None:
    record = {"id": "e", "satNo": "abc", "epoch": "2026-06-01T00:00:00Z"}
    assert elset_ingest._map_udl_record(record) is None


# Elset ingest ----------------------------------------------------------


async def test_ingest_elsets_upserts_and_audits(audit_calls) -> None:
    records = [
        {"id": "e-1", "satNo": 25544, "epoch": "2026-06-01T00:00:00Z", "bstar": 0.0001},
        {"id": "e-2", "satNo": 25545, "epoch": "2026-06-01T01:00:00Z"},
        {"id": "e-3", "epoch": "2026-06-01T01:00:00Z"},
    ]
    client = _FakeUDLClient(records)
    db = _make_db(existing_ids=["e-1"])

    result = await elset_ingest.ingest_elsets(
        db, client, epoch_gte=EPOCH, sat_no=25544, max_results=5, ip_address="1.2.3.4"
    )

    assert result == elset_ingest.IngestResult(pulled=3, inserted=1, updated=1, skipped=1)
    assert client.calls[0][1]["epoch_gte"] == EPOCH
    assert client.calls[0][1]["max_results"] == 5
    compiled = _compiled_upsert(db)
    assert "ON CONFLICT ON CONSTRAINT uq_elset_udl_id DO UPDATE" in str(compiled)
    assert compiled.params["bstar_m0"] == pytest.approx(0.0001)
    assert compiled.params["bstar_m1"] is None
    assert compiled.params["epoch_m1"] == datetime(2026, 6, 1, 1, 0, tzinfo=timezone.utc)
    db.commit.assert_awaited_once()

    audit = audit_calls[0]
    assert audit["action_type"] == "udl.elset.ingest"
    assert audit["entity_type"] == "elset_ingest_run"
    assert audit["detail"]["epoch_gte"] == EPOCH.isoformat()
    assert audit["detail"]["sat_no"] == 25544
    assert audit["detail"]["skipped"] == 1


async def test_ingest_elsets_empty_response(audit_calls) -> None:
    client = _FakeUDLClient([])
    db = AsyncMock()

    result = await elset_ingest.ingest_elsets(db, client, epoch_gte=EPOCH)

    assert result == elset_ingest.IngestResult(pulled=0, inserted=0, updated=0, skipped=0)
    db.execute.assert_not_awaited()
    assert audit_calls[0]["detail"]["pulled"] == 0


# Notification mapping edge cases ---------------------------------------


def test_notification_map_flat_shape_fallbacks() -> None:
    record = {
        "id": "n-1",
        "msgType": "OTHER",
        "noticeNumber": "N-42",
        "text": "flat body",
        "region": "GEO",
        "effectiveFrom": "2026-06-01T00:00:00Z",
        "expirationTime": "2026-06-02T00:00:00Z",
        "satNo": "12345",
        "createdAt": "bad-date",
    }
    mapped = notification_ingest._map_udl_record(record)
    assert mapped is not None
    assert mapped["notice_id"] == "N-42"
    assert mapped["description"] == "flat body"
    assert mapped["region"] == "GEO"
    assert mapped["effective_from"] == datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert mapped["effective_until"] == datetime(2026, 6, 2, tzinfo=timezone.utc)
    assert mapped["sat_no"] == 12345
    assert "udl_created_at" not in mapped


def test_notification_map_multi_sat_ids_do_not_set_sat_no() -> None:
    record = {
        "id": "n-2",
        "createdAt": datetime(2026, 6, 1, tzinfo=timezone.utc),
        "msgBody": {"SatIds": ["1", "2"], "NOTSO": "abc"},
    }
    mapped = notification_ingest._map_udl_record(record)
    assert mapped is not None
    assert mapped["sat_ids"] == ["1", "2"]
    assert "sat_no" not in mapped
    assert mapped["udl_created_at"] == record["createdAt"]
    assert mapped["notso_identifier"] == "abc"


def test_notification_map_ignores_non_numeric_single_sat_id() -> None:
    record = {"id": "n-3", "satNo": "x", "msgBody": {"SatIds": ["UNKNOWN"]}}
    mapped = notification_ingest._map_udl_record(record)
    assert mapped is not None
    assert mapped["sat_ids"] == ["UNKNOWN"]
    assert "sat_no" not in mapped


# Notification ingest ---------------------------------------------------


async def test_ingest_notifications_upserts_and_audits(audit_calls) -> None:
    records = [
        {"id": "n-1", "msgType": "TACREP_NOTSO", "msgBody": {"SatIds": ["44910"]}},
        {"id": "n-2", "msgType": "TACREP_NOTSO"},
        {"msgType": "TACREP_NOTSO"},
    ]
    client = _FakeUDLClient(records)
    db = _make_db(existing_ids=["n-1", "n-2"])

    result = await notification_ingest.ingest_notifications(
        db,
        client,
        msg_type="TACREP_NOTSO",
        created_at_gte=EPOCH,
        data_mode="REAL",
        source="JCO",
        max_results=50,
    )

    assert result == notification_ingest.NotificationIngestResult(
        pulled=3, inserted=0, updated=2, skipped=1
    )
    assert client.calls[0][1] == {
        "msg_type": "TACREP_NOTSO",
        "created_at_gte": EPOCH,
        "data_mode": "REAL",
        "source": "JCO",
        "max_results": 50,
    }
    compiled = _compiled_upsert(db)
    assert "ON CONFLICT ON CONSTRAINT uq_notification_udl_id DO UPDATE" in str(compiled)
    assert compiled.params["sat_no_m0"] == 44910
    assert compiled.params["sat_no_m1"] is None
    audit = audit_calls[0]
    assert audit["action_type"] == "udl.notification.ingest"
    assert audit["detail"]["created_at_gte"] == EPOCH.isoformat()
    assert audit["detail"]["source"] == "JCO"
    assert audit["detail"]["updated"] == 2


async def test_ingest_notifications_without_since_records_none(audit_calls) -> None:
    client = _FakeUDLClient([])
    db = AsyncMock()

    result = await notification_ingest.ingest_notifications(db, client)

    assert result.pulled == 0
    db.execute.assert_not_awaited()
    assert audit_calls[0]["detail"]["created_at_gte"] is None
    assert audit_calls[0]["detail"]["msg_type"] is None


def test_notification_map_skips_blank_strings_and_non_list_sat_ids() -> None:
    record = {
        "id": "n-4",
        "source": "",
        "subject": "flat subject",
        "msgBody": {"Status": "", "SatIds": "44910", "Event_Class": None},
    }
    mapped = notification_ingest._map_udl_record(record)
    assert mapped is not None
    assert "source" not in mapped
    assert "status" not in mapped
    assert "sat_ids" not in mapped
    assert "sat_no" not in mapped
    # msgBody left subject empty, so the flat fallback fills it.
    assert mapped["subject"] == "flat subject"
