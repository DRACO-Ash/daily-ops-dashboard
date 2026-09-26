"""Coverage for the audit hash chain, token revocation and notification dedup query."""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.models.revoked_jti import RevokedJti
from app.services import audit, notification_query, token_revocation
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

FIXED_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


class _FixedDatetime:
    @staticmethod
    def now(tz=None):
        return FIXED_NOW


def _audit_db(previous_hash):
    session = AsyncMock()
    lock_result = MagicMock()
    latest_result = MagicMock()
    latest_result.scalar_one_or_none.return_value = previous_hash
    session.execute = AsyncMock(side_effect=[lock_result, latest_result])
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


def _expected_hash(previous_hash, payload: dict) -> str:
    serialised = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(((previous_hash or "") + serialised).encode("utf-8")).hexdigest()


@pytest.fixture
def fixed_clock(monkeypatch) -> None:
    monkeypatch.setattr(audit, "datetime", _FixedDatetime)


# Audit -----------------------------------------------------------------


async def test_write_audit_chains_from_previous_hash(fixed_clock) -> None:
    db = _audit_db("f" * 64)
    user_id = uuid.uuid4()
    detail = {"b": 2, "a": 1}

    entry = await audit.write_audit(
        db,
        action_type="udl.elset.ingest",
        entity_type="elset_ingest_run",
        entity_id="run-1",
        user_id=user_id,
        ip_address="127.0.0.1",
        detail=detail,
    )

    expected = _expected_hash(
        "f" * 64,
        {
            "action_type": "udl.elset.ingest",
            "entity_type": "elset_ingest_run",
            "entity_id": "run-1",
            "user_id": str(user_id),
            "ip_address": "127.0.0.1",
            "detail": detail,
            "timestamp": FIXED_NOW.isoformat(),
        },
    )
    assert entry.previous_hash == "f" * 64
    assert entry.entry_hash == expected
    assert entry.user_id == user_id
    assert json.loads(entry.detail) == detail
    db.add.assert_called_once_with(entry)
    db.flush.assert_awaited_once()

    lock_call = db.execute.call_args_list[0]
    assert "pg_advisory_xact_lock" in str(lock_call.args[0])
    assert lock_call.args[1] == {"k": audit.AUDIT_ADVISORY_LOCK_KEY}


async def test_write_audit_genesis_entry_has_no_previous_hash(fixed_clock) -> None:
    db = _audit_db(None)

    entry = await audit.write_audit(db, action_type="auth.user.login")

    assert entry.previous_hash is None
    assert entry.detail is None
    assert entry.entry_hash == _expected_hash(
        None,
        {
            "action_type": "auth.user.login",
            "entity_type": None,
            "entity_id": None,
            "user_id": None,
            "ip_address": None,
            "detail": None,
            "timestamp": FIXED_NOW.isoformat(),
        },
    )


async def test_write_audit_hash_is_recomputable_from_stored_row() -> None:
    db = _audit_db("e" * 64)

    entry = await audit.write_audit(db, action_type="auth.user.login", detail={"ok": True})

    # Real clock: the stored timestamp must be the one that was hashed.
    assert entry.timestamp is not None
    recomputed = _expected_hash(
        entry.previous_hash,
        {
            "action_type": entry.action_type,
            "entity_type": entry.entity_type,
            "entity_id": entry.entity_id,
            "user_id": None,
            "ip_address": entry.ip_address,
            "detail": json.loads(entry.detail),
            "timestamp": entry.timestamp.isoformat(),
        },
    )
    assert entry.entry_hash == recomputed


async def test_write_audit_second_entry_links_to_first(fixed_clock) -> None:
    first = await audit.write_audit(_audit_db(None), action_type="one")
    second = await audit.write_audit(_audit_db(first.entry_hash), action_type="two")

    assert second.previous_hash == first.entry_hash
    assert second.entry_hash != first.entry_hash


def test_compute_entry_hash_is_order_sensitive() -> None:
    assert audit._compute_entry_hash(None, "x") == hashlib.sha256(b"x").hexdigest()
    assert audit._compute_entry_hash("a", "b") != audit._compute_entry_hash("b", "a")


def test_serialise_payload_is_canonical() -> None:
    out = audit._serialise_payload({"b": 1, "a": FIXED_NOW})
    assert out == '{"a":"2026-06-01 12:00:00+00:00","b":1}'


# Token revocation ------------------------------------------------------


def _revocation_db(found):
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = found
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


async def test_is_revoked_true_and_false() -> None:
    assert await token_revocation.is_revoked(_revocation_db("jti-1"), "jti-1") is True
    assert await token_revocation.is_revoked(_revocation_db(None), "jti-1") is False


async def test_revoke_adds_row_when_not_already_revoked() -> None:
    db = _revocation_db(None)
    user_id = uuid.uuid4()

    await token_revocation.revoke(db, jti="jti-2", user_id=user_id, expires_at=FIXED_NOW)

    db.add.assert_called_once()
    row = db.add.call_args.args[0]
    assert isinstance(row, RevokedJti)
    assert row.jti == "jti-2"
    assert row.user_id == user_id
    assert row.expires_at == FIXED_NOW
    db.flush.assert_awaited_once()


async def test_revoke_is_idempotent() -> None:
    db = _revocation_db("jti-3")

    await token_revocation.revoke(db, jti="jti-3", user_id=None, expires_at=FIXED_NOW)

    db.add.assert_not_called()
    db.flush.assert_not_awaited()


# Notification dedup query ----------------------------------------------


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


def test_deduped_select_uses_distinct_on_group_key() -> None:
    sql = _sql(notification_query.deduped_notifications_select())
    assert "DISTINCT ON (coalesce(notification.event_id, notification.notso_identifier" in sql
    assert "notification.udl_created_at DESC NULLS LAST" in sql
    assert "WHERE" not in sql


def test_deduped_select_applies_conditions() -> None:
    from app.models.notification import Notification

    sql = _sql(notification_query.deduped_notifications_select([Notification.sat_no == 5]))
    assert "WHERE notification.sat_no = " in sql


def test_aliased_deduped_notifications_returns_alias_over_subquery() -> None:
    from app.models.notification import Notification

    alias, subq = notification_query.aliased_deduped_notifications([Notification.status == "OPEN"])
    sql = _sql(subq.select())
    assert "DISTINCT ON" in sql
    assert "notification.status = " in sql
    # The alias exposes mapped columns that resolve against the subquery.
    outer = _sql(select(alias.sat_no))
    assert outer.startswith("SELECT anon_1.sat_no")
    assert "FROM (SELECT DISTINCT ON" in outer
