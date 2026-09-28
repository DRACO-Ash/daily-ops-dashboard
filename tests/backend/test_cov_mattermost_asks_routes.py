"""Mattermost asks and history-job routes: roles, validation, CSV, audit."""

import csv
import io
import uuid
from datetime import datetime, timezone
from typing import Any, Iterator
from unittest.mock import AsyncMock

import pytest
from app.api.v1.routes import mattermost_asks as routes
from app.db.session import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.mattermost_ask import MattermostAsk, MattermostAskResult, MattermostHistoryJob
from app.models.mattermost_message import MattermostChannelState
from app.models.user import User, UserRole
from app.schemas.mattermost import AskSpec, AskSuggestion
from app.services.mattermost_client import MattermostClientError
from app.services.mattermost_suggest import SuggestError
from httpx import ASGITransport, AsyncClient

from .mm_fakes import FakeDb

NOW = datetime(2026, 9, 28, 9, 0, tzinfo=timezone.utc)
SPEC = {"terms": ["Verified solve"], "authors": ["fusion.provider"], "scope": "first_per_thread"}


def _user(role: UserRole) -> User:
    return User(
        id=uuid.uuid4(),
        username=role.value,
        password_hash="x",
        role=role.value,
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def _ask(**overrides: Any) -> MattermostAsk:
    ask = MattermostAsk(
        id=uuid.uuid4(),
        name="Verified solves",
        question=None,
        spec=AskSpec(**SPEC).model_dump(mode="json"),
        refresh_minutes=None,
        result_count=0,
        created_at=NOW,
        updated_at=NOW,
    )
    for key, value in overrides.items():
        setattr(ask, key, value)
    return ask


def _job(**overrides: Any) -> MattermostHistoryJob:
    job = MattermostHistoryJob(
        id=uuid.uuid4(),
        channel_ids=["chanA"],
        run_after=NOW,
        status="scheduled",
        counts={},
        failed_channel_ids=[],
        created_at=NOW,
        updated_at=NOW,
    )
    for key, value in overrides.items():
        setattr(job, key, value)
    return job


def _result(n: int, **overrides: Any) -> MattermostAskResult:
    row = MattermostAskResult(
        mm_post_id=f"p{n}",
        channel_id="chanA",
        channel_name="JCO DOK",
        channel_archived=False,
        thread_id="p0",
        thread_title="NOTSO-1",
        thread_started_at=NOW,
        author="fusion.provider",
        posted_at=NOW,
        extracted=None,
        excerpt=f"Verified solve {n}",
        permalink=f"https://mm/jco/pl/p{n}",
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


class RouteDb(FakeDb):
    """FakeDb whose flush assigns ids and timestamps like the database."""

    def __init__(self) -> None:
        super().__init__()
        self.flush = AsyncMock(side_effect=self._assign_defaults)

    async def _assign_defaults(self) -> None:
        for obj in self.added:
            obj.id = obj.id or uuid.uuid4()
            obj.created_at = obj.created_at or NOW
            obj.updated_at = obj.updated_at or NOW


@pytest.fixture
def db() -> Iterator[RouteDb]:
    fake = RouteDb()

    async def _get_db():
        yield fake

    prior = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = _get_db
    yield fake
    app.dependency_overrides.clear()
    app.dependency_overrides.update(prior)


@pytest.fixture
def audit(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock()
    monkeypatch.setattr(routes, "write_audit", mock)
    return mock


def _as(role: UserRole) -> User:
    user = _user(role)

    async def _current():
        return user

    app.dependency_overrides[get_current_user] = _current
    return user


async def _call(method: str, url: str, **kwargs: Any):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, f"/api/v1/mattermost{url}", **kwargs)


# Roles -------------------------------------------------------------------------------

WRITES = [
    ("POST", "/asks", {"json": {"name": "n", "spec": SPEC}}),
    ("PUT", f"/asks/{uuid.uuid4()}", {"json": {"name": "n", "spec": SPEC}}),
    ("DELETE", f"/asks/{uuid.uuid4()}", {}),
    ("POST", f"/asks/{uuid.uuid4()}/run", {}),
    ("POST", f"/asks/{uuid.uuid4()}/unschedule", {}),
    ("POST", "/asks/suggest", {"json": {"question": "verified solves"}}),
    ("GET", "/users?q=mi", {}),
    ("POST", "/history-jobs", {"json": {}}),
    ("POST", f"/history-jobs/{uuid.uuid4()}/cancel", {}),
]


@pytest.mark.parametrize(("method", "url", "kwargs"), WRITES)
async def test_analysts_cannot_write(db: RouteDb, method: str, url: str, kwargs: dict) -> None:
    _as(UserRole.ANALYST)
    response = await _call(method, url, **kwargs)
    assert response.status_code == 403


async def test_reads_need_a_signed_in_user(db: RouteDb) -> None:
    assert (await _call("GET", "/asks")).status_code == 401


# Asks CRUD ---------------------------------------------------------------------------


async def test_operator_creates_an_ask_and_it_is_audited(db: RouteDb, audit: AsyncMock) -> None:
    user = _as(UserRole.OPERATOR)
    response = await _call(
        "POST",
        "/asks",
        json={"name": "  Verified solves ", "question": "q", "spec": SPEC, "refresh_minutes": 60},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Verified solves"
    assert body["spec"]["authors"] == ["fusion.provider"]
    assert body["spec"]["include_archived"] is True
    saved = db.added[0]
    assert (saved.created_by, saved.refresh_minutes) == (user.id, 60)
    kwargs = audit.await_args.kwargs
    assert (kwargs["action_type"], kwargs["user_id"]) == ("mattermost.ask.create", user.id)
    db.commit.assert_awaited()


async def test_invalid_spec_is_rejected(db: RouteDb, audit: AsyncMock) -> None:
    _as(UserRole.ADMIN)
    response = await _call("POST", "/asks", json={"name": "n", "spec": {"scope": "posts"}})
    assert response.status_code == 422
    assert db.added == []


async def test_list_get_update_and_delete(db: RouteDb, audit: AsyncMock) -> None:
    _as(UserRole.ADMIN)
    ask = db.put(_ask())
    db.selected = [ask]

    assert [a["id"] for a in (await _call("GET", "/asks")).json()] == [str(ask.id)]
    assert (await _call("GET", f"/asks/{ask.id}")).json()["name"] == "Verified solves"

    updated = await _call(
        "PUT",
        f"/asks/{ask.id}",
        json={"name": "Renamed", "spec": {**SPEC, "terms": ["Possible solve"]}},
    )
    assert updated.status_code == 200
    assert (ask.name, ask.spec["terms"]) == ("Renamed", ["Possible solve"])

    assert (await _call("DELETE", f"/asks/{ask.id}")).status_code == 204
    assert db.deleted == [ask]
    actions = [c.kwargs["action_type"] for c in audit.await_args_list]
    assert actions == ["mattermost.ask.update", "mattermost.ask.delete"]


async def test_missing_ask_is_404(db: RouteDb) -> None:
    _as(UserRole.ADMIN)
    assert (await _call("GET", f"/asks/{uuid.uuid4()}")).status_code == 404


# Running -----------------------------------------------------------------------------


async def test_run_now_queues_for_the_next_cycle(db: RouteDb, audit: AsyncMock) -> None:
    _as(UserRole.OPERATOR)
    ask = db.put(_ask())

    response = await _call("POST", f"/asks/{ask.id}/run")

    assert response.status_code == 200
    assert response.json()["last_status"] == "queued"
    assert ask.next_run_at is not None
    assert (datetime.now(timezone.utc) - ask.next_run_at).total_seconds() < 5


async def test_run_at_a_chosen_time(db: RouteDb, audit: AsyncMock) -> None:
    _as(UserRole.OPERATOR)
    ask = db.put(_ask())

    response = await _call(
        "POST", f"/asks/{ask.id}/run", params={"run_at": "2026-10-01T06:30:00+01:00"}
    )

    assert response.status_code == 200
    assert ask.next_run_at == datetime(2026, 10, 1, 5, 30, tzinfo=timezone.utc)
    assert audit.await_args.kwargs["detail"] == {"run_at": "2026-10-01T06:30:00+01:00"}


async def test_run_at_without_timezone_is_rejected(db: RouteDb) -> None:
    _as(UserRole.OPERATOR)
    ask = db.put(_ask())
    response = await _call("POST", f"/asks/{ask.id}/run", params={"run_at": "2026-10-01T06:30:00"})
    assert response.status_code == 422
    assert ask.next_run_at is None


async def test_unschedule_clears_the_next_run(db: RouteDb, audit: AsyncMock) -> None:
    _as(UserRole.OPERATOR)
    ask = db.put(_ask(next_run_at=NOW))
    assert (await _call("POST", f"/asks/{ask.id}/unschedule")).json()["next_run_at"] is None


# Results -----------------------------------------------------------------------------


async def test_results_are_paged(db: RouteDb) -> None:
    _as(UserRole.ANALYST)
    ask = db.put(_ask())
    db.selected = [_result(1), _result(2)]

    async def _execute(stmt: Any, *args: Any):
        result = await FakeDb.execute(db, stmt)
        result.scalar_one.return_value = 7
        return result

    db.execute = _execute  # type: ignore[method-assign]
    response = await _call("GET", f"/asks/{ask.id}/results", params={"limit": 2, "offset": 4})

    body = response.json()
    assert (body["total"], body["limit"], body["offset"]) == (7, 2, 4)
    assert [i["mm_post_id"] for i in body["items"]] == ["p1", "p2"]
    assert body["items"][0]["thread_title"] == "NOTSO-1"


async def test_csv_export_neutralises_formulas(db: RouteDb) -> None:
    _as(UserRole.ANALYST)
    ask = db.put(_ask(name="Verified / solves!"))
    db.selected = [_result(1), _result(2, excerpt='=HYPERLINK("http://evil")', author="@bob")]

    response = await _call("GET", f"/asks/{ask.id}/results.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert 'filename="Verified___solves_.csv"' in response.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows[0]["excerpt"] == "Verified solve 1"
    assert rows[0]["posted_at"] == NOW.isoformat()
    assert rows[1]["excerpt"] == '\'=HYPERLINK("http://evil")'
    assert rows[1]["author"] == "'@bob"
    assert rows[0]["extracted"] == ""


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, ""), ("+1", "'+1"), ("-1", "'-1"), ("\tx", "'\tx"), ("safe", "safe"), (3, "3")],
)
def test_csv_cell(value: Any, expected: str) -> None:
    assert routes.csv_cell(value) == expected


# Suggest -----------------------------------------------------------------------------


async def test_suggest_returns_a_draft_without_saving(
    db: RouteDb, audit: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _as(UserRole.OPERATOR)
    monkeypatch.setattr(routes, "_live_channels", AsyncMock(return_value=[{"name": "jco_dok"}, {}]))
    draft = AskSuggestion(name="n", spec=AskSpec(**SPEC), explanation="e")
    fake_suggest = AsyncMock(return_value=draft)
    monkeypatch.setattr(routes, "suggest_ask", fake_suggest)

    response = await _call("POST", "/asks/suggest", json={"question": "verified solves"})

    assert response.status_code == 200
    assert response.json()["spec"]["scope"] == "first_per_thread"
    fake_suggest.assert_awaited_once_with("verified solves", ["jco_dok"])
    assert db.added == []
    assert audit.await_args.kwargs["detail"] == {"question": "verified solves"}


async def test_suggest_works_without_mattermost_and_reports_model_failure(
    db: RouteDb, audit: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _as(UserRole.OPERATOR)
    monkeypatch.setattr(routes, "_live_channels", AsyncMock(side_effect=MattermostClientError("x")))
    fake_suggest = AsyncMock(side_effect=SuggestError("The model declined"))
    monkeypatch.setattr(routes, "suggest_ask", fake_suggest)

    response = await _call("POST", "/asks/suggest", json={"question": "verified solves"})

    assert (response.status_code, response.json()["detail"]) == (502, "The model declined")
    assert fake_suggest.await_args.args[1] == []


# Channels and people -----------------------------------------------------------------


async def test_channels_include_archived_and_history_status(
    db: RouteDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    _as(UserRole.ANALYST)
    raw = [
        {"id": "b", "name": "zeta", "display_name": "Zeta", "type": "P"},
        {"id": "a", "name": "alpha", "type": "O", "delete_at": 5},
        {"id": "c", "name": "beta", "type": "O"},
        {"id": "d", "name": "dm", "type": "D"},
    ]
    monkeypatch.setattr(routes, "_live_channels", AsyncMock(return_value=raw))
    db.selected = [MattermostChannelState(channel_id="b", backfill_complete=True, watermark_ms=0)]

    body = (await _call("GET", "/channels")).json()

    assert [c["name"] for c in body] == ["beta", "zeta", "alpha"]  # live first, then archived
    assert body[1] == {
        "id": "b",
        "name": "zeta",
        "display_name": "Zeta",
        "type": "P",
        "archived": False,
        "history_complete": True,
    }
    assert body[2]["archived"] is True


async def test_channels_report_mattermost_failure(
    db: RouteDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    _as(UserRole.ANALYST)
    monkeypatch.setattr(
        routes, "_live_channels", AsyncMock(side_effect=MattermostClientError("down"))
    )
    response = await _call("GET", "/channels")
    assert (response.status_code, response.json()["detail"]) == (502, "down")


class _FakeClient:
    users: list[dict[str, Any]] = []
    fail = False

    async def __aenter__(self) -> "_FakeClient":
        if self.fail:
            raise MattermostClientError("unreachable")
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def get_team_id(self, _name: str) -> str:
        return "team1"

    async def search_users(self, term: str, team_id: str) -> list[dict[str, Any]]:
        assert (term, team_id) == ("sellick", "team1")
        return self.users

    async def get_my_team_channels(self, team_id: str) -> list[dict[str, Any]]:
        return [{"id": "x", "team": team_id}]


async def test_people_search_maps_names(db: RouteDb, monkeypatch: pytest.MonkeyPatch) -> None:
    _as(UserRole.OPERATOR)
    _FakeClient.users = [
        {"username": "michael.sellick", "first_name": "Michael", "last_name": "Sellick"},
        {"username": "m.s", "nickname": "Mike"},
    ]
    _FakeClient.fail = False
    monkeypatch.setattr(routes, "MattermostClient", _FakeClient)
    monkeypatch.setattr(routes, "team_id", lambda client: client.get_team_id("jco"))

    body = (await _call("GET", "/users", params={"q": "sellick"})).json()

    assert body == [
        {"username": "michael.sellick", "name": "Michael Sellick", "nickname": None},
        {"username": "m.s", "name": None, "nickname": "Mike"},
    ]


async def test_people_search_reports_mattermost_failure(
    db: RouteDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    _as(UserRole.OPERATOR)
    _FakeClient.fail = True
    monkeypatch.setattr(routes, "MattermostClient", _FakeClient)
    assert (await _call("GET", "/users", params={"q": "sellick"})).status_code == 502


async def test_live_channels_uses_the_team(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeClient.fail = False
    monkeypatch.setattr(routes, "MattermostClient", _FakeClient)
    monkeypatch.setattr(routes, "team_id", lambda client: client.get_team_id("jco"))
    assert await routes._live_channels() == [{"id": "x", "team": "team1"}]


# History jobs ------------------------------------------------------------------------


async def test_request_full_history_now(db: RouteDb, audit: AsyncMock) -> None:
    user = _as(UserRole.OPERATOR)

    response = await _call("POST", "/history-jobs", json={"channel_ids": ["chanA"]})

    assert response.status_code == 201
    job = db.added[0]
    assert (job.status, job.channel_ids, job.requested_by) == ("scheduled", ["chanA"], user.id)
    assert (datetime.now(timezone.utc) - job.run_after).total_seconds() < 5
    assert audit.await_args.kwargs["action_type"] == "mattermost.history.request"


async def test_request_full_history_at_a_chosen_time(db: RouteDb, audit: AsyncMock) -> None:
    _as(UserRole.ADMIN)
    response = await _call(
        "POST", "/history-jobs", json={"channel_ids": [], "run_after": "2026-10-03T02:00:00Z"}
    )
    assert response.json()["run_after"].startswith("2026-10-03T02:00:00")
    assert db.added[0].channel_ids == []  # all of the bot's channels


async def test_full_history_needs_a_timezone(db: RouteDb) -> None:
    _as(UserRole.ADMIN)
    response = await _call("POST", "/history-jobs", json={"run_after": "2026-10-03T02:00:00"})
    assert response.status_code == 422
    assert db.added == []


async def test_list_and_cancel_jobs(db: RouteDb, audit: AsyncMock) -> None:
    _as(UserRole.OPERATOR)
    job = db.put(_job())
    db.selected = [job]

    assert [j["id"] for j in (await _call("GET", "/history-jobs")).json()] == [str(job.id)]
    cancelled = await _call("POST", f"/history-jobs/{job.id}/cancel")

    assert cancelled.json()["status"] == "cancelled"
    assert job.finished_at is not None
    assert audit.await_args.kwargs["action_type"] == "mattermost.history.cancel"


async def test_cancel_finished_or_missing_job(db: RouteDb) -> None:
    _as(UserRole.OPERATOR)
    done = db.put(_job(status="done"))
    assert (await _call("POST", f"/history-jobs/{done.id}/cancel")).status_code == 409
    assert (await _call("POST", f"/history-jobs/{uuid.uuid4()}/cancel")).status_code == 404
