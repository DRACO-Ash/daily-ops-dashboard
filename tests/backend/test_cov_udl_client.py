"""Coverage for UDLClient request building and error handling (httpx.MockTransport only)."""

from datetime import datetime, timezone

import httpx
import pytest
from app.config import settings
from app.services.udl_client import UDLAuthError, UDLClient, UDLClientError


def _capturing_transport(captured: dict, payload=None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=payload if payload is not None else [])

    return httpx.MockTransport(handler)


def _client(transport: httpx.MockTransport) -> UDLClient:
    return UDLClient(
        base_url="https://udl.test/udl/", username="u", password="p", transport=transport
    )


async def test_get_elsets_includes_data_mode() -> None:
    captured: dict = {}
    async with _client(_capturing_transport(captured)) as client:
        await client.get_elsets(epoch_gte=datetime(2026, 1, 1), data_mode="TEST")

    assert captured["path"] == "/udl/elset"
    assert captured["params"] == {"epoch": ">2026-01-01T00:00:00.000000Z", "dataMode": "TEST"}


async def test_get_maneuvers_builds_all_params() -> None:
    captured: dict = {}
    records = [{"id": "m-1"}]
    async with _client(_capturing_transport(captured, records)) as client:
        result = await client.get_maneuvers(
            event_start_time_gte=datetime(2026, 1, 1, 6, tzinfo=timezone.utc),
            sat_no=25544,
            data_mode="REAL",
            max_results=10,
        )

    assert result == records
    assert captured["path"] == "/udl/maneuver"
    assert captured["params"] == {
        "eventStartTime": ">2026-01-01T06:00:00.000000Z",
        "satNo": "25544",
        "dataMode": "REAL",
        "maxResults": "10",
    }


async def test_get_maneuvers_minimal_params() -> None:
    captured: dict = {}
    async with _client(_capturing_transport(captured)) as client:
        await client.get_maneuvers(event_start_time_gte=datetime(2026, 1, 1))

    assert captured["params"] == {"eventStartTime": ">2026-01-01T00:00:00.000000Z"}


async def test_get_notifications_builds_all_params() -> None:
    captured: dict = {}
    async with _client(_capturing_transport(captured)) as client:
        await client.get_notifications(
            msg_type="TACREP_NOTSO",
            created_at_gte=datetime(2026, 2, 3),
            data_mode="REAL",
            source="JCO",
            max_results=5,
        )

    assert captured["path"] == "/udl/notification"
    assert captured["params"] == {
        "msgType": "TACREP_NOTSO",
        "createdAt": ">2026-02-03T00:00:00.000000Z",
        "dataMode": "REAL",
        "source": "JCO",
        "maxResults": "5",
    }


async def test_get_notifications_without_filters_sends_no_params() -> None:
    captured: dict = {}
    async with _client(_capturing_transport(captured)) as client:
        await client.get_notifications()

    assert captured["params"] == {}


async def test_get_list_outside_context_manager_raises() -> None:
    client = UDLClient(username="u", password="p")
    with pytest.raises(UDLClientError, match="async context manager"):
        await client.get_notifications()


async def test_transport_error_is_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(UDLClientError, match="UDL request failed") as info:
        async with _client(httpx.MockTransport(handler)) as client:
            await client.get_maneuvers(event_start_time_gte=datetime(2026, 1, 1))
    assert not isinstance(info.value, UDLAuthError)
    assert isinstance(info.value.__cause__, httpx.ConnectError)


async def test_invalid_json_is_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    with pytest.raises(UDLClientError, match="not valid JSON"):
        async with _client(httpx.MockTransport(handler)) as client:
            await client.get_notifications()


async def test_http_error_message_truncates_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="x" * 500)

    with pytest.raises(UDLClientError) as info:
        async with _client(httpx.MockTransport(handler)) as client:
            await client.get_notifications()
    message = str(info.value)
    assert message.startswith("UDL returned HTTP 503: ")
    assert message.count("x") == 200


async def test_client_is_closed_on_exit() -> None:
    client = _client(_capturing_transport({}))
    async with client:
        assert client._client is not None
    assert client._client is None
    # Exiting twice is a no-op.
    await client.__aexit__(None, None, None)


def test_defaults_come_from_settings(monkeypatch) -> None:
    monkeypatch.setattr(settings, "udl_base_url", "https://settings.test/udl/")
    monkeypatch.setattr(settings, "udl_username", "cfg-user")
    monkeypatch.setattr(settings, "udl_password", "cfg-pass")
    monkeypatch.setattr(settings, "udl_request_timeout_seconds", 7)
    monkeypatch.setattr(settings, "udl_verify_ssl", False)

    client = UDLClient()

    assert client._base_url == "https://settings.test/udl"
    assert client._username == "cfg-user"
    assert client._password == "cfg-pass"
    assert client._timeout == 7
    assert client._verify_ssl is False


async def test_real_transport_used_when_none_supplied() -> None:
    async with UDLClient(username="u", password="p") as client:
        assert isinstance(client._client, httpx.AsyncClient)
        assert str(client._client.base_url).startswith(settings.udl_base_url.rstrip("/"))
