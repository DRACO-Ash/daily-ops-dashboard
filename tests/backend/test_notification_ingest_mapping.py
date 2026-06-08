from datetime import datetime, timezone

from app.services.notification_ingest import _map_udl_record


def _real_tacrep_notso_record() -> dict:
    """Trimmed copy of a real UDL TACREP_NOTSO record observed via
    https://unifieddatalibrary.com/udl/notification?msgType=TACREP_NOTSO&source=JCO
    """
    return {
        "createdAt": "2026-06-05T04:55:45.975Z",
        "dataMode": "REAL",
        "msgType": "TACREP_NOTSO",
        "createdBy": "system.erudition",
        "id": "9b3de29a-2999-4967-9a01-509165de615a",
        "source": "JCO",
        "classificationMarking": "U//DS-JCO-NOTIF",
        "origNetwork": "OPS1",
        "msgBody": {
            "Status": "OPEN",
            "Event_Class": "ID: 02f7 / Photometric Change / SJ-20 (44910) / GEO",
            "Template_Name": "NOTSO",
            "NOTSO_Image_Metadata": (
                '[{"caption":"","filename":"SJ-20 / Lightcurve / Northstar","'
                'id":"9daef479-4ec1-44b4-86cb-54142445fa85","url":'
                '"https://s3.us-gov-west-1.amazonaws.com/example.png"}]'
            ),
            "Email_Subject": (
                "NOTSO - ID: 02f7 / Photometric Change / SJ-20 (44910) / GEO - "
                "02f7_05Jun-0448Z - TACREP Notification"
            ),
            "Event_Id": "146f7428-8de1-4e31-b534-0798e56902f7",
            "Event_Type": "other",
            "UDL_Classification": "U//DS-JCO-NOTIF",
            "Remarks": "Photometric change observed during JDAY 154.",
            "Classification": "U",
            "UDL_Data_Mode": "REAL",
            "Event_Description": "JDay 156 at 0430z; photometric change detected on SJ-20.",
            "Company_Name": "Keisuke Abe",
            "previewText": "preview text",
            "SatIds": ["44910"],
            "Orbital_Regime": ["N/A"],
            "Publish_To_UDL": "True",
            "Publish_Date": "2026-06-05T04:48:44.453004Z",
            "NOTSO_Link": "https://mmb.dragonarmy.rocks/notso/661abe18-1c82-4b91-9ce5-2ceeea8b67cb",
            "NOTSO": "02f7_05Jun-0448Z",
        },
    }


def test_map_udl_record_extracts_top_level_envelope() -> None:
    mapped = _map_udl_record(_real_tacrep_notso_record())
    assert mapped is not None
    assert mapped["udl_id"] == "9b3de29a-2999-4967-9a01-509165de615a"
    assert mapped["msg_type"] == "TACREP_NOTSO"
    assert mapped["data_mode"] == "REAL"
    assert mapped["source"] == "JCO"
    assert mapped["classification_marking"] == "U//DS-JCO-NOTIF"
    assert mapped["created_by"] == "system.erudition"
    assert mapped["orig_network"] == "OPS1"
    assert mapped["udl_created_at"] == datetime(2026, 6, 5, 4, 55, 45, 975000, tzinfo=timezone.utc)


def test_map_udl_record_extracts_msg_body_fields() -> None:
    mapped = _map_udl_record(_real_tacrep_notso_record())
    assert mapped is not None
    assert mapped["notso_identifier"] == "02f7_05Jun-0448Z"
    assert mapped["notice_id"] == "02f7_05Jun-0448Z"
    assert mapped["event_class"] == "ID: 02f7 / Photometric Change / SJ-20 (44910) / GEO"
    assert mapped["subject"] == "ID: 02f7 / Photometric Change / SJ-20 (44910) / GEO"
    assert mapped["event_type"] == "other"
    assert mapped["event_id"] == "146f7428-8de1-4e31-b534-0798e56902f7"
    assert mapped["status"] == "OPEN"
    assert mapped["description"] == "JDay 156 at 0430z; photometric change detected on SJ-20."
    assert mapped["company_name"] == "Keisuke Abe"
    assert mapped["notso_link"].startswith("https://mmb.dragonarmy.rocks/")
    assert mapped["publish_date"] == datetime(2026, 6, 5, 4, 48, 44, 453004, tzinfo=timezone.utc)


def test_map_udl_record_handles_sat_ids_single_value() -> None:
    mapped = _map_udl_record(_real_tacrep_notso_record())
    assert mapped is not None
    assert mapped["sat_ids"] == ["44910"]
    assert mapped["sat_no"] == 44910


def test_map_udl_record_handles_sat_ids_multiple() -> None:
    record = _real_tacrep_notso_record()
    record["msgBody"]["SatIds"] = ["94472", "94490"]
    mapped = _map_udl_record(record)
    assert mapped is not None
    assert mapped["sat_ids"] == ["94472", "94490"]
    assert "sat_no" not in mapped


def test_map_udl_record_handles_non_numeric_sat_id() -> None:
    record = _real_tacrep_notso_record()
    record["msgBody"]["SatIds"] = ["UNCAT-001"]
    mapped = _map_udl_record(record)
    assert mapped is not None
    assert mapped["sat_ids"] == ["UNCAT-001"]
    assert "sat_no" not in mapped


def test_map_udl_record_preserves_raw_payload() -> None:
    record = _real_tacrep_notso_record()
    mapped = _map_udl_record(record)
    assert mapped is not None
    assert mapped["raw"] is record
    assert mapped["raw"]["msgBody"]["Template_Name"] == "NOTSO"


def test_map_udl_record_returns_none_when_id_missing() -> None:
    record = _real_tacrep_notso_record()
    del record["id"]
    assert _map_udl_record(record) is None


def test_map_udl_record_handles_missing_msg_body() -> None:
    record = {
        "id": "x",
        "msgType": "OTHER_TYPE",
        "dataMode": "REAL",
    }
    mapped = _map_udl_record(record)
    assert mapped is not None
    assert mapped["udl_id"] == "x"
    assert mapped["msg_type"] == "OTHER_TYPE"
    assert "notso_identifier" not in mapped
    assert "status" not in mapped


def test_map_udl_record_falls_back_to_flat_aliases() -> None:
    record = {
        "id": "legacy",
        "msgType": "OPERATIONAL",
        "noticeId": "OPS-2026-001",
        "subject": "Flat-shaped subject",
        "text": "Flat-shaped description",
        "effectiveFrom": "2026-05-20T00:00:00.000Z",
        "satNo": "25544",
    }
    mapped = _map_udl_record(record)
    assert mapped is not None
    assert mapped["notice_id"] == "OPS-2026-001"
    assert mapped["subject"] == "Flat-shaped subject"
    assert mapped["description"] == "Flat-shaped description"
    assert mapped["effective_from"] == datetime(2026, 5, 20, 0, 0, 0, tzinfo=timezone.utc)
    assert mapped["sat_no"] == 25544
