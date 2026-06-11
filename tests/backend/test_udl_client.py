from datetime import datetime, timedelta, timezone

import httpx
import pytest
from app.services.udl_client import (
    UDLAuthError,
    UDLClient,
    UDLClientError,
    _format_epoch,
)


def test_format_epoch_naive_datetime() -> None:
    dt = datetime(2025, 1, 15, 12, 30, 45, 123456)
    assert _format_epoch(dt) == "2025-01-15T12:30:45.123456Z"


def test_format_epoch_aware_datetime_converts_to_utc() -> None:
    dt = datetime(2025, 1, 15, 14, 30, 45, 0, tzinfo=timezone(timedelta(hours=2)))
    assert _format_epoch(dt) == "2025-01-15T12:30:45.000000Z"


async def test_get_elsets_sends_correct_request_and_returns_records() -> None:
    expected_records = [
        {
            "id": "abc-123",
            "satNo": 25544,
            "epoch": "2025-01-15T00:00:00.000000Z",
            "meanMotion": 15.5,
        }
    ]

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        captured["auth_header"] = request.headers.get("authorization")
        return httpx.Response(200, json=expected_records)

    transport = httpx.MockTransport(handler)

    async with UDLClient(
        base_url="https://udl.test/udl",
        username="user",
        password="pass",
        transport=transport,
    ) as client:
        records = await client.get_elsets(
            epoch_gte=datetime(2025, 1, 1, 0, 0, 0),
            sat_no=25544,
            max_results=100,
        )

    assert records == expected_records
    assert captured["path"] == "/udl/elset"
    assert captured["params"]["epoch"] == ">2025-01-01T00:00:00.000000Z"
    assert captured["params"]["satNo"] == "25544"
    assert captured["params"]["maxResults"] == "100"
    assert captured["auth_header"] is not None
    assert captured["auth_header"].startswith("Basic ")


async def test_get_elsets_raises_auth_error_on_401() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Unauthorized")

    transport = httpx.MockTransport(handler)

    with pytest.raises(UDLAuthError):
        async with UDLClient(username="u", password="p", transport=transport) as client:
            await client.get_elsets(epoch_gte=datetime(2025, 1, 1))


async def test_get_elsets_raises_client_error_on_500() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server boom")

    transport = httpx.MockTransport(handler)

    with pytest.raises(UDLClientError):
        async with UDLClient(username="u", password="p", transport=transport) as client:
            await client.get_elsets(epoch_gte=datetime(2025, 1, 1))


async def test_get_elsets_raises_client_error_on_non_list_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "object"})

    transport = httpx.MockTransport(handler)

    with pytest.raises(UDLClientError, match="not a list"):
        async with UDLClient(username="u", password="p", transport=transport) as client:
            await client.get_elsets(epoch_gte=datetime(2025, 1, 1))


async def test_missing_credentials_raises_on_enter() -> None:
    client = UDLClient(username="", password="")
    with pytest.raises(UDLClientError, match="credentials"):
        async with client:
            pass
