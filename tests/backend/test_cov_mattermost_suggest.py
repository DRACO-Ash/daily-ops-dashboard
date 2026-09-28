"""Drafting an ask from plain English: validation, the one retry, failures."""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import anthropic
import httpx
import pytest
from app.config import settings
from app.services import mattermost_suggest as suggest
from app.services.mattermost_suggest import SuggestError, suggest_ask

GOOD = {
    "name": "Verified solves",
    "explanation": "Posts by the fusion provider saying Verified solve, first per thread.",
    "spec": {
        "terms": ["Verified solve"],
        "authors": ["fusion.provider"],
        "scope": "first_per_thread",
    },
}


def _reply(text: str, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(content=[SimpleNamespace(text=text)], stop_reason=stop_reason)


@pytest.fixture
def claude(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    create = AsyncMock()
    monkeypatch.setattr(
        suggest.anthropic,
        "AsyncAnthropic",
        lambda **_kw: SimpleNamespace(messages=SimpleNamespace(create=create)),
    )
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")
    monkeypatch.setattr(settings, "anthropic_model", "claude-test")
    return create


async def test_valid_draft_is_returned_and_prompt_lists_channels(claude: AsyncMock) -> None:
    claude.return_value = _reply("Here you go: " + json.dumps(GOOD))

    result = await suggest_ask("When did fusion verify solves?", ["jco_dok", "fusion"])

    assert result.spec.authors == ["fusion.provider"]
    assert result.spec.scope == "first_per_thread"
    call = claude.await_args.kwargs
    assert call["model"] == "claude-test"
    assert "Channels the bot can see: fusion, jco_dok" in call["messages"][0]["content"]
    assert "When did fusion verify solves?" in call["messages"][0]["content"]
    assert "any_terms" in call["system"]


async def test_invalid_draft_is_retried_once_with_the_error(claude: AsyncMock) -> None:
    bad = {**GOOD, "spec": {"scope": "posts"}}  # nothing narrows the pull
    claude.side_effect = [_reply(json.dumps(bad)), _reply(json.dumps(GOOD))]

    result = await suggest_ask("verified solves", [])

    assert result.name == "Verified solves"
    retry_messages = claude.await_args_list[1].kwargs["messages"]
    assert [m["role"] for m in retry_messages] == ["user", "assistant", "user"]
    assert "did not validate" in retry_messages[2]["content"]
    assert "Channels the bot can see: (unavailable)" in retry_messages[0]["content"]


async def test_second_invalid_draft_raises(claude: AsyncMock) -> None:
    claude.side_effect = [_reply("no json here"), _reply('{"name": 1}')]
    with pytest.raises(SuggestError, match="not a valid ask"):
        await suggest_ask("anything", [])
    assert claude.await_count == 2


@pytest.mark.parametrize(
    ("reply", "match"),
    [
        (_reply("", "refusal"), "declined"),
        (_reply("{", "max_tokens"), "cut off"),
        (
            SimpleNamespace(content=[SimpleNamespace(type="tool_use")], stop_reason="end_turn"),
            "no text",
        ),
    ],
)
async def test_unusable_responses_raise(claude: AsyncMock, reply: Any, match: str) -> None:
    claude.return_value = reply
    with pytest.raises(SuggestError, match=match):
        await suggest_ask("anything", [])


async def test_api_error_is_wrapped(claude: AsyncMock) -> None:
    claude.side_effect = anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))
    with pytest.raises(SuggestError, match="Anthropic API error"):
        await suggest_ask("anything", [])


async def test_missing_api_key_raises_before_calling(
    claude: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    with pytest.raises(SuggestError, match="not configured"):
        await suggest_ask("anything", [])
    claude.assert_not_awaited()
