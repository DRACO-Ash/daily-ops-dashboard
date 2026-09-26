import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import anthropic
import httpx
import pytest
from app.config import settings
from app.models.assistant_evaluation import AssistantEvaluation
from app.models.maneuver import Maneuver
from app.models.mattermost_message import MattermostMessage
from app.models.notification import Notification
from app.models.procedure import Procedure
from app.services import assistant as svc
from app.services.assistant import AssistantError

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def _make_notification(**overrides: Any) -> Notification:
    fields: dict[str, Any] = {
        "id": uuid.uuid4(),
        "udl_id": "udl-1",
        "notso_identifier": "NOTSO-42",
        "msg_type": "TACREP_NOTSO",
        "event_type": "CONJUNCTION",
        "status": "ACTIVE",
        "subject": "Close approach",
        "description": "Two objects closing",
        "publish_date": NOW,
        "udl_created_at": NOW,
        "sat_no": None,
        "sat_ids": None,
        "notso_link": None,
        "raw": {},
        "created_at": NOW,
        "updated_at": NOW,
    }
    fields.update(overrides)
    return Notification(**fields)


def _make_maneuver(**overrides: Any) -> Maneuver:
    fields: dict[str, Any] = {"id": uuid.uuid4(), "sat_no": 25544, "raw": {}}
    fields.update(overrides)
    return Maneuver(**fields)


def _make_message(**overrides: Any) -> MattermostMessage:
    fields: dict[str, Any] = {
        "id": uuid.uuid4(),
        "mm_post_id": "p1",
        "channel_id": "chan-id",
        "channel_name": "ops-floor",
        "user_id": "user-id",
        "user_display_name": "Jo",
        "posted_at": NOW,
        "message": "hello\nteam",
        "raw": {},
    }
    fields.update(overrides)
    return MattermostMessage(**fields)


def _make_procedure(**overrides: Any) -> Procedure:
    fields: dict[str, Any] = {
        "id": uuid.uuid4(),
        "name": "Conjunction SOP",
        "description": "How to handle conjunctions",
        "filename": "sop.txt",
        "content_type": "text/plain",
        "size_bytes": 10,
        "file_hash": "a" * 64,
        "created_at": NOW,
    }
    fields.update(overrides)
    return Procedure(**fields)


