import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from app.config import settings
from app.services import mattermost_ingest
from app.services.mattermost_client import MattermostClient, datetime_to_ms
from app.services.mattermost_ingest import (
    MattermostIngestResult,
    _configured_channel_ids,
    _is_ingestible,
    ingest_mattermost_messages,
)

HIGH_WATER = datetime(2025, 3, 1, 12, 0, 0, tzinfo=timezone.utc)


def _post(post_id: str, **overrides: Any) -> dict[str, Any]:
    post = {
        "id": post_id,
        "user_id": "u1",
        "create_at": 1740830400000,
        "message": f"hello {post_id}",
        "type": "",
    }
    post.update(overrides)
    return post


class _FakeMattermost:
    """Routes MockTransport requests to canned per-path responses."""

    def __init__(self, routes: dict[str, httpx.Response]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/api/v4")
        return self.routes.get(path, httpx.Response(404, text="missing"))

    def paths(self) -> list[str]:
        return [r.url.path.removeprefix("/api/v4") for r in self.requests]


def _install_client(monkeypatch: pytest.MonkeyPatch, fake: _FakeMattermost) -> None:
    def _factory() -> MattermostClient:
        return MattermostClient(
            base_url="https://mm.test",
            bot_token="tok",
            transport=httpx.MockTransport(fake.handler),
        )

    monkeypatch.setattr(mattermost_ingest, "MattermostClient", _factory)


def _make_db(high_water: Optional[datetime] = None, rowcount: Optional[int] = 0) -> AsyncMock:
    inserts: list[Any] = []

    async def _execute(stmt, *args, **kwargs):
        result = MagicMock()
        if getattr(stmt, "is_insert", False):
            inserts.append(stmt)
            result.rowcount = rowcount
        else:
            result.scalar_one_or_none.return_value = high_water
        return result

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=_execute)
    db.inserts = inserts
    return db


@pytest.fixture
def audit(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock()
    monkeypatch.setattr(mattermost_ingest, "write_audit", mock)
    return mock


def test_configured_channel_ids_strips_and_drops_blanks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "mattermost_channel_ids", " a , ,b,, c ")
    assert _configured_channel_ids() == ["a", "b", "c"]
    monkeypatch.setattr(settings, "mattermost_channel_ids", None)
    assert _configured_channel_ids() == []


@pytest.mark.parametrize(
    ("post", "expected"),
    [
        (_post("p"), True),
        (_post("p", type="system_join_channel"), False),
        (_post("p", create_at="1740830400000"), False),
        (_post("p", create_at=None), False),
        (_post("p", message="   "), False),
        (_post("p", message=None, type=None), False),
    ],
)
def test_is_ingestible(post: dict[str, Any], expected: bool) -> None:
    assert _is_ingestible(post) is expected


async def test_no_channels_returns_zero_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, audit: AsyncMock
) -> None:
    monkeypatch.setattr(settings, "mattermost_channel_ids", "")
    db = _make_db()

    result = await ingest_mattermost_messages(db)

    assert result == MattermostIngestResult(0, 0, 0, 0, 0)
    db.execute.assert_not_awaited()
    audit.assert_not_awaited()
    db.commit.assert_not_awaited()


async def test_ingest_inserts_filters_caches_and_audits(
    monkeypatch: pytest.MonkeyPatch, audit: AsyncMock
) -> None:
    monkeypatch.setattr(settings, "mattermost_channel_ids", "chanA")
    posts = {
        "p1": _post("p1", user_id="u1"),
        "p2": _post("p2", user_id="u1"),
        "p3": _post("p3", user_id="u2"),
        "sys": _post("sys", type="system_add_to_channel"),
    }
    fake = _FakeMattermost(
        {
            "/channels/chanA/posts": httpx.Response(
                200, json={"posts": posts, "order": ["p1", "p2", "p3", "sys", "ghost"]}
            ),
            "/channels/chanA": httpx.Response(200, json={"name": "ops", "display_name": "Ops"}),
            "/users/u1": httpx.Response(200, json={"nickname": "", "username": "alice"}),
            "/users/u2": httpx.Response(500, text="boom"),
        }
    )
    _install_client(monkeypatch, fake)
    db = _make_db(high_water=None, rowcount=3)
    actor = uuid.uuid4()

    result = await ingest_mattermost_messages(db, user_id_actor=actor, ip_address="10.0.0.1")

    assert result == MattermostIngestResult(
        channels_polled=1, channels_failed=0, pulled=5, inserted=3, skipped=2
    )
    # u1 looked up once despite two posts; channel name fetched once.
    assert fake.paths().count("/users/u1") == 1
    assert fake.paths().count("/users/u2") == 1
    assert fake.paths().count("/channels/chanA") == 1

    assert len(db.inserts) == 1
    params = db.inserts[0].compile().params
    assert params["mm_post_id_m0"] == "p1"
    assert params["user_display_name_m0"] == "alice"
    assert params["user_display_name_m2"] is None
    assert params["channel_name_m0"] == "Ops"
    assert params["posted_at_m0"] == datetime(2025, 3, 1, 12, 0, tzinfo=timezone.utc)

    audit.assert_awaited_once()
    kwargs = audit.await_args.kwargs
    assert kwargs["action_type"] == "mattermost.ingest"
    assert kwargs["entity_type"] == "mattermost_ingest_run"
    assert kwargs["user_id"] == actor
    assert kwargs["ip_address"] == "10.0.0.1"
    assert kwargs["detail"] == {
        "channels_polled": 1,
        "channels_failed": 0,
        "pulled": 5,
        "inserted": 3,
        "skipped": 2,
    }
    db.commit.assert_awaited_once()


