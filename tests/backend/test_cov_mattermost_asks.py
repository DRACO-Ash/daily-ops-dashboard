"""Mattermost asks: search building, literal filtering, thread shaping,
extraction, and the analyst's example asks run end to end."""

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from app.config import settings
from app.models.mattermost_ask import MattermostAsk
from app.schemas.mattermost import AskSpec
from app.services import mattermost_asks as asks
from app.services import mattermost_ingest as ingest
from app.services.mattermost_client import MattermostClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Delete, Insert

from .mm_fakes import BASE_MS, FakeDb, FakeMattermost, insert_rows, post

DOK, SELLICK, FUSION = "u0", "u1", "u2"


def _scenario(fake: FakeMattermost) -> None:
    fake.posts = [
        post(100, user_id=DOK, message="**NOTSO-2026-041 COSMOS 2589 anomaly**\nTasking follows"),
        post(
            101,
            user_id=FUSION,
            root_id="p0100",
            message="Possible solve: object 2589 brightness drop",
        ),
        post(
            102, user_id=FUSION, root_id="p0100", message="Verified solve: confirmed by two sensors"
        ),
        post(
            103, user_id=SELLICK, root_id="p0100", message="Photometric change noted on COSMOS 2589"
        ),
        post(200, user_id=DOK, message="### NOTSO-2026-042 SL-14 R/B\nPlease track"),
        post(201, user_id=FUSION, root_id="p0200", message="Possible solve issued"),
        post(202, user_id=FUSION, root_id="p0200", message="Possible solve revised"),
        post(300, user_id=SELLICK, channel_id="chanZ", message="COSMOS 2589 magnitude variation"),
        post(400, user_id=SELLICK, channel_id="chanB", message="Anyone for lunch?"),
        post(500, user_id=SELLICK, message="COSMOS 2589 orbit update, nothing unusual"),
        post(501, user_id=SELLICK, message="COSMOS 2589", type="system_header_change"),
    ]


@pytest.fixture
def mm(monkeypatch: pytest.MonkeyPatch) -> FakeMattermost:
    fake = FakeMattermost()
    _scenario(fake)

    async def _sleep(seconds: float) -> None:
        fake.sleeps.append(seconds)

    def _factory() -> MattermostClient:
        return MattermostClient(
            base_url="https://mm.test",
            bot_token="tok",
            transport=httpx.MockTransport(fake.handler),
            sleep=_sleep,
        )

    for module in (asks, ingest):
        monkeypatch.setattr(module, "MattermostClient", _factory)
    monkeypatch.setattr(settings, "mattermost_url", "https://mattermost.example")
    monkeypatch.setattr(settings, "mattermost_team", "jco")
    monkeypatch.setattr(settings, "mattermost_team_id", "")
    monkeypatch.setattr(settings, "mattermost_ask_max_pages", 20)
    return fake