def _scalars_result(rows: list[Any]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


def _scalar_result(value: Any) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _response(content: list[Any], stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(content=content, stop_reason=stop_reason)


class _FakeClient:
    """Stand-in for anthropic.AsyncAnthropic recording constructor and call args."""

    instances: list["_FakeClient"] = []

    def __init__(self, outcome: Any, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.messages = SimpleNamespace(create=AsyncMock())
        if isinstance(outcome, BaseException):
            self.messages.create.side_effect = outcome
        else:
            self.messages.create.return_value = outcome
        _FakeClient.instances.append(self)


@pytest.fixture
def fake_claude(monkeypatch):
    """Install a fake AsyncAnthropic; call the returned setter with the outcome."""
    _FakeClient.instances = []
    state: dict[str, Any] = {"outcome": None}

    def factory(**kwargs: Any) -> _FakeClient:
        return _FakeClient(state["outcome"], **kwargs)

    monkeypatch.setattr(svc.anthropic, "AsyncAnthropic", factory)
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")
    monkeypatch.setattr(settings, "anthropic_model", "claude-test")
    monkeypatch.setattr(settings, "anthropic_max_tokens", 1234)

    def set_outcome(outcome: Any) -> list[_FakeClient]:
        state["outcome"] = outcome
        return _FakeClient.instances

    return set_outcome


def _api_error() -> anthropic.APIError:
    return anthropic.APIConnectionError(request=httpx.Request("POST", "https://example.invalid"))


# _format_notification


def test_format_notification_renders_set_fields_and_skips_empty() -> None:
    n = _make_notification(
        sat_no=25544,
        sat_ids=["25544", "43013"],
        notso_link="https://udl/notso/42",
        region="",
    )
    text = svc._format_notification(n)
    lines = text.splitlines()
    assert lines[0] == "NOTIFICATION:"
    assert "  Notice: NOTSO-42" in lines
    assert f"  Published: {NOW.isoformat()}" in lines
    assert "  Satellite: 25544" in lines
    assert "  Satellites: 25544, 43013" in lines
    assert "  Source link: https://udl/notso/42" in lines
    assert not any(line.startswith("  Region") for line in lines)
    assert not any(line.startswith("  Company") for line in lines)


def test_format_notification_includes_sat_no_zero() -> None:
    text = svc._format_notification(_make_notification(sat_no=0))
    assert "  Satellite: 0" in text.splitlines()
    assert "Satellites:" not in text
    assert "Source link" not in text


# _format_maneuver


def test_format_maneuver_full_record_with_description() -> None:
    start = NOW - timedelta(hours=2)
    m = _make_maneuver(
        event_start_time=start,
        event_stop_time=NOW,
        mnvr_type="STATIONKEEPING",
        maneuver_status="COMPLETE",
        delta_v=0.0,
        source="fusion-a",
        description="  burn complete  ",
    )
    text = svc._format_maneuver(m)
    head, desc = text.split("\n")
    assert head == (
        f"  - Sat 25544 | start={start.isoformat()} | stop={NOW.isoformat()} | "
        "type=STATIONKEEPING | status=COMPLETE | deltaV=0.0 | source=fusion-a"
    )
    assert desc == "    burn complete"


def test_format_maneuver_minimal_record_unknown_sat() -> None:
    assert svc._format_maneuver(_make_maneuver(sat_no=None)) == "  - Sat ?"


# _extract_sat_nos


def test_extract_sat_nos_dedupes_preserves_order_and_skips_bad_values() -> None:
    n = _make_notification(sat_no=5, sat_ids=["7", "5", "abc", None, "7", "9"])
    assert svc._extract_sat_nos(n) == [5, 7, 9]


def test_extract_sat_nos_empty_when_no_satellites() -> None:
    assert svc._extract_sat_nos(_make_notification()) == []


# _load_relevant_maneuvers / _load_recent_chat


async def test_load_relevant_maneuvers_skips_query_without_satellites() -> None:
    db = AsyncMock()
    assert await svc._load_relevant_maneuvers(db, _make_notification()) == []
    db.execute.assert_not_awaited()


async def test_load_relevant_maneuvers_queries_by_sat_numbers() -> None:
    rows = [_make_maneuver(), _make_maneuver(sat_no=43013)]
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalars_result(rows))
    result = await svc._load_relevant_maneuvers(db, _make_notification(sat_no=25544))
    assert result == rows
    stmt = db.execute.await_args.args[0]
    compiled = str(stmt)
    assert "maneuver.sat_no IN" in compiled
    assert "LIMIT" in compiled


@pytest.mark.parametrize(("hours", "limit"), [(0, 30), (6, 0), (-1, -1)])
async def test_load_recent_chat_disabled_by_settings(monkeypatch, hours: int, limit: int) -> None:
    monkeypatch.setattr(settings, "mattermost_prompt_window_hours", hours)
    monkeypatch.setattr(settings, "mattermost_max_messages_in_prompt", limit)
    db = AsyncMock()
    assert await svc._load_recent_chat(db) == []
    db.execute.assert_not_awaited()


async def test_load_recent_chat_returns_chronological_order(monkeypatch) -> None:
    monkeypatch.setattr(settings, "mattermost_prompt_window_hours", 6)
    monkeypatch.setattr(settings, "mattermost_max_messages_in_prompt", 2)
    newest = _make_message(mm_post_id="new", posted_at=NOW)
    older = _make_message(mm_post_id="old", posted_at=NOW - timedelta(hours=1))
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalars_result([newest, older]))
    result = await svc._load_recent_chat(db)
    assert [m.mm_post_id for m in result] == ["old", "new"]
    sql = str(db.execute.await_args.args[0])
    assert "LIMIT" in sql
    # Deleted posts stay in the archive but never reach the model.
    assert "mattermost_message.deleted_at IS NULL" in sql


# _format_chat


def test_format_chat_empty_returns_blank() -> None:
    assert svc._format_chat([]) == ""


def test_format_chat_uses_fallbacks_and_truncates(monkeypatch) -> None:
    monkeypatch.setattr(settings, "mattermost_prompt_window_hours", 4)
    named = _make_message()
    anon = _make_message(user_display_name=None, channel_name=None, message="x" * 600)
    lines = svc._format_chat([named, anon]).splitlines()
    assert lines[0] == "TEAM CHAT (last 4 hours):"
    assert lines[1] == "- [2026-09-01 12:00] #ops-floor @Jo: hello team"
    assert lines[2] == "- [2026-09-01 12:00] #chan-id @user-id: " + "x" * 500 + "..."


# _format_procedure


def test_format_procedure_with_truncated_content(monkeypatch) -> None:
    p = _make_procedure()
    calls: list[tuple[Any, ...]] = []

    def fake_preview(pid, filename, content_type):
        calls.append((pid, filename, content_type))
        return "step 1\nstep 2", True

    monkeypatch.setattr(svc, "read_preview", fake_preview)
    lines = svc._format_procedure(p).splitlines()
    assert calls == [(p.id, "sop.txt", "text/plain")]
    assert lines[0] == f"PROCEDURE id={p.id} name='Conjunction SOP'"
    assert lines[1] == "  Description: How to handle conjunctions"
    assert lines[2:] == ["  Content:", "step 1", "step 2", "  ... (truncated)"]


def test_format_procedure_binary_without_description(monkeypatch) -> None:
    monkeypatch.setattr(svc, "read_preview", lambda *_a: (None, False))
    text = svc._format_procedure(_make_procedure(description=None))
    assert "Description" not in text
    assert "binary or unsupported preview type" in text


def test_format_procedure_untruncated_has_no_marker(monkeypatch) -> None:
    monkeypatch.setattr(svc, "read_preview", lambda *_a: ("body", False))
    assert "truncated" not in svc._format_procedure(_make_procedure())


# _build_user_message


def test_build_user_message_with_everything(monkeypatch) -> None:
    monkeypatch.setattr(svc, "read_preview", lambda *_a: ("body", False))
    msg = svc._build_user_message(
        _make_notification(),
        [_make_procedure()],
        [_make_maneuver()],
        [_make_message()],
    )
    assert msg.startswith("NOTIFICATION:")
    assert "RELATED MANEUVERS (same satellite, last 30 days):\n  - Sat 25544" in msg
    assert "TEAM CHAT" in msg
    assert "AVAILABLE PROCEDURES:\n\nPROCEDURE id=" in msg
    assert msg.endswith("Return the JSON object as specified. No text before or after the JSON.")


def test_build_user_message_with_nothing_related() -> None:
    msg = svc._build_user_message(_make_notification(), [], [], [])
    assert "RELATED MANEUVERS: (none for the satellite(s) in this notification)" in msg
    assert "AVAILABLE PROCEDURES: (none uploaded)" in msg
    assert "TEAM CHAT" not in msg


# _extract_json


def test_extract_json_ignores_prose_and_braces_in_strings() -> None:
    text = 'Sure! {"summary": "use {braces}", "next_actions": []} trailing {junk'
    assert svc._extract_json(text) == {"summary": "use {braces}", "next_actions": []}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("no json here", "contained no JSON object"),
        ('{"summary": ', "was not valid JSON"),
    ],
)
def test_extract_json_errors(text: str, message: str) -> None:
    with pytest.raises(AssistantError, match=message):
        svc._extract_json(text)


