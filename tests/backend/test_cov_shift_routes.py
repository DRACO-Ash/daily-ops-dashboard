import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.v1.routes import shift_log as shift_routes
from app.db.session import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.shift_note import ShiftNote
from app.models.shift_summary import ShiftSummary
from app.models.user import User, UserRole
from httpx import ASGITransport, AsyncClient

SHIFT_DAY = date(2026, 9, 1)


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


def _note(
    raw: str = "raw text",
    polished: Optional[str] = None,
    created_at: Optional[datetime] = None,
) -> ShiftNote:
    ts = created_at or datetime(2026, 9, 1, 9, 15, tzinfo=timezone.utc)
    return ShiftNote(
        id=uuid.uuid4(),
        author_id=None,
        shift_date=SHIFT_DAY,
        raw_text=raw,
        polished_text=polished,
        polish_error=None,
        model=None,
        created_at=ts,
        updated_at=ts,
    )


def _summary(narrative: str = "  Quiet shift.  ") -> ShiftSummary:
    now = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)
    return ShiftSummary(
        id=uuid.uuid4(),
        shift_date=SHIFT_DAY,
        generated_by=None,
        narrative=narrative,
        source_note_ids=[],
        model="m",
        error=None,
        created_at=now,
        updated_at=now,
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


def _rows(values: list[Any]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = values
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

    monkeypatch.setattr(shift_routes, "write_audit", fake_write_audit)
    return calls


@pytest.fixture
def polish_calls(monkeypatch) -> list[str]:
    calls: list[str] = []

    async def fake_polish(raw: str):
        calls.append(raw)
        return f"Polished: {raw}", "claude-test", None

    monkeypatch.setattr(shift_routes, "polish_text", fake_polish)
    return calls


@pytest.fixture
def fixed_today(monkeypatch) -> date:
    monkeypatch.setattr(shift_routes, "_today_utc", lambda: SHIFT_DAY)
    return SHIFT_DAY


# Authentication ------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/shift-log/dates"),
        ("get", "/api/v1/shift-log/notes"),
        ("get", "/api/v1/shift-log/summary"),
        ("get", "/api/v1/shift-log/export"),
        ("post", "/api/v1/shift-log/summary"),
    ],
)
async def test_shift_routes_require_authentication(method: str, path: str) -> None:
    async with _client() as client:
        response = await getattr(client, method)(path)

    assert response.status_code == 401


# Dates ---------------------------------------------------------


async def test_list_dates_merges_counts_with_summary_flags() -> None:
    older = date(2026, 8, 30)
    session = _session(
        [
            _rows(
                [
                    SimpleNamespace(shift_date=SHIFT_DAY, note_count=3),
                    SimpleNamespace(shift_date=older, note_count=1),
                ]
            ),
            _rows([(SHIFT_DAY,)]),
        ]
    )
    _install(session, _make_user(UserRole.ANALYST))

    async with _client() as client:
        response = await client.get("/api/v1/shift-log/dates", params={"days": 7})

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {"shift_date": "2026-09-01", "note_count": 3, "has_summary": True},
            {"shift_date": "2026-08-30", "note_count": 1, "has_summary": False},
        ]
    }
    assert session.execute.await_count == 2


@pytest.mark.parametrize("days", [0, 366])
async def test_list_dates_rejects_out_of_range_days(days: int) -> None:
    session = _session([])
    _install(session)

    async with _client() as client:
        response = await client.get("/api/v1/shift-log/dates", params={"days": days})

    assert response.status_code == 422
    session.execute.assert_not_awaited()


# Notes ---------------------------------------------------------


async def test_list_notes_defaults_to_today(fixed_today: date) -> None:
    notes = [_note("a"), _note("b", polished="B.")]
    _install(_session([_scalars(notes)]))

    async with _client() as client:
        response = await client.get("/api/v1/shift-log/notes")

    assert response.status_code == 200
    body = response.json()
    assert body["shift_date"] == fixed_today.isoformat()
    assert [n["raw_text"] for n in body["items"]] == ["a", "b"]
    assert body["items"][1]["polished_text"] == "B."


async def test_list_notes_honours_explicit_date() -> None:
    _install(_session([_scalars([])]))

    async with _client() as client:
        response = await client.get("/api/v1/shift-log/notes", params={"shift_date": "2026-07-04"})

    assert response.status_code == 200
    assert response.json() == {"items": [], "shift_date": "2026-07-04"}


async def test_list_notes_rejects_bad_date() -> None:
    _install(_session([]))

    async with _client() as client:
        response = await client.get("/api/v1/shift-log/notes", params={"shift_date": "yesterday"})

    assert response.status_code == 422


