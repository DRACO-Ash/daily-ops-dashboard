from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app.config import settings


class UDLClientError(Exception):
    """Raised when a UDL request fails or returns an unexpected response."""


class UDLAuthError(UDLClientError):
    """Raised when UDL rejects the supplied credentials."""


def _format_epoch(dt: datetime) -> str:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class UDLClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: Optional[float] = None,
        verify_ssl: Optional[bool] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._base_url = (base_url or settings.udl_base_url).rstrip("/")
        self._username = username if username is not None else settings.udl_username
        self._password = password if password is not None else settings.udl_password
        self._timeout = timeout if timeout is not None else settings.udl_request_timeout_seconds
        self._verify_ssl = verify_ssl if verify_ssl is not None else settings.udl_verify_ssl
        self._transport = transport
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "UDLClient":
        if not self._username or not self._password:
            raise UDLClientError(
                "UDL credentials are not configured (UDL_USERNAME / UDL_PASSWORD)."
            )
        client_kwargs: dict[str, Any] = {
            "base_url": self._base_url,
            "auth": httpx.BasicAuth(self._username, self._password),
            "timeout": self._timeout,
            "verify": self._verify_ssl,
        }
        if self._transport is not None:
            client_kwargs["transport"] = self._transport
        self._client = httpx.AsyncClient(**client_kwargs)
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get_elsets(
        self,
        epoch_gte: datetime,
        sat_no: Optional[int] = None,
        max_results: Optional[int] = None,
    ) -> list[dict]:
        # UDL's elset endpoint rejects `>=` and only accepts `>` as the
        # interval operator (the notification endpoint behaves the same
        # way). The microsecond difference between strict-greater-than
        # and greater-than-or-equal is irrelevant in practice.
        params: dict[str, Any] = {"epoch": f">{_format_epoch(epoch_gte)}"}
        if sat_no is not None:
            params["satNo"] = sat_no
        if max_results is not None:
            params["maxResults"] = max_results
        return await self._get_list("/elset", params)

    async def get_notifications(
        self,
        msg_type: Optional[str] = None,
        created_at_gte: Optional[datetime] = None,
        data_mode: Optional[str] = None,
        source: Optional[str] = None,
        max_results: Optional[int] = None,
    ) -> list[dict]:
        params: dict[str, Any] = {}
        if msg_type is not None:
            params["msgType"] = msg_type
        if created_at_gte is not None:
            params["createdAt"] = f">{_format_epoch(created_at_gte)}"
        if data_mode is not None:
            params["dataMode"] = data_mode
        if source is not None:
            params["source"] = source
        if max_results is not None:
            params["maxResults"] = max_results
        return await self._get_list("/notification", params)

    async def _get_list(self, path: str, params: dict[str, Any]) -> list[dict]:
        if self._client is None:
            raise UDLClientError("UDLClient must be used as an async context manager.")

        try:
            response = await self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise UDLClientError(f"UDL request failed: {exc}") from exc

        if response.status_code == 401:
            raise UDLAuthError("UDL rejected credentials (401).")
        if response.status_code >= 400:
            raise UDLClientError(f"UDL returned HTTP {response.status_code}: {response.text[:200]}")

        try:
            data = response.json()
        except ValueError as exc:
            raise UDLClientError(f"UDL response was not valid JSON: {exc}") from exc

        if not isinstance(data, list):
            raise UDLClientError(f"UDL response was not a list (got {type(data).__name__}).")

        return data