@pytest.fixture
def audit(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock()
    for module in (asks, ingest):
        monkeypatch.setattr(module, "write_audit", mock)
    return mock


def _ask(db: FakeDb, **spec: Any) -> MattermostAsk:
    refresh = spec.pop("refresh_minutes", None)
    ask = MattermostAsk(
        id=uuid.uuid4(),
        name="test",
        spec=AskSpec(**spec).model_dump(mode="json"),
        refresh_minutes=refresh,
        next_run_at=datetime.now(timezone.utc) - timedelta(seconds=5),
        result_count=0,
    )
    db.selected = [ask]
    return ask


def _results(db: FakeDb) -> list[dict[str, Any]]:
    inserts = db.of(Insert, "mattermost_ask_result")
    return [row for stmt in inserts for row in insert_rows(stmt)]


async def _run(db: FakeDb, **spec: Any) -> tuple[MattermostAsk, list[dict[str, Any]]]:
    ask = _ask(db, **spec)
    assert await asks.run_due_asks(db) == 1  # type: ignore[arg-type]
    return ask, sorted(_results(db), key=lambda r: r["posted_at"])


def _ids(rows: list[dict[str, Any]]) -> list[str]:
    return [r["mm_post_id"] for r in rows]


# The analyst's example asks ----------------------------------------------------------


async def test_when_each_thread_was_started(mm: FakeMattermost, audit: AsyncMock) -> None:
    ask, rows = await _run(FakeDb(), channels=["jco_dok"], scope="thread_starts")

    assert _ids(rows) == ["p0100", "p0200", "p0500"]
    first = rows[0]
    assert first["thread_started_at"] == datetime.fromtimestamp(
        (BASE_MS + 100_000) / 1000, tz=timezone.utc
    )
    assert first["thread_title"] == "NOTSO-2026-041 COSMOS 2589 anomaly"
    assert rows[1]["thread_title"] == "NOTSO-2026-042 SL-14 R/B"
    assert not mm.calls("/posts/search")  # channel-only asks walk history
    assert (ask.last_status, ask.result_count) == ("ok", 3)


async def test_thread_id_from_the_title(mm: FakeMattermost, audit: AsyncMock) -> None:
    _, rows = await _run(
        FakeDb(),
        channels=["jco_dok"],
        scope="thread_starts",
        extract={"pattern": r"(NOTSO-\d{4}-\d{3})", "source": "thread_title"},
    )
    assert [r["extracted"] for r in rows] == ["NOTSO-2026-041", "NOTSO-2026-042", None]


async def test_when_the_fusion_provider_released_a_possible_solve(
    mm: FakeMattermost, audit: AsyncMock
) -> None:
    _, rows = await _run(
        FakeDb(), terms=["Possible solve"], authors=["fusion.provider"], scope="first_per_thread"
    )

    assert _ids(rows) == ["p0101", "p0201"]  # earliest per thread, not p0202
    assert [r["thread_id"] for r in rows] == ["p0100", "p0200"]
    assert rows[0]["thread_title"] == "NOTSO-2026-041 COSMOS 2589 anomaly"
    assert rows[0]["author"] == "fusion.provider"
    search = mm.calls("/posts/search")[0]
    assert b'"terms": "\\"Possible solve\\" from:fusion.provider"' in search.content


async def test_when_the_fusion_provider_released_a_verified_solve(
    mm: FakeMattermost, audit: AsyncMock
) -> None:
    _, rows = await _run(
        FakeDb(), terms=["Verified solve"], authors=["fusion.provider"], scope="first_per_thread"
    )
    assert _ids(rows) == ["p0102"]


async def test_all_posts_by_one_person_across_all_channels(
    mm: FakeMattermost, audit: AsyncMock
) -> None:
    _, rows = await _run(FakeDb(), authors=["michael.sellick"])

    assert _ids(rows) == ["p0103", "p0300", "p0400", "p0500"]  # system post excluded
    archived = {r["mm_post_id"]: r["channel_archived"] for r in rows}
    assert archived == {"p0103": False, "p0300": True, "p0400": False, "p0500": False}


async def test_archived_channels_are_left_out_when_asked(
    mm: FakeMattermost, audit: AsyncMock
) -> None:
    _, rows = await _run(FakeDb(), authors=["michael.sellick"], include_archived=False)
    assert "p0300" not in _ids(rows)
    assert b'"include_deleted_channels": false' in mm.calls("/posts/search")[0].content


async def test_photometric_changes_on_cosmos_2589_in_open_and_closed_channels(
    mm: FakeMattermost, audit: AsyncMock
) -> None:
    _, rows = await _run(
        FakeDb(),
        terms=["COSMOS 2589"],
        any_terms=["photometric", "brightness", "magnitude"],
        include_archived=True,
    )

    # p0101 mentions brightness but not COSMOS 2589; p0100 and p0500 mention
    # COSMOS 2589 but nothing photometric. The looser server search returns
    # all of them; the literal filter keeps only true matches.
    assert _ids(rows) == ["p0103", "p0300"]
    assert rows[1]["channel_name"] == "Old ops"
    assert rows[1]["channel_archived"] is True


# Behaviour ----------------------------------------------------------------------------


async def test_run_archives_matches_replaces_results_and_audits(
    mm: FakeMattermost, audit: AsyncMock
) -> None:
    db = FakeDb()
    ask, rows = await _run(db, terms=["Verified solve"])

    assert [s.table.name for s in db.statements if isinstance(s, Delete)] == [
        "mattermost_ask_result"
    ]
    archived = [
        r["mm_post_id"] for s in db.of(Insert, "mattermost_message") for r in insert_rows(s)
    ]
    assert archived == ["p0102"]
    assert rows[0]["permalink"] == "https://mattermost.example/jco/pl/p0102"
    assert rows[0]["excerpt"] == "Verified solve: confirmed by two sensors"
    assert ask.next_run_at is None  # one-off
    detail = audit.await_args.kwargs["detail"]
    assert (detail["status"], detail["results"]) == ("ok", 1)
    db.commit.assert_awaited()


async def test_refreshing_ask_schedules_its_next_run(mm: FakeMattermost, audit: AsyncMock) -> None:
    ask, _ = await _run(FakeDb(), terms=["Verified solve"], refresh_minutes=60)
    assert ask.last_run_at is not None and ask.next_run_at is not None
    assert ask.next_run_at - ask.last_run_at == timedelta(minutes=60)


async def test_no_matches_clears_old_results(mm: FakeMattermost, audit: AsyncMock) -> None:
    db = FakeDb()
    ask, rows = await _run(db, terms=["no such phrase anywhere"])
    assert rows == []
    assert ask.result_count == 0
    assert db.of(Delete, "mattermost_ask_result")


async def test_unknown_username_fails_loudly(mm: FakeMattermost, audit: AsyncMock) -> None:
    db = FakeDb()
    ask, rows = await _run(db, authors=["Michael Sellick", "fusion.provider"])

    assert ask.last_status == "failed"
    assert ask.last_error == "Unknown Mattermost username: Michael Sellick"
    assert rows == [] and not db.of(Delete, "mattermost_ask_result")  # old results kept
    assert not mm.calls("/posts/search")


async def test_unknown_channel_fails_loudly(mm: FakeMattermost, audit: AsyncMock) -> None:
    ask, _ = await _run(FakeDb(), terms=["x"], channels=["jco_dokk"])
    assert (ask.last_status, ask.last_error) == ("failed", "Unknown channel: jco_dokk")


async def test_hitting_the_page_cap_marks_the_run_partial(
    mm: FakeMattermost, audit: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mattermost_ask_max_pages", 1)
    mm.posts += [post(1000 + n, message=f"flood {n}") for n in range(150)]

    ask, rows = await _run(FakeDb(), terms=["flood"])

    assert ask.last_status == "partial"
    assert "narrow the ask" in (ask.last_error or "")
    assert len(rows) == 100


async def test_history_walk_stops_at_the_page_cap_and_the_after_date(
    mm: FakeMattermost, audit: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    day_ms = 86_400_000
    mm.posts = [
        post(n, create_at=BASE_MS + n * day_ms, update_at=BASE_MS + n * day_ms) for n in range(450)
    ]
    monkeypatch.setattr(settings, "mattermost_ask_max_pages", 1)
    ask, _ = await _run(FakeDb(), channels=["jco_dok"])
    assert ask.last_status == "partial"

    monkeypatch.setattr(settings, "mattermost_ask_max_pages", 20)
    cutoff = datetime.fromtimestamp((BASE_MS + 300 * day_ms) / 1000, tz=timezone.utc).date()
    calls_before = len(mm.calls("/channels/chanA/posts"))
    ask, rows = await _run(FakeDb(), channels=["jco_dok"], after=cutoff)

    assert ask.last_status == "ok"
    # Page 1 holds posts 449..250; the oldest predates the cutoff, so stop.
    assert len(mm.calls("/channels/chanA/posts")) - calls_before == 1
    assert len(rows) == 150
    assert all(r["posted_at"].date() >= cutoff for r in rows)


async def test_archived_channel_skipped_in_history_walk_when_excluded(
    mm: FakeMattermost, audit: AsyncMock
) -> None:
    ask, rows = await _run(FakeDb(), channels=["old_ops"], include_archived=False)
    assert (ask.last_status, rows) == ("ok", [])
    assert not mm.calls("/channels/chanZ/posts")


async def test_missing_thread_root_leaves_thread_fields_empty(
    mm: FakeMattermost, audit: AsyncMock
) -> None:
    mm.posts = [p for p in mm.posts if p["id"] != "p0200"]
    _, rows = await _run(FakeDb(), terms=["Possible solve"], scope="first_per_thread")
    orphan = next(r for r in rows if r["thread_id"] == "p0200")
    assert (orphan["thread_title"], orphan["thread_started_at"]) == (None, None)


async def test_unresolvable_channel_metadata_keeps_the_result(
    mm: FakeMattermost, audit: AsyncMock
) -> None:
    mm.fail_paths["/channels/chanB"] = 500
    _, rows = await _run(FakeDb(), terms=["lunch"])
    assert rows[0]["channel_name"] is None


async def test_nothing_due_means_no_calls(mm: FakeMattermost, audit: AsyncMock) -> None:
    db = FakeDb()
    assert await asks.run_due_asks(db) == 0  # type: ignore[arg-type]
    assert mm.requests == []


async def test_unconfigured_mattermost_fails_due_asks(
    audit: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mattermost_url", "")
    db = FakeDb()
    ask = _ask(db, terms=["x"], refresh_minutes=30)

    await asks.run_due_asks(db)  # type: ignore[arg-type]

    assert ask.last_status == "failed"
    assert "not configured" in (ask.last_error or "")
    assert ask.next_run_at is not None  # retried at the next refresh
    db.commit.assert_awaited()


async def test_missing_team_fails_the_ask(
    mm: FakeMattermost, audit: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mattermost_team", "")
    ask, _ = await _run(FakeDb(), terms=["x"])
    assert (ask.last_status, ask.last_error) == ("failed", "MATTERMOST_TEAM is not configured")


# Pure helpers ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "terms", "is_or"),
    [
        (AskSpec(terms=["COSMOS 2589", "photometric"]), '"COSMOS 2589" photometric', False),
        (AskSpec(any_terms=["flare", "glint"]), "flare glint", True),
        (AskSpec(any_terms=["flare"]), "flare", False),
        (AskSpec(terms=["a"], any_terms=["b", "c"]), "a", False),
        (
            AskSpec(authors=["@michael.sellick"], channels=["~jco_dok"]),
            "from:michael.sellick in:jco_dok",
            False,
        ),
        (
            AskSpec(terms=["x"], after=date(2026, 3, 1), before=date(2026, 3, 31)),
            "x after:2026-02-28 before:2026-04-01",
            False,
        ),
    ],
)
def test_build_search(spec: AskSpec, terms: str, is_or: bool) -> None:
    assert asks.build_search(spec) == (terms, is_or)


def test_matches_terms_is_literal_and_case_insensitive() -> None:
    spec = AskSpec(terms=["COSMOS 2589"], any_terms=["photometric", "flare"])
    assert asks.matches_terms("cosmos 2589 FLARE seen", spec)
    assert not asks.matches_terms("COSMOS 2589 orbit", spec)
    assert not asks.matches_terms("photometric on COSMOS 25", spec)
    assert asks.matches_terms("anything", AskSpec(authors=["a"]))


def test_in_window_is_inclusive_of_both_dates() -> None:
    spec = AskSpec(terms=["x"], after=date(2026, 3, 1), before=date(2026, 3, 1))
    day = datetime(2026, 3, 1, tzinfo=timezone.utc)

    def at(moment: datetime) -> dict[str, Any]:
        return {"create_at": int(moment.timestamp() * 1000)}

    assert asks.in_window(at(day), spec)
    assert asks.in_window(at(day + timedelta(hours=23, minutes=59)), spec)
    assert not asks.in_window(at(day - timedelta(seconds=1)), spec)
    assert not asks.in_window(at(day + timedelta(days=1)), spec)


@pytest.mark.parametrize(
    ("message", "title"),
    [
        ("**NOTSO-1 thing**\nbody", "NOTSO-1 thing"),
        ("\n\n### Heading _here_\n", "Heading here"),
        ("> quoted `code`", "quoted code"),
        ("   \n", ""),
        ("x" * 400, "x" * 300),
    ],
)
def test_thread_title(message: str, title: str) -> None:
    assert asks.thread_title(message) == title


def test_extract_group_whole_match_missing_and_bounded_input() -> None:
    grouped = AskSpec(terms=["x"], extract={"pattern": r"ID-(\d+)"})
    whole = AskSpec(terms=["x"], extract={"pattern": r"ID-\d+"})
    assert asks.extract(grouped, "see ID-42 now", "") == "42"
    assert asks.extract(whole, "see ID-42 now", "") == "ID-42"
    assert asks.extract(grouped, "nothing", "") is None
    assert asks.extract(AskSpec(terms=["x"]), "ID-42", "") is None
    late = "a" * asks.MAX_EXTRACT_INPUT + "ID-9"
    assert asks.extract(grouped, late, "") is None  # beyond the scanned prefix


def test_permalink_needs_url_and_team(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mattermost_url", "https://mm.example/")
    monkeypatch.setattr(settings, "mattermost_team", "jco")
    assert asks.permalink("p1") == "https://mm.example/jco/pl/p1"
    monkeypatch.setattr(settings, "mattermost_team", "")
    assert asks.permalink("p1") is None


def test_result_insert_targets_the_results_table() -> None:
    stmt = postgresql.insert(asks.MattermostAskResult).values([{"mm_post_id": "p"}])
    assert "mattermost_ask_result" in str(stmt.compile(dialect=postgresql.dialect()))
