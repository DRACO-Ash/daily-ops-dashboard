from datetime import datetime, timezone

from app.services.elset_ingest import _map_udl_record


def _sample_record() -> dict:
    return {
        "id": "udl-abc-123",
        "satNo": 25544,
        "epoch": "2025-01-15T12:34:56.789012Z",
        "meanMotion": 15.5,
        "eccentricity": 0.0001234,
        "inclination": 51.6,
        "raan": 100.0,
        "argOfPerigee": 200.0,
        "meanAnomaly": 300.0,
        "revNo": 12345,
        "bstar": 0.00001,
        "meanMotionDot": 0.0,
        "meanMotionDDot": 0.0,
        "semiMajorAxis": 6800.0,
        "period": 92.5,
        "apogee": 420.0,
        "perigee": 410.0,
        "line1": "1 25544U ...",
        "line2": "2 25544 51.6...",
        "classificationMarking": "U",
        "dataMode": "REAL",
        "source": "18 SPCS",
        "extraFieldWeDoNotModel": "preserved-in-raw",
    }


def test_map_udl_record_full_record() -> None:
    mapped = _map_udl_record(_sample_record())
    assert mapped is not None
    assert mapped["udl_id"] == "udl-abc-123"
    assert mapped["sat_no"] == 25544
    assert mapped["mean_motion"] == 15.5
    assert mapped["eccentricity"] == 0.0001234
    assert mapped["inclination"] == 51.6
    assert mapped["raan"] == 100.0
    assert mapped["arg_of_perigee"] == 200.0
    assert mapped["mean_anomaly"] == 300.0
    assert mapped["rev_no"] == 12345
    assert mapped["bstar"] == 0.00001
    assert mapped["mean_motion_dot"] == 0.0
    assert mapped["mean_motion_ddot"] == 0.0
    assert mapped["semi_major_axis"] == 6800.0
    assert mapped["period"] == 92.5
    assert mapped["apogee"] == 420.0
    assert mapped["perigee"] == 410.0
    assert mapped["line1"] == "1 25544U ..."
    assert mapped["line2"] == "2 25544 51.6..."
    assert mapped["classification_marking"] == "U"
    assert mapped["data_mode"] == "REAL"
    assert mapped["source"] == "18 SPCS"


def test_map_udl_record_parses_epoch_with_timezone() -> None:
    mapped = _map_udl_record(_sample_record())
    assert mapped is not None
    assert mapped["epoch"] == datetime(2025, 1, 15, 12, 34, 56, 789012, tzinfo=timezone.utc)


def test_map_udl_record_preserves_full_payload_in_raw() -> None:
    record = _sample_record()
    mapped = _map_udl_record(record)
    assert mapped is not None
    assert mapped["raw"] is record
    assert mapped["raw"]["extraFieldWeDoNotModel"] == "preserved-in-raw"


def test_map_udl_record_returns_none_when_id_missing() -> None:
    record = _sample_record()
    del record["id"]
    assert _map_udl_record(record) is None


def test_map_udl_record_returns_none_when_sat_no_missing() -> None:
    record = _sample_record()
    del record["satNo"]
    assert _map_udl_record(record) is None


def test_map_udl_record_returns_none_when_epoch_missing() -> None:
    record = _sample_record()
    del record["epoch"]
    assert _map_udl_record(record) is None


def test_map_udl_record_handles_minimal_record() -> None:
    minimal = {
        "id": "x",
        "satNo": 1,
        "epoch": "2025-01-01T00:00:00.000000Z",
    }
    mapped = _map_udl_record(minimal)
    assert mapped is not None
    assert mapped["udl_id"] == "x"
    assert mapped["sat_no"] == 1
    assert "mean_motion" not in mapped
