from pathlib import Path

import pytest
from app.core.spa import (
    SECURITY_HEADERS,
    SecurityHeadersMiddleware,
    mount_spa,
    resolve_static_path,
)
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text("<html>app</html>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "main.js").write_text("console.log(1)")
    (tmp_path.parent / "secret.txt").write_text("nope")
    return tmp_path


def _app(static_dir: Path) -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/api/v1/ping")
    async def ping() -> dict:
        return {"ok": True}

    assert mount_spa(app, str(static_dir))
    return app


def test_resolve_static_path_serves_existing_file(bundle: Path) -> None:
    assert resolve_static_path(bundle, "assets/main.js") == (bundle / "assets/main.js").resolve()


def test_resolve_static_path_falls_back_to_index(bundle: Path) -> None:
    index = (bundle / "index.html").resolve()
    assert resolve_static_path(bundle, "") == index
    assert resolve_static_path(bundle, "shift-log") == index
    assert resolve_static_path(bundle, "../secret.txt") == index


def test_mount_spa_without_bundle_is_noop(tmp_path: Path) -> None:
    app = FastAPI()
    assert mount_spa(app, str(tmp_path / "missing")) is False


@pytest.mark.asyncio
async def test_root_returns_200_with_security_headers(bundle: Path) -> None:
    transport = ASGITransport(app=_app(bundle))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        root = await client.get("/")
        head = await client.head("/")
        deep = await client.get("/notifications/123")
        asset = await client.get("/assets/main.js")
        api = await client.get("/api/v1/ping")
        missing_api = await client.get("/api/v1/does-not-exist")

    assert root.status_code == 200
    assert root.text == "<html>app</html>"
    assert head.status_code == 200
    for name, value in SECURITY_HEADERS.items():
        assert root.headers[name] == value
    assert deep.status_code == 200
    assert deep.text == "<html>app</html>"
    assert asset.text == "console.log(1)"
    assert api.json() == {"ok": True}
    assert missing_api.status_code == 404


@pytest.mark.asyncio
async def test_docs_path_skips_csp(bundle: Path) -> None:
    transport = ASGITransport(app=_app(bundle))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/docs")
    assert "Content-Security-Policy" not in response.headers
    assert response.headers["X-Frame-Options"] == "DENY"
