"""Thin async wrapper around Mattermost's REST API.

We use Mattermost's `/api/v4` surface with a bot personal access token
(the dok.bot account). The bot must be a member of any channel we want
to poll; channels it isn't in respond 403 and the caller treats that as
"skip silently".

Rate-limit etiquette follows the standalone `mattermost_channel_pull`
tool: explicit timeouts, and bounded retries on 429 and 5xx that honour
`Retry-After`.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import quote

import httpx

from app.config import settings


class MattermostClientError(Exception):
    """Raised when a Mattermost request fails or returns an unexpected response."""


class MattermostAuthError(MattermostClientError):
    """Raised when Mattermost rejects the bot token."""


RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 4
PER_PAGE = 200  # API maximum for the posts and channels endpoints
USER_BATCH = 100  # user ids per /users/ids call
PAGE_PAUSE_S = 0.5  # courtesy pause between history pages
SEARCH_PER_PAGE = 100


def retry_delay(attempt: int, retry_after: Optional[str]) -> float:
    """Seconds to wait before retry `attempt` (1-based), honouring Retry-After."""
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            pass
    return float(2 ** (attempt - 1))


class MattermostClient:
    """Async client. Use as `async with MattermostClient() as mm: ...`."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        bot_token: Optional[str] = None,
        timeout: float = 30.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._base_url = (base_url or settings.mattermost_url).rstrip("/")
        self._bot_token = bot_token if bot_token is not None else settings.mattermost_bot_token
        self._timeout = timeout
        self._transport = transport
        self._sleep = sleep
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "MattermostClient":
        if not self._base_url or not self._bot_token:
            raise MattermostClientError(
                "Mattermost is not configured (MATTERMOST_URL / MATTERMOST_BOT_TOKEN)."
            )
        client_kwargs: dict[str, Any] = {
            "base_url": f"{self._base_url}/api/v4",
            "headers": {"Authorization": f"Bearer {self._bot_token}"},
            "timeout": self._timeout,
        }
        if self._transport is not None:
            client_kwargs["transport"] = self._transport
        self._client = httpx.AsyncClient(**client_kwargs)
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """One request with bounded retries on 429, 5xx and transport errors.

        The first MAX_ATTEMPTS - 1 tries back off and retry; the final try
        returns whatever it gets, so the caller maps the status to an error.
        """
        if self._client is None:
            raise MattermostClientError(
                "MattermostClient must be used as an async context manager."
            )
        client = self._client
        for attempt in range(1, MAX_ATTEMPTS):
            try:
                response = await client.request(method, path, **kwargs)
            except httpx.HTTPError:
                await self._sleep(retry_delay(attempt, None))
                continue
            if response.status_code not in RETRYABLE_STATUSES:
                return response
            await self._sleep(retry_delay(attempt, response.headers.get("Retry-After")))
        try:
            return await client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise MattermostClientError(f"Mattermost request failed: {exc}") from exc

    async def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        response = await self._send(method, path, **kwargs)
        if response.status_code == 401:
            raise MattermostAuthError("Mattermost rejected the bot token (401).")
        if response.status_code == 403:
            raise MattermostAuthError(
                f"Mattermost denied access ({response.status_code}): bot not in channel?"
            )
        if response.status_code >= 400:
            raise MattermostClientError(
                f"Mattermost returned HTTP {response.status_code}: {response.text[:200]}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise MattermostClientError(f"Mattermost returned invalid JSON: {exc}") from exc

    async def _get_json(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        return await self._json("GET", path, params=params)

    async def get_channel(self, channel_id: str) -> dict[str, Any]:
        return await self._get_json(f"/channels/{channel_id}")

    async def get_user(self, user_id: str) -> dict[str, Any]:
        return await self._get_json(f"/users/{user_id}")

    async def get_team_id(self, team_name: str) -> str:
        """Resolve a team URL name (e.g. "jco") to its id."""
        team = await self._get_json(f"/teams/name/{quote(team_name.strip().lower(), safe='')}")
        if not isinstance(team, dict) or not team.get("id"):
            raise MattermostClientError(f"Team '{team_name}' did not resolve to an id")
        return str(team["id"])

    async def get_my_team_channels(self, team_id: str) -> list[dict[str, Any]]:
        """Every channel the token holder belongs to in `team_id`.

        Includes private channels the bot has joined. Direct and group
        messages are not team channels and are not returned here.
        """
        channels: list[dict[str, Any]] = []
        page = 0
        while True:
            batch = await self._get_json(
                f"/users/me/teams/{team_id}/channels",
                params={"page": page, "per_page": PER_PAGE},
            )
            if not isinstance(batch, list):
                raise MattermostClientError("Channel listing returned an unexpected payload")
            channels.extend(c for c in batch if isinstance(c, dict))
            if len(batch) < PER_PAGE:
                return channels
            page += 1

    async def get_users_by_ids(self, user_ids: list[str]) -> list[dict[str, Any]]:
        """Batched user lookup. Batches that fail are skipped, not fatal."""
        users: list[dict[str, Any]] = []
        for i in range(0, len(user_ids), USER_BATCH):
            try:
                batch = await self._json("POST", "/users/ids", json=user_ids[i : i + USER_BATCH])
            except MattermostClientError:
                continue
            if isinstance(batch, list):
                users.extend(u for u in batch if isinstance(u, dict))
        return users

    async def get_channel_posts_before(
        self, channel_id: str, before: Optional[str], per_page: int = PER_PAGE
    ) -> dict[str, Any]:
        """One page of history older than post `before` (or the newest page
        when `before` is None), newest first. Used for backfill."""
        params: dict[str, Any] = {"page": 0, "per_page": per_page}
        if before:
            params["before"] = before
        return await self._get_json(f"/channels/{channel_id}/posts", params=params)

    async def get_users_by_usernames(self, usernames: list[str]) -> list[dict[str, Any]]:
        found = await self._json("POST", "/users/usernames", json=usernames)
        return [u for u in found if isinstance(u, dict)] if isinstance(found, list) else []

    async def search_users(self, term: str, team_id: Optional[str] = None) -> list[dict[str, Any]]:
        """People search by name, username or nickname (for picking authors)."""
        body: dict[str, Any] = {"term": term, "allow_inactive": True, "limit": 20}
        if team_id:
            body["team_id"] = team_id
        found = await self._json("POST", "/users/search", json=body)
        return [u for u in found if isinstance(u, dict)] if isinstance(found, list) else []

    async def get_post(self, post_id: str) -> dict[str, Any]:
        return await self._get_json(f"/posts/{post_id}")

    async def get_channel_by_name(self, team_id: str, name: str) -> dict[str, Any]:
        """Resolve a channel URL name in a team, archived channels included."""
        return await self._get_json(
            f"/teams/{team_id}/channels/name/{quote(name.strip().lower(), safe='')}",
            params={"include_deleted": "true"},
        )

    async def search_team_posts(
        self,
        team_id: str,
        terms: str,
        *,
        is_or_search: bool,
        include_archived: bool,
        page: int,
        per_page: int = SEARCH_PER_PAGE,
    ) -> dict[str, Any]:
        """Server-side post search in one team, newest first.

        Only channels the bot is a member of are searched. With
        `include_archived`, archived channels are searched too (the server
        must allow viewing archived channels).
        """
        return await self._json(
            "POST",
            f"/teams/{team_id}/posts/search",
            json={
                "terms": terms,
                "is_or_search": is_or_search,
                "time_zone_offset": 0,
                "include_deleted_channels": include_archived,
                "page": page,
                "per_page": per_page,
            },
        )

    async def pause(self) -> None:
        """Courtesy pause between consecutive history pages."""
        await self._sleep(PAGE_PAUSE_S)

    async def get_channel_posts_since(
        self,
        channel_id: str,
        since_ms: int,
        per_page: int = PER_PAGE,
    ) -> dict[str, Any]:
        """Get posts in a channel created or modified since `since_ms`.

        Returns Mattermost's native shape: `{posts: {id: {...}}, order: [id, ...]}`.
        Edited and deleted posts come back too, which is how edits and
        deletions reach the archive.
        """
        return await self._get_json(
            f"/channels/{channel_id}/posts",
            params={"since": since_ms, "per_page": per_page},
        )


def datetime_to_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def ms_to_datetime(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
