"""Mattermost ingest: channel discovery, full-history backfill, edits, deletions."""

from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from app.config import settings
from app.models.mattermost_message import MattermostChannelState
from app.services import mattermost_ingest
from app.services.mattermost_client import PER_PAGE, MattermostClient
from app.services.mattermost_ingest import (
    MattermostIngestResult,
    _Channel,
    _configured_channel_ids,
    _highest_update,
    _is_ingestible,
    ingest_mattermost_messages,
    selectable_channels,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Insert, Update

BASE_MS = 1_740_000_000_000


def _post(n: int, **overrides: Any) -> dict[str, Any]:
    post = {
        "id": f"p{n:04d}",
        "user_id": f"u{n % 3}",
        "create_at": BASE_MS + n * 1000,
        "update_at": BASE_MS + n * 1000,
        "message": f"message {n}",
        "type": "",
    }
    post.update(overrides)
    return post


class FakeMattermost:
    """In-memory Mattermost with the paging semantics the ingest relies on.

    History pages are newest first; `before` returns posts older than the
    given id; `since` returns posts whose update_at is strictly greater.
    """

    def __init__(self, posts: Optional[list[dict[str, Any]]] = None) -> None:
        self.posts = list(posts or [])
        self.channels = [
            {"id": "chanA", "name": "jco_dok", "display_name": "JCO DOK", "type": "O"},
        ]
        self.users = {"u0": {"nickname": "Duty Officer"}, "u1": {}, "u2": {}}
        self.requests: list[httpx.Request] = []
        self.fail_paths: dict[str, int] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/api/v4")
        if path in self.fail_paths:
            return httpx.Response(self.fail_paths[path])
        if path == "/teams/name/jco":
            return httpx.Response(200, json={"id": "team1"})
        if path == "/users/me/teams/team1/channels":
            return httpx.Response(200, json=self.channels)
        if path == "/users/ids":
            return httpx.Response(200, json=self._users(request))
        if path.endswith("/posts"):
            return httpx.Response(200, json=self._page(request.url.params))
        if path.startswith("/channels/"):
            return httpx.Response(200, json={"id": path.split("/")[2], "name": "named"})
        return httpx.Response(404)

    def _users(self, request: httpx.Request) -> list[dict[str, Any]]:
        ids = httpx.Response(200, content=request.content).json()
        return [{"id": i, "username": f"user-{i}", **self.users[i]} for i in ids if i in self.users]

    def _page(self, params: httpx.QueryParams) -> dict[str, Any]:
        newest_first = sorted(self.posts, key=lambda p: p["create_at"], reverse=True)
        if "since" in params:
            chosen = [p for p in newest_first if p["update_at"] > int(params["since"])]
        else:
            before = params.get("before")
            if before:
                ids = [p["id"] for p in newest_first]
                newest_first = newest_first[ids.index(before) + 1 :]
            chosen = newest_first[: int(params["per_page"])]
        return {"order": [p["id"] for p in chosen], "posts": {p["id"]: p for p in chosen}}

    def calls(self, suffix: str) -> list[httpx.QueryParams]:
        return [r.url.params for r in self.requests if r.url.path.endswith(suffix)]


class FakeDb:
    """Records statements; the insert reports every row as newly inserted
    unless its post id is in `existing`, which it reports as updated."""

    def __init__(self, state: Optional[MattermostChannelState] = None) -> None:
        self.states = {state.channel_id: state} if state else {}
        self.existing: set[str] = set()
        self.inserts: list[Insert] = []
        self.updates: list[Update] = []
        self.added: list[Any] = []
        self.commit = AsyncMock()

    async def get(self, _model: Any, key: str) -> Optional[MattermostChannelState]:
        return self.states.get(key)

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        self.states[obj.channel_id] = obj

    async def execute(self, stmt: Any) -> MagicMock:
        result = MagicMock()
        if isinstance(stmt, Insert):
            self.inserts.append(stmt)
            ids = [row["mm_post_id"] for row in _rows(stmt)]
            result.scalars.return_value.all.return_value = [i not in self.existing for i in ids]
        else:
            self.updates.append(stmt)
            result.rowcount = 1
        return result

    def stored_ids(self) -> list[str]:
        return [row["mm_post_id"] for stmt in self.inserts for row in _rows(stmt)]


def _rows(stmt: Insert) -> list[dict[str, Any]]:
    params = stmt.compile(dialect=postgresql.dialect()).params
    count = sum(1 for key in params if key.startswith("mm_post_id_m"))
    fields = ("mm_post_id", "message", "user_display_name", "mm_updated_at", "root_id")
    return [{f: params[f"{f}_m{i}"] for f in fields} for i in range(count)]


@pytest.fixture
def mm(monkeypatch: pytest.MonkeyPatch) -> FakeMattermost:
    fake = FakeMattermost()
    sleeps: list[float] = []

    async def _sleep(seconds: float) -> None:
        sleeps.append(seconds)

    def _factory() -> MattermostClient:
        return MattermostClient(
            base_url="https://mm.test",
            bot_token="tok",
            transport=httpx.MockTransport(fake.handler),
            sleep=_sleep,
        )

    fake.sleeps = sleeps  # type: ignore[attr-defined]
    monkeypatch.setattr(mattermost_ingest, "MattermostClient", _factory)
    monkeypatch.setattr(settings, "mattermost_channel_ids", "")
    monkeypatch.setattr(settings, "mattermost_team", "jco")
    monkeypatch.setattr(settings, "mattermost_team_id", "")
    monkeypatch.setattr(settings, "mattermost_backfill_pages_per_cycle", 10)
    return fake


@pytest.fixture
def audit(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock()
    monkeypatch.setattr(mattermost_ingest, "write_audit", mock)
    return mock


# Pure helpers ---------------------------------------------------------------


def test_configured_channel_ids_strips_and_drops_blanks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mattermost_channel_ids", " a , ,b,")
    assert _configured_channel_ids() == ["a", "b"]


def test_selectable_channels_keeps_live_team_channels_only() -> None:
    channels = [
        {"id": "o", "type": "O", "display_name": "Ops", "name": "ops"},
        {"id": "p", "type": "P", "name": "private"},
        {"id": "d", "type": "D"},
        {"id": "g", "type": "G"},
        {"id": "x", "type": "O", "delete_at": 99},
        {"type": "O"},
    ]
    assert selectable_channels(channels) == [_Channel("o", "Ops"), _Channel("p", "private")]


@pytest.mark.parametrize(
    ("post", "expected"),
    [
        ({"type": "", "create_at": 1, "message": "hi"}, True),
        ({"type": "system_join_channel", "create_at": 1, "message": "joined"}, False),
        ({"type": "", "create_at": "1", "message": "hi"}, False),
        ({"type": "", "create_at": 1, "message": "   "}, False),
    ],
)
def test_is_ingestible(post: dict[str, Any], expected: bool) -> None:
    assert _is_ingestible(post) is expected


def test_highest_update_ignores_non_integer_stamps() -> None:
    posts = [{"update_at": 5}, {"create_at": 9}, {"update_at": "12"}, {}]
    assert _highest_update(posts, 7) == 9
    assert _highest_update([], 7) == 7


# Configuration --------------------------------------------------------------


async def test_unconfigured_returns_zero_without_calling_mattermost(
    mm: FakeMattermost, audit: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mattermost_team", "")
    db = FakeDb()

    result = await ingest_mattermost_messages(db)  # type: ignore[arg-type]

    assert result == MattermostIngestResult(0, 0, 0, 0, 0)
    assert mm.requests == []
    audit.assert_not_awaited()


async def test_explicit_empty_channel_list_is_a_no_op(mm: FakeMattermost, audit: AsyncMock) -> None:
    result = await ingest_mattermost_messages(FakeDb(), channel_ids=[])  # type: ignore[arg-type]
    assert result.channels_polled == 0
    assert mm.requests == []


async def test_team_id_setting_skips_team_name_lookup(
    mm: FakeMattermost, audit: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mattermost_team", "")
    monkeypatch.setattr(settings, "mattermost_team_id", "team1")

    await ingest_mattermost_messages(FakeDb())  # type: ignore[arg-type]

    paths = [r.url.path for r in mm.requests]
    assert "/api/v4/teams/name/jco" not in paths
    assert "/api/v4/users/me/teams/team1/channels" in paths


async def test_configured_channel_ids_override_discovery(
    mm: FakeMattermost, audit: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mattermost_channel_ids", "chanZ")
    db = FakeDb()

    await ingest_mattermost_messages(db)  # type: ignore[arg-type]

    assert list(db.states) == ["chanZ"]
    assert db.states["chanZ"].channel_name == "named"
    assert not any("/teams/" in r.url.path for r in mm.requests)


async def test_channel_ids_argument_is_used_as_given(mm: FakeMattermost, audit: AsyncMock) -> None:
    db = FakeDb()
    await ingest_mattermost_messages(db, channel_ids=["chanQ"])  # type: ignore[arg-type]
    assert list(db.states) == ["chanQ"]


async def test_discovery_ingests_every_channel_the_bot_belongs_to(
    mm: FakeMattermost, audit: AsyncMock
) -> None:
    mm.channels.append({"id": "chanB", "name": "exercise_ops", "type": "P"})
    mm.channels.append({"id": "dm", "type": "D"})
    db = FakeDb()

    result = await ingest_mattermost_messages(db)  # type: ignore[arg-type]

    assert sorted(db.states) == ["chanA", "chanB"]
    assert db.states["chanA"].channel_name == "JCO DOK"
    assert result.channels_polled == 2


# Backfill -------------------------------------------------------------------


async def test_first_cycle_backfills_the_full_history(mm: FakeMattermost, audit: AsyncMock) -> None:
    mm.posts = [_post(n) for n in range(450)]
    db = FakeDb()

    result = await ingest_mattermost_messages(db)  # type: ignore[arg-type]

    assert sorted(db.stored_ids()) == sorted(p["id"] for p in mm.posts)
    state = db.states["chanA"]
    assert state.backfill_complete is True
    assert state.backfill_cursor == "p0000"
    assert state.watermark_ms == BASE_MS + 449 * 1000
    pages = mm.calls("/channels/chanA/posts")
    assert [p.get("before") for p in pages] == [None, "p0250", "p0050"]
    assert all(p["per_page"] == str(PER_PAGE) for p in pages)
    assert mm.sleeps == [0.5, 0.5]  # type: ignore[attr-defined]
    assert (result.pulled, result.inserted, result.updated) == (450, 450, 0)
    db.commit.assert_awaited_once()


async def test_backfill_stops_at_the_page_cap_and_resumes_next_cycle(
    mm: FakeMattermost, audit: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mattermost_backfill_pages_per_cycle", 1)
    mm.posts = [_post(n) for n in range(450)]
    db = FakeDb()

    await ingest_mattermost_messages(db)  # type: ignore[arg-type]
    state = db.states["chanA"]
    assert (state.backfill_complete, state.backfill_cursor) == (False, "p0250")
    assert len(db.stored_ids()) == PER_PAGE

    mm.posts.append(_post(900))  # arrives mid-backfill; must not open a gap
    await ingest_mattermost_messages(db)  # type: ignore[arg-type]
    await ingest_mattermost_messages(db)  # type: ignore[arg-type]

    assert set(db.stored_ids()) == {p["id"] for p in mm.posts}
    assert state.backfill_complete is True


async def test_empty_channel_completes_backfill_without_inserting(
    mm: FakeMattermost, audit: AsyncMock
) -> None:
    db = FakeDb()

    result = await ingest_mattermost_messages(db)  # type: ignore[arg-type]

    state = db.states["chanA"]
    assert (state.backfill_complete, state.backfill_cursor, state.watermark_ms) == (True, None, 0)
    assert db.inserts == []
    assert result.channels_polled == 1


# Incremental ----------------------------------------------------------------


def _synced_state(watermark: int) -> MattermostChannelState:
    return MattermostChannelState(
        channel_id="chanA", watermark_ms=watermark, backfill_complete=True
    )


async def test_incremental_pulls_since_watermark_minus_one(
    mm: FakeMattermost, audit: AsyncMock
) -> None:
    watermark = BASE_MS + 10_000
    mm.posts = [_post(10), _post(11), _post(12)]
    db = FakeDb(_synced_state(watermark))
    db.existing = {"p0010"}

    result = await ingest_mattermost_messages(db)  # type: ignore[arg-type]

    assert mm.calls("/channels/chanA/posts") == [
        httpx.QueryParams({"since": str(watermark - 1), "per_page": str(PER_PAGE)})
    ]
    assert sorted(db.stored_ids()) == ["p0010", "p0011", "p0012"]
    assert (result.inserted, result.updated) == (2, 1)
    assert db.states["chanA"].watermark_ms == BASE_MS + 12_000


async def test_edits_and_deletions_are_archived_not_dropped(
    mm: FakeMattermost, audit: AsyncMock
) -> None:
    watermark = BASE_MS + 50_000
    edited = _post(3, message="corrected", update_at=watermark + 5, edit_at=watermark + 5)
    deleted = _post(4, message="", update_at=watermark + 9, delete_at=watermark + 9)
    system = _post(5, type="system_join_channel", update_at=watermark + 1)
    reply = _post(6, root_id="p0003", update_at=watermark + 2)
    mm.posts = [edited, deleted, system, reply]
    db = FakeDb(_synced_state(watermark))

    result = await ingest_mattermost_messages(db)  # type: ignore[arg-type]

    rows = {row["mm_post_id"]: row for stmt in db.inserts for row in _rows(stmt)}
    assert sorted(rows) == ["p0003", "p0006"]
    assert rows["p0003"]["message"] == "corrected"
    assert rows["p0006"]["root_id"] == "p0003"
    assert len(db.updates) == 1
    update_sql = str(db.updates[0].compile(dialect=postgresql.dialect()))
    assert "deleted_at IS NULL" in update_sql
    assert "message" not in update_sql.split("SET")[1].split("WHERE")[0]
    assert (result.deleted, result.skipped, result.pulled) == (1, 1, 4)
    assert db.states["chanA"].watermark_ms == watermark + 9


async def test_upsert_only_replaces_with_a_newer_revision(
    mm: FakeMattermost, audit: AsyncMock
) -> None:
    mm.posts = [_post(1)]
    db = FakeDb()

    await ingest_mattermost_messages(db)  # type: ignore[arg-type]

    sql = str(db.inserts[0].compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT ON CONSTRAINT uq_mattermost_message_post_id DO UPDATE" in sql
    assert "WHERE excluded.mm_updated_at > coalesce(mattermost_message.mm_updated_at" in sql
    assert "RETURNING (xmax = 0)" in sql


# Names ----------------------------------------------------------------------


async def test_author_names_are_batched_once_per_cycle(
    mm: FakeMattermost, audit: AsyncMock
) -> None:
    mm.posts = [_post(n) for n in range(6)] + [_post(7, user_id="ghost")]
    db = FakeDb()

    await ingest_mattermost_messages(db)  # type: ignore[arg-type]

    lookups = [r for r in mm.requests if r.url.path.endswith("/users/ids")]
    assert len(lookups) == 1
    assert httpx.Response(200, content=lookups[0].content).json() == ["ghost", "u0", "u1", "u2"]
    names = {row["mm_post_id"]: row["user_display_name"] for row in _rows(db.inserts[0])}
    assert names["p0000"] == "Duty Officer"  # nickname preferred
    assert names["p0001"] == "user-u1"
    assert names["p0007"] is None


# Failures -------------------------------------------------------------------


async def test_channel_auth_failure_is_counted_and_others_continue(
    mm: FakeMattermost, audit: AsyncMock
) -> None:
    mm.channels.append({"id": "chanB", "name": "b", "type": "O"})
    mm.fail_paths["/channels/chanA/posts"] = 403
    mm.posts = [_post(1)]
    db = FakeDb()

    result = await ingest_mattermost_messages(db)  # type: ignore[arg-type]

    assert (result.channels_polled, result.channels_failed) == (1, 1)
    assert db.states["chanB"].backfill_complete is True


async def test_channel_client_failure_is_counted(mm: FakeMattermost, audit: AsyncMock) -> None:
    mm.fail_paths["/channels/chanA/posts"] = 400
    result = await ingest_mattermost_messages(FakeDb())  # type: ignore[arg-type]
    assert (result.channels_polled, result.channels_failed) == (0, 1)


async def test_unreachable_mattermost_aborts_and_is_audited(
    audit: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mattermost_team", "jco")
    monkeypatch.setattr(settings, "mattermost_url", "")
    db = FakeDb()

    result = await ingest_mattermost_messages(db)  # type: ignore[arg-type]

    assert (result.channels_polled, result.channels_failed) == (0, 1)
    detail = audit.await_args.kwargs["detail"]
    assert detail["channels_failed"] == 1
    db.commit.assert_awaited_once()


async def test_audit_records_every_count(mm: FakeMattermost, audit: AsyncMock) -> None:
    mm.posts = [_post(1)]

    await ingest_mattermost_messages(  # type: ignore[arg-type]
        FakeDb(), user_id_actor="actor", ip_address="10.0.0.1"
    )

    kwargs = audit.await_args.kwargs
    assert kwargs["action_type"] == "mattermost.ingest"
    assert kwargs["user_id"] == "actor"
    assert kwargs["ip_address"] == "10.0.0.1"
    assert kwargs["detail"] == {
        "channels_polled": 1,
        "channels_failed": 0,
        "pulled": 1,
        "inserted": 1,
        "updated": 0,
        "deleted": 0,
        "skipped": 0,
    }


async def test_channel_name_lookup_failure_leaves_name_unset(
    mm: FakeMattermost, audit: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mattermost_channel_ids", "chanZ")
    mm.fail_paths["/channels/chanZ"] = 404
    db = FakeDb()

    await ingest_mattermost_messages(db)  # type: ignore[arg-type]

    assert db.states["chanZ"].channel_name is None


async def test_team_that_does_not_resolve_fails_the_cycle(
    mm: FakeMattermost, audit: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mattermost_team", "nosuchteam")
    db = FakeDb()

    result = await ingest_mattermost_messages(db)  # type: ignore[arg-type]

    assert db.states == {}
    assert (result.channels_polled, result.channels_failed) == (0, 1)
