import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import anthropic
import httpx
import pytest
from app.config import settings
from app.models.event_summary import EventSummary
from app.models.notification import Notification
from app.schemas.event_summary import EventSummaryRead
from app.services import event_summary as svc
from app.services.assistant import AssistantError
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def _make_notification(**overrides: Any) -> Notification:
    fields: dict[str, Any] = {
        "id": uuid.uuid4(),
        "udl_id": "udl-1",
        "event_id": None,
        "notso_identifier": None,
        "udl_created_at": NOW,
        "raw": {},
        "created_at": NOW,
        "updated_at": NOW,
    }
    fields.update(overrides)
    return Notification(**fields)


def _make_summary_row(**overrides: Any) -> EventSummary:
    fields: dict[str, Any] = {
        "id": uuid.uuid4(),
        "event_key": "EVT-1",
        "narrative": "It happened.",
        "source_notification_ids": ["a", "b"],
        "latest_notification_id": uuid.uuid4(),
        "publication_count": 2,
        "model": "claude-test",
        "error": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    fields.update(overrides)
    return EventSummary(**fields)


class _FakeClient:
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
    _FakeClient.instances = []
    state: dict[str, Any] = {"outcome": None}

    def factory(**kwargs: Any) -> _FakeClient:
        return _FakeClient(state["outcome"], **kwargs)

    monkeypatch.setattr(svc.anthropic, "AsyncAnthropic", factory)
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")
    monkeypatch.setattr(settings, "anthropic_model", "claude-test")

    def set_outcome(outcome: Any) -> list[_FakeClient]:
        state["outcome"] = outcome
        return _FakeClient.instances

    return set_outcome


def _text_response(*texts: Any) -> SimpleNamespace:
    return SimpleNamespace(content=[SimpleNamespace(text=t) for t in texts])


# compute_event_key


def test_compute_event_key_prefers_event_id_then_notso_then_udl_then_id() -> None:
    n = _make_notification(event_id="E", notso_identifier="N", udl_id="U")
    assert svc.compute_event_key(n) == "E"
    n.event_id = ""
    assert svc.compute_event_key(n) == "N"
    n.notso_identifier = None
    assert svc.compute_event_key(n) == "U"
    n.udl_id = None
    assert svc.compute_event_key(n) == str(n.id)


# _format_publication / _build_user_message


def test_format_publication_full_record() -> None:
    n = _make_notification(
        status="ACTIVE",
        event_type="REENTRY",
        event_class="Reentry",
        subject="Decay of object",
        region="Pacific",
        sat_no=0,
        sat_ids=["1", "2"],
        description="  falling  ",
        effective_from=NOW,
        effective_until=NOW + timedelta(hours=1),
    )
    head, *body = svc._format_publication(2, n).split("\n")
    assert (
        head
        == f"Publication 3 | udl_created={NOW.isoformat()} | status=ACTIVE | event_type=REENTRY"
    )
    assert body == [
        "  event_class: Reentry",
        "  subject: Decay of object",
        "  region: Pacific",
        "  sat_no: 0",
        "  sat_ids: 1, 2",
        "  description: falling",
        f"  effective_from: {NOW.isoformat()}",
        f"  effective_until: {(NOW + timedelta(hours=1)).isoformat()}",
    ]


def test_format_publication_minimal_and_duplicate_subject() -> None:
    n = _make_notification(udl_created_at=None, event_class="Same", subject="Same")
    assert svc._format_publication(0, n) == "Publication 1\n  event_class: Same"


def test_build_user_message_numbers_publications_in_order() -> None:
    a = _make_notification(status="A")
    b = _make_notification(status="B")
    msg = svc._build_user_message([a, b])
    assert msg.startswith("EVENT PUBLICATIONS (oldest to newest):\n\nPublication 1")
    assert msg.index("status=A") < msg.index("Publication 2") < msg.index("status=B")


# _enforce_three_sentences


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("One. Two! Three? Four. Five.", "One. Two! Three?"),
        ("  Only one sentence  ", "Only one sentence"),
        ("A.\nB.\n\nC. D.", "A. B. C."),
    ],
)
def test_enforce_three_sentences(text: str, expected: str) -> None:
    assert svc._enforce_three_sentences(text) == expected


# _call_claude


async def test_call_claude_requires_api_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    with pytest.raises(AssistantError, match="ANTHROPIC_API_KEY is not configured"):
        await svc._call_claude("hi")


async def test_call_claude_joins_text_and_passes_request(fake_claude) -> None:
    clients = fake_claude(_text_response("  First part.", None, "Second part.  "))
    text, model = await svc._call_claude("the prompt")
    assert text == "First part.\nSecond part."
    assert model == "claude-test"
    assert clients[0].kwargs == {"api_key": "sk-test"}
    call = clients[0].messages.create.await_args.kwargs
    assert call["max_tokens"] == 400
    assert call["system"] == svc._SYSTEM_PROMPT
    assert call["messages"] == [{"role": "user", "content": "the prompt"}]