def test_extract_json_takes_first_object_inside_array() -> None:
    assert svc._extract_json('[{"a": 1}]') == {"a": 1}


# _call_claude


async def test_call_claude_requires_api_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    with pytest.raises(AssistantError, match="ANTHROPIC_API_KEY is not configured"):
        await svc._call_claude("hi")


async def test_call_claude_success_joins_text_blocks(fake_claude) -> None:
    payload = {"summary": "ok", "next_actions": []}
    raw = json.dumps(payload)
    # Blocks are joined with "\n", so split where whitespace is legal JSON.
    split = raw.index(",") + 1
    blocks = [
        SimpleNamespace(text=raw[:split]),
        SimpleNamespace(type="tool_use", text=None),
        SimpleNamespace(text=raw[split:]),
    ]
    clients = fake_claude(_response(blocks))

    structured, model = await svc._call_claude("user text")

    assert structured == payload
    assert model == "claude-test"
    assert clients[0].kwargs == {"api_key": "sk-test"}
    call = clients[0].messages.create.await_args.kwargs
    assert call["model"] == "claude-test"
    assert call["max_tokens"] == 1234
    assert call["system"] == svc._SYSTEM_PROMPT
    assert call["messages"] == [{"role": "user", "content": "user text"}]


async def test_call_claude_wraps_api_error(fake_claude) -> None:
    fake_claude(_api_error())
    with pytest.raises(AssistantError, match="Anthropic API error: Connection error"):
        await svc._call_claude("hi")


