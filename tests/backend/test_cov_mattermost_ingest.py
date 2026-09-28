"""Mattermost archive storage and on-demand full-history jobs."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from app.config import settings
from app.models.mattermost_ask import MattermostHistoryJob
from app.models.mattermost_message import MattermostChannelState
from app.services import mattermost_ingest as ingest
from app.services.mattermost_client import PER_PAGE, MattermostClient
from app.services.mattermost_ingest import (
    Channel,
    Tally,
    _highest_update,
    is_ingestible,
    run_history_jobs,
    selectable_channels,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Insert, Update

from .mm_fakes import BASE_MS, FakeDb, FakeMattermost, insert_rows, post


@pytest.fixture
def mm(monkeypatch: pytest.MonkeyPatch) -> FakeMattermost:
    fake = FakeMattermost()

    async def _sleep(seconds: float) -> None:
        fake.sleeps.append(seconds)

    def _factory() -> MattermostClient:
        return MattermostClient(
            base_url="https://mm.test",
            bot_token="tok",
            transport=httpx.MockTransport(fake.handler),
            sleep=_sleep,
        )

    monkeypatch.setattr(ingest, "MattermostClient", _factory)
    monkeypatch.setattr(settings, "mattermost_team", "jco")
    monkeypatch.setattr(settings, "mattermost_team_id", "")
    monkeypatch.setattr(settings, "mattermost_backfill_pages_per_cycle", 10)
    return fake


@pytest.fixture
def audit(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock()
    monkeypatch.setattr(ingest, "write_audit", mock)
    return mock


def _job(db: FakeDb, **overrides: Any) -> MattermostHistoryJob:
    job = MattermostHistoryJob(
        id=uuid.uuid4(),
        channel_ids=[],
        run_after=datetime.now(timezone.utc) - timedelta(minutes=1),
        status="scheduled",
        counts={},
        failed_channel_ids=[],
        requested_by=uuid.uuid4(),
    )
    for key, value in overrides.items():
        setattr(job, key, value)
    db.selected = [job]
    return job


def _stored_ids(db: FakeDb) -> list[str]:
    return [
        row["mm_post_id"] for s in db.of(Insert, "mattermost_message") for row in insert_rows(s)
    ]


# Pure helpers ---------------------------------------------------------------------


def test_selectable_channels_keeps_live_team_channels_only() -> None:
    channels = [
        {"id": "o", "type": "O", "display_name": "Ops", "name": "ops"},
        {"id": "p", "type": "P", "name": "private"},
        {"id": "d", "type": "D"},
        {"id": "x", "type": "O", "delete_at": 99},
        {"type": "O"},
    ]
    assert selectable_channels(channels) == [Channel("o", "Ops"), Channel("p", "private")]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"type": "", "create_at": 1, "message": "hi"}, True),
        ({"type": "system_join_channel", "create_at": 1, "message": "joined"}, False),
        ({"type": "", "create_at": "1", "message": "hi"}, False),
        ({"type": "", "create_at": 1, "message": "   "}, False),
    ],
)
def test_is_ingestible(body: dict[str, Any], expected: bool) -> None:
    assert is_ingestible(body) is expected


def test_highest_update_ignores_non_integer_stamps() -> None:
    posts = [{"update_at": 5}, {"create_at": 9}, {"update_at": "12"}, {}]
    assert _highest_update(posts, 7) == 9


def test_tally_adds_into_existing_counts() -> None:
    assert Tally(pulled=2, inserted=1).add_to({"pulled": 3, "other": 1}) == {
        "pulled": 5,
        "inserted": 1,
        "updated": 0,
        "deleted": 0,
        "skipped": 0,
        "other": 1,
    }


# Scheduling -----------------------------------------------------------------------


async def test_no_due_jobs_does_nothing(mm: FakeMattermost, audit: AsyncMock) -> None:
    db = FakeDb()
    assert await run_history_jobs(db) == 0  # type: ignore[arg-type]
    assert mm.requests == []
    audit.assert_not_awaited()


async def test_due_query_filters_on_status_and_start_time(
    mm: FakeMattermost, audit: AsyncMock
) -> None:
    db = FakeDb()
    await run_history_jobs(db)  # type: ignore[arg-type]
    sql = str(db.statements[0].compile(dialect=postgresql.dialect()))
    assert "mattermost_history_job.status IN" in sql
    assert "mattermost_history_job.run_after <=" in sql


# Full history ---------------------------------------------------------------------


async def test_job_pulls_the_full_history_of_every_bot_channel(
    mm: FakeMattermost, audit: AsyncMock
) -> None:
    mm.posts = [post(n) for n in range(450)] + [post(900 + n, channel_id="chanB") for n in range(3)]
    db = FakeDb()
    job = _job(db)

    await run_history_jobs(db)  # type: ignore[arg-type]

    assert job.channel_ids == ["chanA", "chanB"]  # archived chanZ excluded
    assert sorted(_stored_ids(db)) == sorted(p["id"] for p in mm.posts)
    assert (job.status, job.counts["pulled"], job.counts["inserted"]) == ("done", 453, 453)
    assert db.state("chanA").backfill_complete is True
    assert db.state("chanA").backfill_cursor == "p0000"
    assert db.state("chanA").channel_name == "JCO DOK"
    befores = [r.url.params.get("before") for r in mm.calls("/channels/chanA/posts")]
    assert befores == [None, "p0250", "p0050"]
    assert mm.sleeps == [0.5, 0.5]
    actions = [c.kwargs["action_type"] for c in audit.await_args_list]
    assert actions == ["mattermost.history.start", "mattermost.history.finish"]
    assert audit.await_args.kwargs["user_id"] == job.requested_by
    db.commit.assert_awaited()


async def test_job_for_named_channels_only_touches_those(
    mm: FakeMattermost, audit: AsyncMock
) -> None:
    mm.posts = [post(1), post(2, channel_id="chanB")]
    db = FakeDb()
    job = _job(db, channel_ids=["chanB"])

    await run_history_jobs(db)  # type: ignore[arg-type]

    assert _stored_ids(db) == ["p0002"]
    assert job.status == "done"
    assert not mm.calls("/users/me/teams/team1/channels")


async def test_page_cap_spreads_a_job_over_cycles(
    mm: FakeMattermost, audit: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mattermost_backfill_pages_per_cycle", 1)
    mm.posts = [post(n) for n in range(450)]
    db = FakeDb()
    job = _job(db, channel_ids=["chanA"])

    await run_history_jobs(db)  # type: ignore[arg-type]
    assert (job.status, len(_stored_ids(db))) == ("running", PER_PAGE)

    mm.posts.append(post(999))  # arrives mid-job; the cursor walk is unaffected
    await run_history_jobs(db)  # type: ignore[arg-type]
    await run_history_jobs(db)  # type: ignore[arg-type]

    assert job.status == "done"
    assert set(_stored_ids(db)) >= {p["id"] for p in mm.posts if p["id"] != "p0999"}
    assert job.counts["pulled"] == 450
    assert audit.await_count == 2  # start and finish only, not every cycle


async def test_rerun_restarts_a_completed_channel_from_the_newest_post(
    mm: FakeMattermost, audit: AsyncMock
) -> None:
    mm.posts = [post(1)]
    db = FakeDb()
    db.put(
        MattermostChannelState(
            channel_id="chanA", watermark_ms=5, backfill_cursor="old", backfill_complete=True
        )
    )
    _job(db, channel_ids=["chanA"])

    await run_history_jobs(db)  # type: ignore[arg-type]

    assert mm.calls("/channels/chanA/posts")[0].url.params.get("before") is None
    assert _stored_ids(db) == ["p0001"]


async def test_edits_and_deletions_are_archived_not_dropped(
    mm: FakeMattermost, audit: AsyncMock
) -> None:
    mm.posts = [
        post(1, message="corrected", update_at=BASE_MS + 9_000, edit_at=BASE_MS + 9_000),
        post(2, type="system_join_channel"),
        post(3, root_id="p0001"),
    ]
    db = FakeDb()
    db.existing = {"p0001"}
    job = _job(db, channel_ids=["chanA"])

    await run_history_jobs(db)  # type: ignore[arg-type]

    rows = {r["mm_post_id"]: r for s in db.of(Insert, "mattermost_message") for r in insert_rows(s)}
    assert rows["p0001"]["message"] == "corrected"
    assert rows["p0003"]["root_id"] == "p0001"
    assert (job.counts["inserted"], job.counts["updated"], job.counts["skipped"]) == (1, 1, 1)
    sql = str(db.of(Insert, "mattermost_message")[0].compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT ON CONSTRAINT uq_mattermost_message_post_id DO UPDATE" in sql
    assert "WHERE excluded.mm_updated_at > coalesce(mattermost_message.mm_updated_at" in sql
    assert "RETURNING (xmax = 0)" in sql


async def test_deleted_posts_keep_their_text(mm: FakeMattermost, audit: AsyncMock) -> None:
    cycle = ingest.Cycle(db=FakeDb(), client=AsyncMock())  # type: ignore[arg-type]
    deleted = post(4, message="", delete_at=BASE_MS + 50)

    await ingest.store_posts(cycle, Channel("chanA", "JCO DOK"), [deleted])

    update = cycle.db.of(Update, "mattermost_message")[0]  # type: ignore[attr-defined]
    sql = str(update.compile(dialect=postgresql.dialect()))
    assert "deleted_at IS NULL" in sql
    assert "message" not in sql.split("SET")[1].split("WHERE")[0]
    assert cycle.tally.deleted == 1


async def test_author_names_are_batched_and_nickname_preferred(
    mm: FakeMattermost, audit: AsyncMock
) -> None:
    mm.posts = [post(n) for n in range(6)] + [post(7, user_id="ghost")]
    db = FakeDb()
    _job(db, channel_ids=["chanA"])

    await run_history_jobs(db)  # type: ignore[arg-type]

    assert len(mm.calls("/users/ids")) == 1
    names = {
        r["mm_post_id"]: r["user_display_name"]
        for r in insert_rows(db.of(Insert, "mattermost_message")[0])
    }
    assert (names["p0000"], names["p0001"], names["p0007"]) == ("DOK", "michael.sellick", None)


# Failures -------------------------------------------------------------------------


async def test_failed_channel_is_skipped_and_the_job_still_finishes(
    mm: FakeMattermost, audit: AsyncMock
) -> None:
    mm.fail_paths["/channels/chanA/posts"] = 403
    mm.posts = [post(1, channel_id="chanB")]
    db = FakeDb()
    job = _job(db, channel_ids=["chanA", "chanB"])

    await run_history_jobs(db)  # type: ignore[arg-type]

    assert (job.status, job.failed_channel_ids) == ("done", ["chanA"])
    assert "chanA" in (job.error or "")
    assert _stored_ids(db) == ["p0001"]


async def test_job_fails_when_every_channel_fails(mm: FakeMattermost, audit: AsyncMock) -> None:
    mm.fail_paths["/channels/chanA/posts"] = 500
    db = FakeDb()
    job = _job(db, channel_ids=["chanA"])

    await run_history_jobs(db)  # type: ignore[arg-type]

    assert job.status == "failed"
    assert audit.await_args.kwargs["detail"]["status"] == "failed"


async def test_channel_name_lookup_failure_leaves_the_name_unset(
    mm: FakeMattermost, audit: AsyncMock
) -> None:
    mm.fail_paths["/channels/chanA"] = 404
    db = FakeDb()
    _job(db, channel_ids=["chanA"])

    await run_history_jobs(db)  # type: ignore[arg-type]

    assert db.state("chanA").channel_name is None


@pytest.mark.parametrize(("team", "team_id"), [("", ""), ("nosuchteam", "")])
async def test_unresolvable_team_fails_the_job(
    mm: FakeMattermost,
    audit: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
    team: str,
    team_id: str,
) -> None:
    monkeypatch.setattr(settings, "mattermost_team", team)
    monkeypatch.setattr(settings, "mattermost_team_id", team_id)
    db = FakeDb()
    job = _job(db)

    await run_history_jobs(db)  # type: ignore[arg-type]

    assert job.status == "failed"
    assert job.finished_at is not None
    db.commit.assert_awaited()


async def test_team_id_setting_skips_the_name_lookup(
    mm: FakeMattermost, audit: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mattermost_team", "")
    monkeypatch.setattr(settings, "mattermost_team_id", "team1")
    db = FakeDb()
    job = _job(db)

    await run_history_jobs(db)  # type: ignore[arg-type]

    assert not mm.calls("/teams/name/jco")
    assert job.status == "done"


async def test_unconfigured_client_fails_the_job(
    audit: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mattermost_url", "")
    db = FakeDb()
    job = _job(db, status="running", channel_ids=["chanA"])

    await run_history_jobs(db)  # type: ignore[arg-type]

    assert job.status == "failed"
    assert "not configured" in (job.error or "")


async def test_failed_channel_is_not_retried_on_later_cycles(
    mm: FakeMattermost, audit: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mattermost_backfill_pages_per_cycle", 1)
    mm.channels.append({"id": "chanC", "name": "small", "type": "O"})
    mm.fail_paths["/channels/chanA/posts"] = 403
    mm.posts = [post(n, channel_id="chanB") for n in range(250)] + [post(900, channel_id="chanC")]
    db = FakeDb()
    job = _job(db, channel_ids=["chanA", "chanB", "chanC"])

    await run_history_jobs(db)  # type: ignore[arg-type]
    assert job.status == "running"
    assert db.state("chanC").backfill_complete is True
    chan_a_calls = len(mm.calls("/channels/chanA/posts"))
    chan_c_calls = len(mm.calls("/channels/chanC/posts"))

    await run_history_jobs(db)  # type: ignore[arg-type]

    assert job.status == "done"
    assert job.failed_channel_ids == ["chanA"]
    assert len(mm.calls("/channels/chanA/posts")) == chan_a_calls  # not retried
    assert len(mm.calls("/channels/chanC/posts")) == chan_c_calls  # already complete
