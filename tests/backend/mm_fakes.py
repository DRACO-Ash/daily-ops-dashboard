"""In-memory Mattermost and database fakes shared by the Mattermost tests.

FakeMattermost models the API behaviour the app relies on: history pages
newest first with a `before` cursor, and a team search that, like the
real one, is looser than the app's rules (it returns posts matching ANY
searched word), so tests prove the app's own literal filtering.
"""

import json
import re
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import httpx
from app.models.mattermost_ask import MattermostAsk, MattermostHistoryJob
from app.models.mattermost_message import MattermostChannelState
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Delete, Insert, Update
from sqlalchemy.sql.selectable import Select

BASE_MS = 1_740_000_000_000
TOKEN = re.compile(r'(\w+):(\S+)|"([^"]+)"|(\S+)')


def post(n: int, **overrides: Any) -> dict[str, Any]:
    body = {
        "id": f"p{n:04d}",
        "channel_id": "chanA",
        "user_id": f"u{n % 3}",
        "create_at": BASE_MS + n * 1000,
        "update_at": BASE_MS + n * 1000,
        "message": f"message {n}",
        "type": "",
        "root_id": "",
    }
    body.update(overrides)
    return body


class FakeMattermost:
    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []
        self.channels = [
            {"id": "chanA", "name": "jco_dok", "display_name": "JCO DOK", "type": "O"},
            {"id": "chanB", "name": "fusion", "display_name": "Fusion", "type": "P"},
            {
                "id": "chanZ",
                "name": "old_ops",
                "display_name": "Old ops",
                "type": "O",
                "delete_at": 99,
            },
        ]
        self.users = {
            "u0": {"username": "dok.bot", "nickname": "DOK"},
            "u1": {"username": "michael.sellick", "first_name": "Michael", "last_name": "Sellick"},
            "u2": {"username": "fusion.provider"},
        }
        self.requests: list[httpx.Request] = []
        self.fail_paths: dict[str, int] = {}
        self.sleeps: list[float] = []

    # Routing -----------------------------------------------------------------

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/api/v4")
        if path in self.fail_paths:
            return httpx.Response(self.fail_paths[path], json={"message": "nope"})
        body = json.loads(request.content) if request.content else None
        routed = self._route(path, request.url.params, body)
        return httpx.Response(404, json={"message": path}) if routed is None else routed

    def _route(self, path: str, params: httpx.QueryParams, body: Any) -> Optional[httpx.Response]:
        if path == "/teams/name/jco":
            return httpx.Response(200, json={"id": "team1", "name": "jco"})
        if path == "/users/me/teams/team1/channels":
            return httpx.Response(200, json=self.channels)
        if path == "/teams/team1/posts/search":
            return httpx.Response(200, json=self._search(body))
        if path.startswith("/teams/team1/channels/name/"):
            return self._channel(name=path.rsplit("/", 1)[1])
        if path in ("/users/ids", "/users/usernames"):
            key = "id" if path.endswith("ids") else "username"
            return httpx.Response(200, json=[u for u in self._user_list() if u[key] in body])
        if path == "/users/search":
            term = body["term"].casefold()
            return httpx.Response(
                200, json=[u for u in self._user_list() if term in str(u).casefold()]
            )
        if path.startswith("/posts/"):
            return self._post(path.split("/")[2])
        if path.endswith("/posts") and path.startswith("/channels/"):
            return httpx.Response(200, json=self._history(path.split("/")[2], params))
        if path.startswith("/channels/"):
            return self._channel(channel_id=path.split("/")[2])
        return None

    # Handlers ------------------------------------------------------------------

    def _user_list(self) -> list[dict[str, Any]]:
        return [{"id": uid, **info} for uid, info in self.users.items()]

    def _channel(self, name: str = "", channel_id: str = "") -> httpx.Response:
        for channel in self.channels:
            if channel["name"] == name or channel["id"] == channel_id:
                return httpx.Response(200, json=channel)
        return httpx.Response(404, json={"message": "no channel"})

    def _post(self, post_id: str) -> httpx.Response:
        for item in self.posts:
            if item["id"] == post_id:
                return httpx.Response(200, json=item)
        return httpx.Response(404, json={"message": "no post"})

    @staticmethod
    def _page(chosen: list[dict[str, Any]]) -> dict[str, Any]:
        return {"order": [p["id"] for p in chosen], "posts": {p["id"]: p for p in chosen}}

    def _newest_first(self) -> list[dict[str, Any]]:
        return sorted(self.posts, key=lambda p: p["create_at"], reverse=True)

    def _history(self, channel_id: str, params: httpx.QueryParams) -> dict[str, Any]:
        rows = [p for p in self._newest_first() if p["channel_id"] == channel_id]
        if "since" in params:
            return self._page([p for p in rows if p["update_at"] > int(params["since"])])
        rows = [p for p in rows if not p.get("delete_at")]
        if params.get("before"):
            ids = [p["id"] for p in rows]
            rows = rows[ids.index(params["before"]) + 1 :]
        return self._page(rows[: int(params["per_page"])])

    def _search(self, body: dict[str, Any]) -> dict[str, Any]:
        froms, ins, words = self._parse_terms(body["terms"])
        names = {c["id"]: c for c in self.channels}
        usernames = {uid: u["username"] for uid, u in self.users.items()}
        hits = [
            p
            for p in self._newest_first()
            if (not froms or usernames.get(p["user_id"]) in froms)
            and (not ins or names[p["channel_id"]]["name"] in ins)
            and (body["include_deleted_channels"] or not names[p["channel_id"]].get("delete_at"))
            and (not words or any(w in p["message"].casefold() for w in words))
        ]
        start = body["page"] * body["per_page"]
        return self._page(hits[start : start + body["per_page"]])

    @staticmethod
    def _parse_terms(terms: str) -> tuple[set[str], set[str], list[str]]:
        froms: set[str] = set()
        ins: set[str] = set()
        words: list[str] = []
        for key, value, phrase, word in TOKEN.findall(terms):
            if key == "from":
                froms.add(value)
            elif key == "in":
                ins.add(value)
            elif key in ("after", "before"):
                continue
            else:
                # Looser than the app: any single word of a phrase matches.
                words.extend((phrase or word).casefold().split())
        return froms, ins, words

    # Assertions helpers ----------------------------------------------------------

    def calls(self, suffix: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path.endswith(suffix)]