async def test_call_claude_rejects_truncated_response(fake_claude) -> None:
    fake_claude(_response([SimpleNamespace(text='{"summary": "par')], stop_reason="max_tokens"))
    with pytest.raises(AssistantError, match="truncated at 1234 tokens"):
        await svc._call_claude("hi")


async def test_call_claude_rejects_no_text_blocks(fake_claude) -> None:
    fake_claude(_response([SimpleNamespace(type="tool_use")]))
    with pytest.raises(AssistantError, match="no text blocks"):
        await svc._call_claude("hi")


# is_persistent_anthropic_failure


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (None, False),
        ("", False),
        ("Anthropic API error: Your credit balance is too low", True),
        ("Rate limit exceeded", True),
        ("AUTHENTICATION failed", True),
        ("invalid API key supplied", True),
        ("Permission denied", True),
        ("Model response contained no JSON object", False),
    ],
)
def test_is_persistent_anthropic_failure(message: Optional[str], expected: bool) -> None:
    assert svc.is_persistent_anthropic_failure(message) is expected


# evaluate_notification


def _eval_db(notification: Optional[Notification], procedures: list[Procedure]) -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock(side_effect=[_scalar_result(notification), _scalars_result(procedures)])
    return db


async def test_evaluate_notification_not_found() -> None:
    db = _eval_db(None, [])
    with pytest.raises(AssistantError, match="Notification not found"):
        await svc.evaluate_notification(db, uuid.uuid4())
    db.add.assert_not_called()
    db.flush.assert_not_awaited()


async def test_evaluate_notification_success_persists_row(monkeypatch) -> None:
    notification = _make_notification()
    procedures = [_make_procedure(), _make_procedure(name="Second")]
    db = _eval_db(notification, procedures)
    monkeypatch.setattr(svc, "_load_relevant_maneuvers", AsyncMock(return_value=[]))
    monkeypatch.setattr(svc, "_load_recent_chat", AsyncMock(return_value=[]))
    monkeypatch.setattr(svc, "read_preview", lambda *_a: ("body", False))
    structured = {"summary": "All quiet", "next_actions": []}
    claude = AsyncMock(return_value=(structured, "claude-x"))
    monkeypatch.setattr(svc, "_call_claude", claude)

    evaluation = await svc.evaluate_notification(db, notification.id)

    assert isinstance(evaluation, AssistantEvaluation)
    assert evaluation.notification_id == notification.id
    assert evaluation.summary == "All quiet"
    assert evaluation.structured == structured
    assert evaluation.procedures_used == [str(p.id) for p in procedures]
    assert evaluation.model == "claude-x"
    assert evaluation.error is None
    db.add.assert_called_once_with(evaluation)
    db.flush.assert_awaited_once()
    prompt = claude.await_args.args[0]
    assert "NOTSO-42" in prompt
    assert prompt.count("PROCEDURE id=") == 2


