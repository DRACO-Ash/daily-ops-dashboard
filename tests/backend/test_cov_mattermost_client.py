from datetime import datetime, timedelta, timezone

import httpx
import pytest
from app.config import settings
from app.services.mattermost_client import (
    MattermostAuthError,
    MattermostClient,
    MattermostClientError,
    datetime_to_ms,
    ms_to_datetime,
)


def _client(handler) -> MattermostClient:
    return MattermostClient(
        base_url="https://mm.test/",
        bot_token="tok-123",
        transport=httpx.MockTransport(handler),
    )


def test_datetime_to_ms_treats_naive_as_utc() -> None:
    naive = datetime(2025, 1, 1, 0, 0, 1)
    aware = datetime(2025, 1, 1, 0, 0, 1, tzinfo=timezone.utc)
    assert datetime_to_ms(naive) == datetime_to_ms(aware) == 1735689601000


def test_datetime_to_ms_converts_offset_to_utc() -> None:
    dt = datetime(2025, 1, 1, 2, 0, 1, tzinfo=timezone(timedelta(hours=2)))
    assert datetime_to_ms(dt) == 1735689601000


def test_ms_to_datetime_round_trips() -> None:
    dt = ms_to_datetime(1735689601500)
    assert dt == datetime(2025, 1, 1, 0, 0, 1, 500000, tzinfo=timezone.utc)
    assert datetime_to_ms(dt) == 1735689601500


def test_defaults_come_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mattermost_url", "https://chat.example/")
    monkeypatch.setattr(settings, "mattermost_bot_token", "from-settings")
    client = MattermostClient()
    assert client._base_url == "https://chat.example"
    assert client._bot_token == "from-settings"


def test_explicit_empty_token_is_not_replaced_by_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "mattermost_bot_token", "from-settings")
    client = MattermostClient(base_url="https://mm.test", bot_token="")
    assert client._bot_token == ""


async def test_enter_raises_when_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mattermost_url", "")
    monkeypatch.setattr(settings, "mattermost_bot_token", "")
    with pytest.raises(MattermostClientError, match="not configured"):
        async with MattermostClient():
            pass


async def test_enter_raises_when_token_missing() -> None:
    with pytest.raises(MattermostClientError, match="not configured"):
        async with MattermostClient(base_url="https://mm.test", bot_token=""):
            pass


async def test_enter_without_transport_builds_real_client_and_exit_closes() -> None:
    client = MattermostClient(base_url="https://mm.test", bot_token="t")
    async with client as entered:
        assert entered is client
        assert isinstance(client._client, httpx.AsyncClient)
        assert str(client._client.base_url) == "https://mm.test/api/v4/"
    assert client._client is None


async def test_exit_without_enter_is_noop() -> None:
    client = MattermostClient(base_url="https://mm.test", bot_token="t")
    await client.__aexit__(None, None, None)
    assert client._client is None


async def test_get_json_outside_context_manager_raises() -> None:
    client = MattermostClient(base_url="https://mm.test", bot_token="t")
    with pytest.raises(MattermostClientError, match="async context manager"):
        await client.get_user("u1")


async def test_get_channel_posts_since_sends_params_and_bearer() -> None:
    captured: dict = {}
    payload = {"posts": {"p1": {"id": "p1"}}, "order": ["p1"]}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=payload)

    async with _client(handler) as mm:
        result = await mm.get_channel_posts_since("chan1", 1700000000000, per_page=50)

    assert result == payload
    assert captured["path"] == "/api/v4/channels/chan1/posts"
    assert captured["params"] == {"since": "1700000000000", "per_page": "50"}
    assert captured["auth"] == "Bearer tok-123"


async def test_get_channel_and_get_user_hit_expected_paths() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json={"path": request.url.path})

    async with _client(handler) as mm:
        channel = await mm.get_channel("c9")
        user = await mm.get_user("u7")

    assert channel == {"path": "/api/v4/channels/c9"}
    assert user == {"path": "/api/v4/users/u7"}
    assert paths == ["/api/v4/channels/c9", "/api/v4/users/u7"]


@pytest.mark.parametrize(
    ("status", "match"),
    [(401, "bot token"), (403, "bot not in channel")],
)
async def test_auth_statuses_raise_auth_error(status: int, match: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="nope")

    with pytest.raises(MattermostAuthError, match=match):
        async with _client(handler) as mm:
            await mm.get_user("u1")


async def test_server_error_raises_client_error_not_auth_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server boom")

    with pytest.raises(MattermostClientError, match="HTTP 500: server boom") as info:
        async with _client(handler) as mm:
            await mm.get_channel("c1")
    assert not isinstance(info.value, MattermostAuthError)


async def test_transport_error_wrapped_as_client_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(MattermostClientError, match="request failed") as info:
        async with _client(handler) as mm:
            await mm.get_channel("c1")
    assert isinstance(info.value.__cause__, httpx.ConnectError)
