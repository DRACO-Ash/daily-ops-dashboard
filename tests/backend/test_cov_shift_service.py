import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import anthropic
import httpx
import pytest
from app.config import settings
from app.models.shift_note import ShiftNote
from app.services import shift_log as shift_service


def _note(raw: str, polished: str | None = None, created_at: datetime | None = None) -> ShiftNote:
    return ShiftNote(
        id=uuid.uuid4(),
        shift_date=date(2026, 9, 1),
        raw_text=raw,
        polished_text=polished,
        created_at=created_at,
    )


class _FakeMessages:
    def __init__(self, outcome: Any, calls: list[dict[str, Any]]) -> None:
        self._outcome = outcome
        self._calls = calls

    async def create(self, **kwargs: Any) -> Any:
        self._calls.append(kwargs)
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return self._outcome


def _install_fake_client(monkeypatch, outcome: Any) -> SimpleNamespace:
    calls: list[dict[str, Any]] = []
    keys: list[str] = []

    def factory(api_key: str) -> Any:
        keys.append(api_key)
        return SimpleNamespace(messages=_FakeMessages(outcome, calls))

    monkeypatch.setattr(shift_service.anthropic, "AsyncAnthropic", factory)
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test-key")
    monkeypatch.setattr(settings, "anthropic_model", "claude-test-model")
    monkeypatch.setattr(settings, "anthropic_max_tokens", 321)
    return SimpleNamespace(calls=calls, keys=keys)


def _response(*texts: Any) -> SimpleNamespace:
    return SimpleNamespace(content=[SimpleNamespace(text=t) for t in texts])


def _api_error() -> anthropic.APIError:
    request = httpx.Request("POST", "https://api.anthropic.invalid/v1/messages")
    return anthropic.APIError("upstream exploded", request, body=None)


async def test_polish_text_returns_polished_text_and_model(monkeypatch) -> None:
    calls = _install_fake_client(monkeypatch, _response("  Tidy paragraph.  "))

    polished, model, error = await shift_service.polish_text("   ugh the radar died again   ")

    assert (polished, model, error) == ("Tidy paragraph.", "claude-test-model", None)
    sent = calls.calls[0]
    assert calls.keys == ["sk-test-key"]
    assert sent["model"] == "claude-test-model"
    assert sent["max_tokens"] == 321
    assert sent["messages"] == [{"role": "user", "content": "ugh the radar died again"}]
    assert "shift log" in sent["system"]


async def test_polish_text_joins_text_blocks_and_ignores_non_text(monkeypatch) -> None:
    response = SimpleNamespace(
        content=[
            SimpleNamespace(text="First."),
            SimpleNamespace(type="tool_use"),
            SimpleNamespace(text=None),
            SimpleNamespace(text="Second."),
        ]
    )
    _install_fake_client(monkeypatch, response)

    polished, _, error = await shift_service.polish_text("raw")

    assert polished == "First.\nSecond."
    assert error is None


async def test_polish_text_without_api_key_returns_error(monkeypatch) -> None:
    factory = MagicMock()
    monkeypatch.setattr(shift_service.anthropic, "AsyncAnthropic", factory)
    monkeypatch.setattr(settings, "anthropic_api_key", "")

    polished, model, error = await shift_service.polish_text("raw")

    assert polished is None
    assert model == settings.anthropic_model
    assert error == "ANTHROPIC_API_KEY is not configured"
    factory.assert_not_called()


async def test_polish_text_wraps_api_error(monkeypatch) -> None:
    _install_fake_client(monkeypatch, _api_error())

    polished, model, error = await shift_service.polish_text("raw")

    assert polished is None
    assert model == "claude-test-model"
    assert error is not None
    assert error.startswith("Anthropic API error:")
    assert "upstream exploded" in error


async def test_polish_text_reports_empty_response(monkeypatch) -> None:
    _install_fake_client(monkeypatch, SimpleNamespace(content=[SimpleNamespace(type="x")]))

    polished, _, error = await shift_service.polish_text("raw")

    assert polished is None
    assert error == "Model response contained no text blocks"


async def test_summarise_shift_rejects_empty_list_without_calling_model(monkeypatch) -> None:
    factory = MagicMock()
    monkeypatch.setattr(shift_service.anthropic, "AsyncAnthropic", factory)

    narrative, model, error = await shift_service.summarise_shift(MagicMock(), [])

    assert narrative is None
    assert model == settings.anthropic_model
    assert error == "Cannot summarise an empty shift."
    factory.assert_not_called()


async def test_summarise_shift_formats_notes_chronologically(monkeypatch) -> None:
    calls = _install_fake_client(monkeypatch, _response("# Quiet shift"))
    ts = datetime(2026, 9, 1, 8, 30, tzinfo=timezone.utc)
    notes = [
        _note("raw one", polished="Polished one.", created_at=ts),
        _note("  raw two  ", polished=None, created_at=None),
    ]

    narrative, model, error = await shift_service.summarise_shift(MagicMock(), notes)

    assert (narrative, model, error) == ("# Quiet shift", "claude-test-model", None)
    content = calls.calls[0]["messages"][0]["content"]
    assert content == f"- {ts.isoformat()}: Polished one.\n- ?: raw two"
    assert "handover" in calls.calls[0]["system"].lower()


async def test_summarise_shift_returns_error_on_api_failure(monkeypatch) -> None:
    _install_fake_client(monkeypatch, _api_error())

    narrative, model, error = await shift_service.summarise_shift(MagicMock(), [_note("raw")])

    assert narrative is None
    assert model == "claude-test-model"
    assert error is not None
    assert "upstream exploded" in error


def test_module_reexports_persistent_failure_helper() -> None:
    assert "is_persistent_anthropic_failure" in shift_service.__all__
    assert shift_service.is_persistent_anthropic_failure(None) is False


@pytest.mark.parametrize("raw", ["x", "a much longer operator rant about the radar"])
async def test_polish_text_passes_raw_through_unchanged_when_already_stripped(
    monkeypatch, raw: str
) -> None:
    calls = _install_fake_client(monkeypatch, _response("ok"))

    await shift_service.polish_text(raw)

    assert calls.calls[0]["messages"][0]["content"] == raw