async def test_evaluate_notification_empty_summary_gets_placeholder(monkeypatch) -> None:
    notification = _make_notification()
    db = _eval_db(notification, [])
    monkeypatch.setattr(svc, "_load_relevant_maneuvers", AsyncMock(return_value=[]))
    monkeypatch.setattr(svc, "_load_recent_chat", AsyncMock(return_value=[]))
    monkeypatch.setattr(svc, "_call_claude", AsyncMock(return_value=({}, "claude-x")))

    evaluation = await svc.evaluate_notification(db, notification.id)

    assert evaluation.summary == "No summary returned."
    assert evaluation.procedures_used == []


async def test_evaluate_notification_null_summary_gets_placeholder(monkeypatch) -> None:
    db = _eval_db(_make_notification(), [])
    monkeypatch.setattr(svc, "_load_relevant_maneuvers", AsyncMock(return_value=[]))
    monkeypatch.setattr(svc, "_load_recent_chat", AsyncMock(return_value=[]))
    claude = AsyncMock(return_value=({"summary": None}, "claude-x"))
    monkeypatch.setattr(svc, "_call_claude", claude)

    evaluation = await svc.evaluate_notification(db, uuid.uuid4())

    assert evaluation.summary == "No summary returned."


async def test_evaluate_notification_records_claude_failure(monkeypatch, caplog) -> None:
    monkeypatch.setattr(settings, "anthropic_model", "claude-fallback")
    notification = _make_notification()
    db = _eval_db(notification, [])
    monkeypatch.setattr(svc, "_load_relevant_maneuvers", AsyncMock(return_value=[]))
    monkeypatch.setattr(svc, "_load_recent_chat", AsyncMock(return_value=[]))
    monkeypatch.setattr(svc, "_call_claude", AsyncMock(side_effect=AssistantError("boom")))

    evaluation = await svc.evaluate_notification(db, notification.id)

    assert evaluation.error == "boom"
    assert evaluation.model == "claude-fallback"
    assert evaluation.summary == "Assistant evaluation could not be generated."
    assert evaluation.structured["next_actions"] == []
    db.add.assert_called_once_with(evaluation)
    assert "Assistant evaluation failed" in caplog.text


async def test_evaluate_notification_end_to_end_with_fake_client(fake_claude) -> None:
    """Loaders and Claude call run for real against mocked DB and SDK."""
    notification = _make_notification(sat_no=25544)
    maneuver = _make_maneuver(mnvr_type="RAISE")
    message = _make_message()
    db = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalar_result(notification),
            _scalars_result([]),
            _scalars_result([maneuver]),
            _scalars_result([message]),
        ]
    )
    clients = fake_claude(_response([SimpleNamespace(text='{"summary": "Burn seen"}')]))

    evaluation = await svc.evaluate_notification(db, notification.id)

    assert evaluation.summary == "Burn seen"
    assert evaluation.error is None
    assert db.execute.await_count == 4
    prompt = clients[0].messages.create.await_args.kwargs["messages"][0]["content"]
    assert "type=RAISE" in prompt
    assert "@Jo: hello team" in prompt


# get_latest_evaluation


async def test_get_latest_evaluation_returns_row() -> None:
    row = AssistantEvaluation(id=uuid.uuid4(), notification_id=uuid.uuid4())
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(row))
    assert await svc.get_latest_evaluation(db, row.notification_id) is row
    compiled = str(db.execute.await_args.args[0])
    assert "ORDER BY assistant_evaluation.evaluated_at DESC" in compiled


async def test_get_latest_evaluation_none() -> None:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(None))
    assert await svc.get_latest_evaluation(db, uuid.uuid4()) is None