class FakeDb:
    """Records statements. Inserts into mattermost_message report every row
    as new unless its id is in `existing`; selects return `selected`."""

    def __init__(self) -> None:
        self.objects: dict[tuple[type, Any], Any] = {}
        self.existing: set[str] = set()
        self.selected: list[Any] = []
        self.statements: list[Any] = []
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.flush = AsyncMock()
        self.refresh = AsyncMock()

    def put(self, obj: Any) -> Any:
        key = obj.channel_id if isinstance(obj, MattermostChannelState) else obj.id
        self.objects[(type(obj), key)] = obj
        return obj

    async def get(self, model: type, key: Any) -> Any:
        return self.objects.get((model, key))

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        if isinstance(obj, (MattermostChannelState, MattermostAsk, MattermostHistoryJob)):
            self.put(obj)

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def execute(self, stmt: Any, *args: Any) -> MagicMock:
        self.statements.append(stmt)
        result = MagicMock()
        if isinstance(stmt, Insert) and stmt.table.name == "mattermost_message":
            ids = [row["mm_post_id"] for row in insert_rows(stmt)]
            result.scalars.return_value.all.return_value = [i not in self.existing for i in ids]
        elif isinstance(stmt, Select):
            result.scalars.return_value.all.return_value = list(self.selected)
            result.scalars.return_value.__iter__ = lambda _s: iter(list(self.selected))
        elif isinstance(stmt, (Update, Delete)):
            result.rowcount = 1
        return result

    def of(self, kind: type, table: str) -> list[Any]:
        return [s for s in self.statements if isinstance(s, kind) and s.table.name == table]

    def state(self, channel_id: str) -> MattermostChannelState:
        return self.objects[(MattermostChannelState, channel_id)]


def insert_rows(stmt: Insert) -> list[dict[str, Any]]:
    """The VALUES rows of a multi-row insert, by column name."""
    params = stmt.compile(dialect=postgresql.dialect()).params
    indexed = [k for k in params if re.search(r"_m\d+$", k)]
    if not indexed:  # a one-row VALUES compiles without the _mN suffix
        return [dict(params)]
    columns = sorted({k.rsplit("_m", 1)[0] for k in indexed})
    count = 1 + max(int(k.rsplit("_m", 1)[1]) for k in indexed)
    return [{c: params.get(f"{c}_m{i}") for c in columns} for i in range(count)]
