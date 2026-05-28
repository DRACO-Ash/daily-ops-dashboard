from datetime import datetime, timezone

from app.services.notso_ingest import _map_udl_record


def _sample_record() -> dict:
    return {
        "id": "udl-notso-abc",
        "noticeId": "NOTSO-2026-001",
        "msgType": "OPERATIONAL",
        "effectiveFrom": "2026-05-20T00:00:00.000000Z",
        "effectiveUntil": "2026-05-25T23:59:59.000000Z",
        "subject": "Conjunction warning for ISS",
        "description": "Predicted close approach with debris object.",
        "satNo": 25544,
        "region": "Low Earth Orbit",
        "classificationMarking": "U",
        "dataMode": "REAL",
        "source": "18 SPCS",
        "createdAt": "2026-05-19T12:00:00.000000Z",
        "vendorOnlyField": "preserved-in-raw",
    }


def test_map_udl_record_full_record() -> None:
    mapped = _map_udl_record(_sample_record())
    assert mapped is not None
    assert mapped["udl_id"] == "udl-notso-abc"
    assert mapped["notice_id"] == "NOTSO-2026-001"
    assert mapped["msg_type"] == "OPERATIONAL"
    assert mapped["subject"] == "Conjunction warning for ISS"
    assert mapped["description"] == "Predicted close approach with debris object."
    assert mapped["sat_no"] == 25544
    assert mapped["region"] == "Low Earth Orbit"
    assert mapped["classification_marking"] == "U"
    assert mapped["data_mode"] == "REAL"
    assert mapped["source"] == "18 SPCS"


def test_map_udl_record_parses_datetime_fields() -> None:
    mapped = _map_udl_record(_sample_record())
    assert mapped is not None
    assert mapped["effective_from"] == datetime(2026, 5, 20, 0, 0, 0, tzinfo=timezone.utc)
    assert mapped["effective_until"] == datetime(2026, 5, 25, 23, 59, 59, tzinfo=timezone.utc)
    assert mapped["udl_created_at"] == datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc)


def test_map_udl_record_preserves_raw_payload() -> None:
    record = _sample_record()
    mapped = _map_udl_record(record)
    assert mapped is not None
    assert mapped["raw"] is record
    assert mapped["raw"]["vendorOnlyField"] == "preserved-in-raw"


def test_map_udl_record_returns_none_when_id_missing() -> None:
    record = _sample_record()
    del record["id"]
    assert _map_udl_record(record) is None


def test_map_udl_record_handles_minimal_record() -> None:
    minimal = {"id": "x"}
    mapped = _map_udl_record(minimal)
    assert mapped is not None
    assert mapped["udl_id"] == "x"
    assert "notice_id" not in mapped
    assert mapped["raw"] is minimal


def test_map_udl_record_accepts_text_field_as_description() -> None:
    record = {"id": "y", "text": "Free-form NOTSO text"}
    mapped = _map_udl_record(record)
    assert mapped is not None
    assert mapped["description"] == "Free-form NOTSO text"


def test_map_udl_record_accepts_expiration_time_as_effective_until() -> None:
    record = {
        "id": "z",
        "expirationTime": "2026-06-01T00:00:00.000000Z",
    }
    mapped = _map_udl_record(record)
    assert mapped is not None
    assert mapped["effective_until"] == datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
