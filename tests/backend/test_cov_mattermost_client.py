from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import pytest
from app.config import settings
from app.services.mattermost_client import (
    MAX_ATTEMPTS,
    PAGE_PAUSE_S,
    PER_PAGE,
    USER_BATCH,
    MattermostAuthError,
    MattermostClient,
    MattermostClientError,
    datetime_to_ms,
    ms_to_datetime,
    retry_delay,
)


def _client(handler, sleeps: Optional[list[float]] = None) -> MattermostClient:
    """Client over a mock transport. Retry sleeps are recorded, not slept."""
    recorded = sleeps if sleeps is not None else []

    async def _sleep(seconds: float) -> None:
        recorded.append(seconds)

    return MattermostClient(
        base_url="https://mm.test/",
        bot_token="tok-123",
        transport=httpx.MockTransport(handler),
        sleep=_sleep,
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


async def test_server_error_retries_then_raises_client_error() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(500, text="server boom")

    sleeps: list[float] = []
    with pytest.raises(MattermostClientError, match="HTTP 500: server boom") as info:
        async with _client(handler, sleeps) as mm:
            await mm.get_channel("c1")
    assert not isinstance(info.value, MattermostAuthError)
    assert len(calls) == MAX_ATTEMPTS
    assert sleeps == [1.0, 2.0, 4.0]


async def test_rate_limit_honours_retry_after_then_succeeds() -> None:
    responses = [
        httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(503),
        httpx.Response(200, json={"id": "c1"}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    sleeps: list[float] = []
    async with _client(handler, sleeps) as mm:
        assert await mm.get_channel("c1") == {"id": "c1"}
    assert sleeps == [7.0, 2.0]


async def test_transport_error_retries_then_wraps_as_client_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    sleeps: list[float] = []
    with pytest.raises(MattermostClientError, match="request failed") as info:
        async with _client(handler, sleeps) as mm:
            await mm.get_channel("c1")
    assert isinstance(info.value.__cause__, httpx.ConnectError)
    assert sleeps == [1.0, 2.0, 4.0]


async def test_transient_transport_error_recovers() -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, json={"ok": True})

    async with _client(handler, []) as mm:
        assert await mm.get_user("u1") == {"ok": True}


@pytest.mark.parametrize(
    ("retry_after", "attempt", "expected"),
    [("3", 1, 3.0), ("-2", 1, 0.0), ("soon", 2, 2.0), (None, 3, 4.0)],
)
def test_retry_delay(retry_after, attempt: int, expected: float) -> None:
    assert retry_delay(attempt, retry_after) == expected


async def test_invalid_json_raises_client_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>proxy error</html>")

    with pytest.raises(MattermostClientError, match="invalid JSON"):
        async with _client(handler, []) as mm:
            await mm.get_user("u1")


async def test_get_team_id_quotes_and_lowercases_name() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.raw_path.decode())
        return httpx.Response(200, json={"id": "team1"})

    async with _client(handler, []) as mm:
        assert await mm.get_team_id("  JCO ") == "team1"
    assert seen == ["/api/v4/teams/name/jco"]


async def test_get_team_id_without_id_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"name": "jco"})

    with pytest.raises(MattermostClientError, match="did not resolve"):
        async with _client(handler, []) as mm:
            await mm.get_team_id("jco")


async def test_get_my_team_channels_pages_until_short_page() -> None:
    pages = {"0": [{"id": f"c{i}"} for i in range(PER_PAGE)], "1": [{"id": "last"}, "junk"]}
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.params["page"])
        assert request.url.path == "/api/v4/users/me/teams/t1/channels"
        return httpx.Response(200, json=pages[request.url.params["page"]])

    async with _client(handler, []) as mm:
        channels = await mm.get_my_team_channels("t1")
    assert requested == ["0", "1"]
    assert len(channels) == PER_PAGE + 1
    assert channels[-1] == {"id": "last"}


async def test_get_my_team_channels_rejects_non_list_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "nope"})

    with pytest.raises(MattermostClientError, match="unexpected payload"):
        async with _client(handler, []) as mm:
            await mm.get_my_team_channels("t1")


async def test_get_users_by_ids_batches_and_skips_failed_batch() -> None:
    bodies: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        ids = httpx.Response(200, content=request.content).json()
        bodies.append(ids)
        if len(bodies) == 2:
            return httpx.Response(400)
        if len(bodies) == 3:
            return httpx.Response(200, json={"not": "a list"})
        return httpx.Response(200, json=[{"id": i} for i in ids] + ["junk"])

    ids = [f"u{i}" for i in range(USER_BATCH * 3 + 1)]
    async with _client(handler, []) as mm:
        users = await mm.get_users_by_ids(ids)
    assert [len(b) for b in bodies] == [USER_BATCH, USER_BATCH, USER_BATCH, 1]
    assert [u["id"] for u in users] == ids[:USER_BATCH] + ids[-1:]


async def test_get_channel_posts_before_sends_cursor_only_when_set() -> None:
    params: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params.append(dict(request.url.params))
        return httpx.Response(200, json={"order": [], "posts": {}})

    async with _client(handler, []) as mm:
        await mm.get_channel_posts_before("c1", None)
        await mm.get_channel_posts_before("c1", "p9", per_page=50)
    assert params == [
        {"page": "0", "per_page": str(PER_PAGE)},
        {"page": "0", "per_page": "50", "before": "p9"},
    ]


async def test_pause_uses_the_injected_sleep() -> None:
    sleeps: list[float] = []
    async with _client(lambda r: httpx.Response(200, json={}), sleeps) as mm:
        await mm.pause()
    assert sleeps == [PAGE_PAUSE_S]
