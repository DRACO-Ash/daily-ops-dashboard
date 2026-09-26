"""Serve the built frontend bundle from the backend.

Used by the single-container Bluestaq App Store deployment, where one
process answers both `/api/*` and the React single-page app. Client-side
routes (`/login`, `/shift-log`, ...) fall back to `index.html` so deep
links and browser refreshes work, and `GET /` returns 200 for the
platform readiness probe.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; font-src 'self' data:; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # Swagger UI (development only) loads its assets from a CDN.
        docs = request.url.path.startswith("/api/docs")
        for name, value in SECURITY_HEADERS.items():
            if docs and name == "Content-Security-Policy":
                continue
            response.headers.setdefault(name, value)
        return response


def resolve_static_path(root: Path, requested: str) -> Path:
    """Return the file to serve for `requested`, confined to `root`.

    Anything that is not an existing file inside `root` resolves to
    `index.html` so the React router can handle it.
    """
    root = root.resolve()
    index = root / "index.html"
    if not requested:
        return index
    candidate = (root / requested).resolve()
    if candidate.is_file() and candidate.is_relative_to(root):
        return candidate
    return index


def mount_spa(app: FastAPI, static_dir: str) -> bool:
    """Register the SPA catch-all route. Returns False if no bundle exists."""
    root = Path(static_dir)
    if not (root / "index.html").is_file():
        return False

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        return FileResponse(resolve_static_path(root, full_path))

    return True
