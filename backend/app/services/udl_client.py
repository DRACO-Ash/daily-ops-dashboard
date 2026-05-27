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
        if self._client is None:
            raise UDLClientError("UDLClient must be used as an async context manager.")

        params: dict[str, Any] = {"epoch": f">={_format_epoch(epoch_gte)}"}
        if sat_no is not None:
            params["satNo"] = sat_no
        if max_results is not None:
            params["maxResults"] = max_results

        try:
            response = await self._client.get("/elset", params=params)
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