async def test_call_claude_wraps_api_error(fake_claude) -> None:
    fake_claude(anthropic.APIConnectionError(request=httpx.Request("POST", "https://x.invalid")))
    with pytest.raises(AssistantError, match="Anthropic API error"):
        await svc._call_claude("hi")


async def test_call_claude_no_text_blocks(fake_claude) -> None:
    fake_claude(SimpleNamespace(content=[SimpleNamespace(type="tool_use")]))
    with pytest.raises(AssistantError, match="no text blocks"):
        await svc._call_claude("hi")


# generate_event_summary


def _upsert_db(fetched: EventSummary) -> AsyncMock:
    select_result = MagicMock()
    select_result.scalar_one.return_value = fetched
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[MagicMock(), select_result])
    return db


def _compiled_upsert(db: AsyncMock) -> Any:
    stmt = db.execute.await_args_list[0].args[0]
    return stmt.compile(dialect=postgresql.dialect())


async def test_generate_event_summary_rejects_empty_list() -> None:
    db = AsyncMock()
    with pytest.raises(AssistantError, match="empty publication list"):
        await svc.generate_event_summary(db, "EVT-1", [])
    db.execute.assert_not_awaited()


async def test_generate_event_summary_upserts_sorted_capped_narrative(monkeypatch) -> None:
    newest = _make_notification(udl_created_at=NOW)
    oldest = _make_notification(udl_created_at=None, created_at=NOW - timedelta(days=1))
    middle = _make_notification(udl_created_at=NOW - timedelta(hours=1))
    claude = AsyncMock(return_value=("S1. S2. S3. S4.", "claude-x"))
    monkeypatch.setattr(svc, "_call_claude", claude)
    fetched = _make_summary_row()
    db = _upsert_db(fetched)

    result = await svc.generate_event_summary(db, "EVT-1", [newest, oldest, middle])

    assert result is fetched
    assert db.execute.await_count == 2
    compiled = _compiled_upsert(db)
    sql = str(compiled)
    assert "INSERT INTO event_summary" in sql
    assert "ON CONFLICT ON CONSTRAINT uq_event_summary_event_key DO UPDATE" in sql
    params = compiled.params
    assert params["event_key"] == "EVT-1"
    assert params["narrative"] == "S1. S2. S3."
    assert params["source_notification_ids"] == [str(oldest.id), str(middle.id), str(newest.id)]
    assert params["latest_notification_id"] == newest.id
    assert params["publication_count"] == 3
    assert params["model"] == "claude-x"
    assert params["error"] is None
    prompt = claude.await_args.args[0]
    middle_ts = (NOW - timedelta(hours=1)).isoformat()
    assert f"Publication 2 | udl_created={middle_ts}" in prompt
    assert f"Publication 3 | udl_created={NOW.isoformat()}" in prompt


async def test_generate_event_summary_records_failure(monkeypatch, caplog) -> None:
    monkeypatch.setattr(settings, "anthropic_model", "claude-fallback")
    monkeypatch.setattr(svc, "_call_claude", AsyncMock(side_effect=AssistantError("down")))
    pub = _make_notification()
    fetched = _make_summary_row(error="down")
    db = _upsert_db(fetched)

    result = await svc.generate_event_summary(db, "EVT-9", [pub])

    assert result is fetched
    params = _compiled_upsert(db).params
    assert params["narrative"] == "Event summary could not be generated."
    assert params["error"] == "down"
    assert params["model"] == "claude-fallback"
    assert params["publication_count"] == 1
    assert "Event summary failed for EVT-9" in caplog.text


async def test_generate_event_summary_with_fake_client(fake_claude) -> None:
    clients = fake_claude(_text_response("Object decayed. Reentry confirmed."))
    db = _upsert_db(_make_summary_row())

    await svc.generate_event_summary(db, "EVT-1", [_make_notification(status="FINAL")])

    params = _compiled_upsert(db).params
    assert params["narrative"] == "Object decayed. Reentry confirmed."
    assert params["model"] == "claude-test"
    prompt = clients[0].messages.create.await_args.kwargs["messages"][0]["content"]
    assert "status=FINAL" in prompt


# app.schemas.event_summary.EventSummaryRead (not imported by app code)


def test_event_summary_read_validates_from_orm_row() -> None:
    row = _make_summary_row()
    read = EventSummaryRead.model_validate(row)
    assert read.id == row.id
    assert read.event_key == "EVT-1"
    assert read.source_notification_ids == ["a", "b"]
    assert read.latest_notification_id == row.latest_notification_id
    assert read.publication_count == 2
    assert read.error is None


def test_event_summary_read_optional_defaults() -> None:
    read = EventSummaryRead(
        id=uuid.uuid4(),
        event_key="K",
        narrative="n",
        source_notification_ids=[],
        publication_count=1,
        created_at=NOW,
        updated_at=NOW,
    )
    assert read.latest_notification_id is None
    assert read.model is None
    assert read.error is None


def test_event_summary_read_rejects_missing_required_fields() -> None:
    with pytest.raises(ValidationError) as excinfo:
        EventSummaryRead(event_key="K")
    missing = {err["loc"][0] for err in excinfo.value.errors()}
    assert {"id", "narrative", "publication_count", "created_at"} <= missing