async def test_high_water_adds_one_ms_and_skips_empty_order(
    monkeypatch: pytest.MonkeyPatch, audit: AsyncMock
) -> None:
    fake = _FakeMattermost(
        {"/channels/c1/posts": httpx.Response(200, json={"posts": None, "order": None})}
    )
    _install_client(monkeypatch, fake)
    db = _make_db(high_water=HIGH_WATER)

    result = await ingest_mattermost_messages(db, channel_ids=["c1"])

    assert result == MattermostIngestResult(1, 0, 0, 0, 0)
    posts_request = fake.requests[0]
    assert posts_request.url.params["since"] == str(datetime_to_ms(HIGH_WATER) + 1)
    # No channel-name lookup when there is nothing to store.
    assert fake.paths() == ["/channels/c1/posts"]
    assert db.inserts == []
    audit.assert_awaited_once()


async def test_all_posts_filtered_means_no_insert(
    monkeypatch: pytest.MonkeyPatch, audit: AsyncMock
) -> None:
    fake = _FakeMattermost(
        {
            "/channels/c1/posts": httpx.Response(
                200,
                json={"posts": {"s": _post("s", type="system_x")}, "order": ["s"]},
            ),
            "/channels/c1": httpx.Response(403, text="denied"),
        }
    )
    _install_client(monkeypatch, fake)
    db = _make_db()

    result = await ingest_mattermost_messages(db, channel_ids=["c1"])

    assert result == MattermostIngestResult(1, 0, 1, 0, 1)
    assert db.inserts == []


async def test_null_rowcount_counts_as_zero_and_nickname_preferred(
    monkeypatch: pytest.MonkeyPatch, audit: AsyncMock
) -> None:
    fake = _FakeMattermost(
        {
            "/channels/c1/posts": httpx.Response(
                200, json={"posts": {"p": _post("p")}, "order": ["p"]}
            ),
            "/channels/c1": httpx.Response(200, json={"display_name": "", "name": "raw-name"}),
            "/users/u1": httpx.Response(200, json={"nickname": "Nick", "username": "n"}),
        }
    )
    _install_client(monkeypatch, fake)
    db = _make_db(rowcount=None)

    result = await ingest_mattermost_messages(db, channel_ids=["c1"])

    assert result.inserted == 0
    params = db.inserts[0].compile().params
    assert params["user_display_name_m0"] == "Nick"
    assert params["channel_name_m0"] == "raw-name"


async def test_per_channel_errors_are_counted_and_others_continue(
    monkeypatch: pytest.MonkeyPatch, audit: AsyncMock
) -> None:
    fake = _FakeMattermost(
        {
            "/channels/denied/posts": httpx.Response(403, text="no"),
            "/channels/broken/posts": httpx.Response(502, text="bad gateway"),
            "/channels/ok/posts": httpx.Response(200, json={"posts": {}, "order": []}),
        }
    )
    _install_client(monkeypatch, fake)
    db = _make_db()

    result = await ingest_mattermost_messages(db, channel_ids=["denied", "broken", "ok"])

    assert result == MattermostIngestResult(1, 2, 0, 0, 0)
    assert audit.await_args.kwargs["detail"]["channels_failed"] == 2
    db.commit.assert_awaited_once()


async def test_unconfigured_client_aborts_and_marks_all_failed(
    monkeypatch: pytest.MonkeyPatch, audit: AsyncMock
) -> None:
    monkeypatch.setattr(settings, "mattermost_url", "")
    monkeypatch.setattr(settings, "mattermost_bot_token", "")
    db = _make_db()

    result = await ingest_mattermost_messages(db, channel_ids=["a", "b"])

    assert result == MattermostIngestResult(0, 2, 0, 0, 0)
    db.execute.assert_not_awaited()
    assert audit.await_args.kwargs["detail"]["channels_failed"] == 2
    db.commit.assert_awaited_once()
