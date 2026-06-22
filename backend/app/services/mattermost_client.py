"""Thin async wrapper around Mattermost's REST API.

We use Mattermost's `/api/v4` surface with a bot personal access token.
The bot must be a member of any channel we want to poll; channels it
isn't in respond 403 and the caller treats that as "skip silently".
"""

from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app.config import settings


class MattermostClientError(Exception):
    """Raised when a Mattermost request fails or returns an unexpected response."""


class MattermostAuthError(MattermostClientError):
    """Raised when Mattermost rejects the bot token."""


class MattermostClient:
    """Async client. Use as `async with MattermostClient() as mm: ...`."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        bot_token: Optional[str] = None,
        timeout: float = 30.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._base_url = (base_url or settings.mattermost_url).rstrip("/")
        self._bot_token = bot_token if bot_token is not None else settings.mattermost_bot_token
        self._timeout = timeout
        self._transport = transport
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

    async def _get_json(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        if self._client is None:
            raise MattermostClientError(
                "MattermostClient must be used as an async context manager."
            )
        try:
            response = await self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise MattermostClientError(f"Mattermost request failed: {exc}") from exc
        if response.status_code == 401:
            raise MattermostAuthError("Mattermost rejected the bot token (401).")
        if response.status_code == 403:
            raise MattermostAuthError(
                f"Mattermost denied access ({response.status_code}): bot not in channel?"
            )
        if response.status_code >= 400:
            raise MattermostClientError(
                f"Mattermost returned HTTP {response.status_code}: {response.text}"
            )
        return response.json()

    async def get_channel(self, channel_id: str) -> dict[str, Any]:
        return await self._get_json(f"/channels/{channel_id}")

    async def get_user(self, user_id: str) -> dict[str, Any]:
        return await self._get_json(f"/users/{user_id}")

    async def get_channel_posts_since(
        self,
        channel_id: str,
        since_ms: int,
        per_page: int = 200,
    ) -> dict[str, Any]:
        """Get posts in a channel created since `since_ms` (epoch milliseconds).

        Returns Mattermost's native shape: `{posts: {id: {...}}, order: [id, ...]}`.
        `order` is newest-first.
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