async def test_create_note_polishes_persists_and_audits(
    polish_calls: list[str], audit_calls: list[dict[str, Any]], fixed_today: date
) -> None:
    session = _session([])
    user = _install(session)

    async with _client() as client:
        response = await client.post(
            "/api/v1/shift-log/notes", json={"raw_text": "  radar is down again  "}
        )

    assert response.status_code == 201
    body = response.json()
    assert body["raw_text"] == "radar is down again"
    assert body["polished_text"] == "Polished: radar is down again"
    assert body["model"] == "claude-test"
    assert body["polish_error"] is None
    assert body["shift_date"] == fixed_today.isoformat()
    assert body["author_id"] == str(user.id)
    assert polish_calls == ["radar is down again"]
    assert len(session.added) == 1
    session.commit.assert_awaited_once()
    assert len(audit_calls) == 1
    audit = audit_calls[0]
    assert audit["action_type"] == "shift_log.note.create"
    assert audit["entity_id"] == body["id"]
    assert audit["user_id"] == user.id
    assert audit["ip_address"] == "127.0.0.1"
    assert audit["detail"] == {"shift_date": "2026-09-01", "had_error": False}


async def test_create_note_keeps_raw_text_when_polish_fails(
    monkeypatch, audit_calls: list[dict[str, Any]]
) -> None:
    async def failing_polish(raw: str):
        return None, "claude-test", "Anthropic API error: boom"

    monkeypatch.setattr(shift_routes, "polish_text", failing_polish)
    session = _session([])
    _install(session)

    async with _client() as client:
        response = await client.post(
            "/api/v1/shift-log/notes",
            json={"raw_text": "raw only", "shift_date": "2026-08-15"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["raw_text"] == "raw only"
    assert body["polished_text"] is None
    assert body["polish_error"] == "Anthropic API error: boom"
    assert body["shift_date"] == "2026-08-15"
    assert audit_calls[0]["detail"] == {"shift_date": "2026-08-15", "had_error": True}


async def test_create_note_rejects_whitespace_only_text(
    polish_calls: list[str], audit_calls: list[dict[str, Any]]
) -> None:
    session = _session([])
    _install(session)

    async with _client() as client:
        response = await client.post("/api/v1/shift-log/notes", json={"raw_text": "   "})

    assert response.status_code == 400
    assert response.json()["detail"] == "Note text cannot be empty."
    assert polish_calls == []
    assert audit_calls == []
    session.add.assert_not_called()


@pytest.mark.parametrize("payload", [{}, {"raw_text": ""}, {"raw_text": "x" * 10_001}])
async def test_create_note_validates_payload(payload: dict[str, Any], polish_calls) -> None:
    _install(_session([]))

    async with _client() as client:
        response = await client.post("/api/v1/shift-log/notes", json=payload)

    assert response.status_code == 422
    assert polish_calls == []


async def test_update_note_replaces_polished_text_and_clears_error(
    audit_calls: list[dict[str, Any]],
) -> None:
    note = _note("raw", polished="old")
    note.polish_error = "earlier failure"
    session = _session([_scalar(note)])
    _install(session)

    async with _client() as client:
        response = await client.patch(
            f"/api/v1/shift-log/notes/{note.id}", json={"polished_text": "  Edited.  "}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["polished_text"] == "Edited."
    assert body["polish_error"] is None
    assert audit_calls[0]["action_type"] == "shift_log.note.update"
    assert audit_calls[0]["entity_id"] == str(note.id)
    session.commit.assert_awaited_once()


async def test_update_note_blank_text_clears_polished_version() -> None:
    note = _note("raw", polished="old")
    _install(_session([_scalar(note)]))

    async with _client() as client:
        response = await client.patch(
            f"/api/v1/shift-log/notes/{note.id}", json={"polished_text": "   "}
        )

    assert response.status_code == 200
    assert response.json()["polished_text"] is None


async def test_update_note_without_field_leaves_note_unchanged() -> None:
    note = _note("raw", polished="keep me")
    note.polish_error = "still here"
    _install(_session([_scalar(note)]))

    async with _client() as client:
        response = await client.patch(f"/api/v1/shift-log/notes/{note.id}", json={})

    assert response.status_code == 200
    assert response.json()["polished_text"] == "keep me"
    assert response.json()["polish_error"] == "still here"


async def test_update_note_missing_returns_404(audit_calls: list[dict[str, Any]]) -> None:
    session = _session([_scalar(None)])
    _install(session)

    async with _client() as client:
        response = await client.patch(
            f"/api/v1/shift-log/notes/{uuid.uuid4()}", json={"polished_text": "x"}
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Note not found"
    assert audit_calls == []
    session.commit.assert_not_awaited()


async def test_update_note_rejects_non_uuid_id() -> None:
    _install(_session([]))

    async with _client() as client:
        response = await client.patch("/api/v1/shift-log/notes/not-a-uuid", json={})

    assert response.status_code == 422


async def test_repolish_note_reruns_polish_on_raw_text(
    polish_calls: list[str], audit_calls: list[dict[str, Any]]
) -> None:
    note = _note("original rant", polished=None)
    note.polish_error = "timeout"
    _install(_session([_scalar(note)]))

    async with _client() as client:
        response = await client.post(f"/api/v1/shift-log/notes/{note.id}/repolish")

    assert response.status_code == 200
    body = response.json()
    assert body["polished_text"] == "Polished: original rant"
    assert body["polish_error"] is None
    assert body["model"] == "claude-test"
    assert polish_calls == ["original rant"]
    assert audit_calls[0]["action_type"] == "shift_log.note.repolish"
    assert audit_calls[0]["detail"] == {"had_error": False}


async def test_repolish_missing_note_returns_404(polish_calls: list[str]) -> None:
    _install(_session([_scalar(None)]))

    async with _client() as client:
        response = await client.post(f"/api/v1/shift-log/notes/{uuid.uuid4()}/repolish")

    assert response.status_code == 404
    assert polish_calls == []


async def test_delete_note_removes_row_and_audits(audit_calls: list[dict[str, Any]]) -> None:
    note = _note()
    session = _session([_scalar(note)])
    user = _install(session)

    async with _client() as client:
        response = await client.delete(f"/api/v1/shift-log/notes/{note.id}")

    assert response.status_code == 204
    assert response.content == b""
    session.delete.assert_awaited_once_with(note)
    session.commit.assert_awaited_once()
    assert audit_calls == [
        {
            "action_type": "shift_log.note.delete",
            "entity_type": "shift_note",
            "entity_id": str(note.id),
            "user_id": user.id,
            "ip_address": "127.0.0.1",
            "detail": {"shift_date": "2026-09-01"},
        }
    ]


async def test_delete_missing_note_returns_404(audit_calls: list[dict[str, Any]]) -> None:
    session = _session([_scalar(None)])
    _install(session)

    async with _client() as client:
        response = await client.delete(f"/api/v1/shift-log/notes/{uuid.uuid4()}")

    assert response.status_code == 404
    session.delete.assert_not_awaited()
    assert audit_calls == []


# Summary -------------------------------------------------------


async def test_get_summary_returns_null_when_absent(fixed_today: date) -> None:
    _install(_session([_scalar(None)]))

    async with _client() as client:
        response = await client.get("/api/v1/shift-log/summary")

    assert response.status_code == 200
    assert response.json() is None


async def test_get_summary_returns_latest_row() -> None:
    summary = _summary("Busy shift.")
    _install(_session([_scalar(summary)]))

    async with _client() as client:
        response = await client.get(
            "/api/v1/shift-log/summary", params={"shift_date": "2026-09-01"}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(summary.id)
    assert body["narrative"] == "Busy shift."


async def test_generate_summary_without_notes_returns_400(
    monkeypatch, fixed_today: date, audit_calls: list[dict[str, Any]]
) -> None:
    summarise = AsyncMock()
    monkeypatch.setattr(shift_routes, "summarise_shift", summarise)
    _install(_session([_scalars([])]))

    async with _client() as client:
        response = await client.post("/api/v1/shift-log/summary")

    assert response.status_code == 400
    assert response.json()["detail"] == "No notes recorded for 2026-09-01."
    summarise.assert_not_awaited()
    assert audit_calls == []


async def test_generate_summary_persists_narrative_and_sources(
    monkeypatch, audit_calls: list[dict[str, Any]]
) -> None:
    notes = [_note("a"), _note("b")]
    summarise = AsyncMock(return_value=("# Narrative", "claude-test", None))
    monkeypatch.setattr(shift_routes, "summarise_shift", summarise)
    session = _session([_scalars(notes)])
    user = _install(session)

    async with _client() as client:
        response = await client.post(
            "/api/v1/shift-log/summary", params={"shift_date": "2026-09-01"}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["narrative"] == "# Narrative"
    assert body["source_note_ids"] == [str(n.id) for n in notes]
    assert body["generated_by"] == str(user.id)
    assert body["error"] is None
    assert summarise.await_args.args[1] == notes
    assert audit_calls[0]["action_type"] == "shift_log.summary.generate"
    assert audit_calls[0]["detail"] == {
        "shift_date": "2026-09-01",
        "note_count": 2,
        "had_error": False,
    }


async def test_generate_summary_records_failure_with_placeholder(
    monkeypatch, audit_calls: list[dict[str, Any]]
) -> None:
    summarise = AsyncMock(return_value=(None, "claude-test", "Anthropic API error: down"))
    monkeypatch.setattr(shift_routes, "summarise_shift", summarise)
    _install(_session([_scalars([_note()])]))

    async with _client() as client:
        response = await client.post(
            "/api/v1/shift-log/summary", params={"shift_date": "2026-09-01"}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["narrative"] == "Summary could not be generated."
    assert body["error"] == "Anthropic API error: down"
    assert audit_calls[0]["detail"]["had_error"] is True


# Export --------------------------------------------------------


async def test_export_markdown_includes_narrative_and_timeline() -> None:
    notes = [
        _note("raw one", polished="Polished one."),
        _note("  raw two  ", created_at=datetime(2026, 9, 1, 10, 0, 5, tzinfo=timezone.utc)),
    ]
    _install(_session([_scalars(notes), _scalar(_summary())]))

    async with _client() as client:
        response = await client.get("/api/v1/shift-log/export", params={"shift_date": "2026-09-01"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert (
        response.headers["content-disposition"] == 'attachment; filename="shift-log-2026-09-01.md"'
    )
    assert response.text == (
        "# Daily Operations Shift Log — 2026-09-01\n\n"
        "## End-of-shift narrative\n\n"
        "Quiet shift.\n\n"
        "## Timeline\n\n"
        "**2026-09-01 09:15:00Z**\n\n"
        "Polished one.\n\n"
        "**2026-09-01 10:00:05Z**\n\n"
        "raw two\n"
    )


async def test_export_markdown_without_summary_or_notes(fixed_today: date) -> None:
    _install(_session([_scalars([]), _scalar(None)]))

    async with _client() as client:
        response = await client.get("/api/v1/shift-log/export")

    assert response.status_code == 200
    assert "End-of-shift narrative" not in response.text
    assert response.text == "# Daily Operations Shift Log — 2026-09-01\n\n## Timeline\n"


async def test_export_html_escapes_operator_text() -> None:
    notes = [_note("<script>alert('x')</script> & more")]
    summary = _summary("Tom & Jerry <b>bold</b>")
    _install(_session([_scalars(notes), _scalar(summary)]))

    async with _client() as client:
        response = await client.get(
            "/api/v1/shift-log/export",
            params={"shift_date": "2026-09-01", "format": "html"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="shift-log-2026-09-01.html"'
    )
    html = response.text
    assert html.startswith("<!doctype html>")
    assert "<title>Shift log 2026-09-01</title>" in html
    assert "<script>" not in html
    assert "&lt;script&gt;alert('x')&lt;/script&gt; &amp; more" in html
    assert '<div class="narrative">Tom &amp; Jerry &lt;b&gt;bold&lt;/b&gt;</div>' in html
    assert '<div class="timeline-ts">2026-09-01 09:15:00Z</div>' in html


async def test_export_html_without_summary_omits_narrative() -> None:
    _install(_session([_scalars([_note(polished="Clean.")]), _scalar(None)]))

    async with _client() as client:
        response = await client.get(
            "/api/v1/shift-log/export",
            params={"shift_date": "2026-09-01", "format": "html"},
        )

    assert response.status_code == 200
    assert "End-of-shift narrative" not in response.text
    assert "<div>Clean.</div>" in response.text


async def test_export_rejects_unknown_format() -> None:
    _install(_session([]))

    async with _client() as client:
        response = await client.get("/api/v1/shift-log/export", params={"format": "pdf"})

    assert response.status_code == 422


def test_builders_render_placeholder_when_timestamp_missing() -> None:
    note = _note("no timestamp")
    note.created_at = None

    markdown = shift_routes._build_markdown(SHIFT_DAY, [note], None)
    html = shift_routes._build_html(SHIFT_DAY, [note], None)

    assert "**?**" in markdown
    assert '<div class="timeline-ts">?</div>' in html


def test_today_utc_matches_current_utc_date() -> None:
    before = datetime.now(timezone.utc).date()
    today = shift_routes._today_utc()
    after = datetime.now(timezone.utc).date()
    assert before <= today <= after
