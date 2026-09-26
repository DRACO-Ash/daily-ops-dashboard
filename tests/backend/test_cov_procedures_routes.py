import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.v1.routes import procedures as procedure_routes
from app.config import settings
from app.db.session import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.procedure import Procedure
from app.models.user import User, UserRole
from app.services import procedure_storage
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError


def _make_user(role: UserRole = UserRole.OPERATOR) -> User:
    now = datetime.now(timezone.utc)
    return User(
        id=uuid.uuid4(),
        username=f"user-{role.value}",
        email=None,
        password_hash="not-used-in-this-test",
        role=role.value,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def _procedure(filename: str = "checklist.md", content_type: str = "text/markdown") -> Procedure:
    now = datetime(2027, 1, 1, tzinfo=timezone.utc)
    return Procedure(
        id=uuid.uuid4(),
        name="Launch checklist",
        description=None,
        filename=filename,
        content_type=content_type,
        size_bytes=10,
        file_hash="f" * 64,
        uploaded_by=None,
        created_at=now,
        updated_at=now,
    )


def _fill_db_defaults(obj: Any) -> None:
    now = datetime.now(timezone.utc)
    if obj.id is None:
        obj.id = uuid.uuid4()
    if obj.created_at is None:
        obj.created_at = now
    if obj.updated_at is None:
        obj.updated_at = now


def _scalar(value: Any) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _session(results: list[Any], flush_error: Optional[Exception] = None) -> AsyncMock:
    session = AsyncMock()
    session.added = []
    session.execute = AsyncMock(side_effect=results)
    session.add = MagicMock(side_effect=session.added.append)

    async def _flush() -> None:
        if flush_error is not None:
            raise flush_error
        for obj in session.added:
            _fill_db_defaults(obj)

    async def _refresh(obj: Any) -> None:
        _fill_db_defaults(obj)

    session.flush = AsyncMock(side_effect=_flush)
    session.refresh = AsyncMock(side_effect=_refresh)
    return session


def _install(session: AsyncMock, user: Optional[User] = None) -> User:
    async def _get_db():
        yield session

    current = user or _make_user()

    async def _get_user():
        return current

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _get_user
    return current


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _restore_overrides():
    prior_db = app.dependency_overrides.get(get_db)
    prior_user = app.dependency_overrides.get(get_current_user)
    yield
    if prior_db is not None:
        app.dependency_overrides[get_db] = prior_db
    else:
        app.dependency_overrides.pop(get_db, None)
    if prior_user is not None:
        app.dependency_overrides[get_current_user] = prior_user
    else:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(autouse=True)
def storage_root(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(settings, "procedure_storage_path", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def audit_calls(monkeypatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_write_audit(db, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(procedure_routes, "write_audit", fake_write_audit)
    return calls


# Authentication ------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/procedures"),
        ("get", f"/api/v1/procedures/{uuid.uuid4()}"),
        ("get", f"/api/v1/procedures/{uuid.uuid4()}/download"),
        ("delete", f"/api/v1/procedures/{uuid.uuid4()}"),
    ],
)
async def test_procedure_routes_require_authentication(method: str, path: str) -> None:
    async with _client() as client:
        response = await getattr(client, method)(path)

    assert response.status_code == 401


# List ----------------------------------------------------------


async def test_list_procedures_returns_items_and_total() -> None:
    rows = [_procedure(), _procedure("runbook.pdf", "application/pdf")]
    items = MagicMock()
    items.scalars.return_value.all.return_value = rows
    total = MagicMock()
    total.scalar_one.return_value = 2
    _install(_session([items, total]), _make_user(UserRole.ANALYST))

    async with _client() as client:
        response = await client.get("/api/v1/procedures")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [item["filename"] for item in body["items"]] == ["checklist.md", "runbook.pdf"]


# Get / preview -------------------------------------------------


async def test_get_procedure_inlines_text_content() -> None:
    proc = _procedure()
    procedure_storage.write_file(proc.id, proc.filename, b"# Step 1\nCheck comms.")
    _install(_session([_scalar(proc)]))

    async with _client() as client:
        response = await client.get(f"/api/v1/procedures/{proc.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(proc.id)
    assert body["content"] == "# Step 1\nCheck comms."
    assert body["content_truncated"] is False


async def test_get_procedure_binary_type_has_no_content() -> None:
    proc = _procedure("runbook.pdf", "application/pdf")
    procedure_storage.write_file(proc.id, proc.filename, b"%PDF-1.7")
    _install(_session([_scalar(proc)]))

    async with _client() as client:
        response = await client.get(f"/api/v1/procedures/{proc.id}")

    assert response.status_code == 200
    assert response.json()["content"] is None


async def test_get_procedure_with_missing_file_still_returns_metadata() -> None:
    proc = _procedure()
    _install(_session([_scalar(proc)]))

    async with _client() as client:
        response = await client.get(f"/api/v1/procedures/{proc.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Launch checklist"
    assert body["content"] is None
    assert body["content_truncated"] is False


@pytest.mark.parametrize("suffix", ["", "/download"])
async def test_get_and_download_missing_procedure_return_404(suffix: str) -> None:
    _install(_session([_scalar(None)]))

    async with _client() as client:
        response = await client.get(f"/api/v1/procedures/{uuid.uuid4()}{suffix}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Procedure not found"


async def test_get_procedure_rejects_non_uuid() -> None:
    _install(_session([]))

    async with _client() as client:
        response = await client.get("/api/v1/procedures/not-a-uuid")

    assert response.status_code == 422


# Download ------------------------------------------------------


async def test_download_streams_stored_bytes_with_headers() -> None:
    proc = _procedure("runbook.pdf", "application/pdf")
    payload = b"%PDF-1.7 binary \x00\xff"
    procedure_storage.write_file(proc.id, proc.filename, payload)
    _install(_session([_scalar(proc)]))

    async with _client() as client:
        response = await client.get(f"/api/v1/procedures/{proc.id}/download")

    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == (
        "attachment; filename=\"runbook.pdf\"; filename*=UTF-8''runbook.pdf"
    )


async def test_download_escapes_quotes_and_non_ascii_in_filename() -> None:
    proc = _procedure('ops "final" é.txt', "text/plain")
    procedure_storage.write_file(proc.id, proc.filename, b"x")
    _install(_session([_scalar(proc)]))

    async with _client() as client:
        response = await client.get(f"/api/v1/procedures/{proc.id}/download")

    assert response.headers["content-disposition"] == (
        'attachment; filename="ops _final_ _.txt"; '
        "filename*=UTF-8''ops%20%22final%22%20%C3%A9.txt"
    )


async def test_download_missing_file_returns_404() -> None:
    proc = _procedure("gone.pdf", "application/pdf")
    _install(_session([_scalar(proc)]))

    async with _client() as client:
        response = await client.get(f"/api/v1/procedures/{proc.id}/download")

    assert response.status_code == 404
    assert response.json()["detail"] == "Procedure file not found"


# Upload --------------------------------------------------------


async def test_upload_writes_file_persists_row_and_audits(
    storage_root: Path, audit_calls: list[dict[str, Any]]
) -> None:
    session = _session([])
    user = _install(session)
    data = b"# Conjunction response\n1. Page the duty officer.\n"

    async with _client() as client:
        response = await client.post(
            "/api/v1/procedures",
            data={"name": "  Conjunction response  ", "description": "  CDM playbook  "},
            files={"file": ("conjunction.md", data, "text/markdown")},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Conjunction response"
    assert body["description"] == "CDM playbook"
    assert body["filename"] == "conjunction.md"
    assert body["content_type"] == "text/markdown"
    assert body["size_bytes"] == len(data)
    assert body["file_hash"] == hashlib.sha256(data).hexdigest()
    assert body["uploaded_by"] == str(user.id)
    stored = [p for p in storage_root.iterdir() if p.is_file()]
    assert len(stored) == 1
    assert stored[0].read_bytes() == data
    assert stored[0].suffix == ".md"
    assert stored[0].name == f"{body['id']}.md"
    session.commit.assert_awaited_once()
    assert audit_calls[0]["action_type"] == "procedure.upload"
    assert audit_calls[0]["entity_id"] == body["id"]
    assert audit_calls[0]["detail"] == {
        "name": "Conjunction response",
        "filename": "conjunction.md",
        "size_bytes": len(data),
    }


async def test_upload_without_description_stores_null() -> None:
    _install(_session([]))

    async with _client() as client:
        response = await client.post(
            "/api/v1/procedures",
            data={"name": "Plain"},
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )

    assert response.status_code == 201
    assert response.json()["description"] is None


async def test_upload_rejects_empty_file(
    storage_root: Path, audit_calls: list[dict[str, Any]]
) -> None:
    session = _session([])
    _install(session)

    async with _client() as client:
        response = await client.post(
            "/api/v1/procedures",
            data={"name": "Empty"},
            files={"file": ("empty.txt", b"", "text/plain")},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Uploaded file is empty"
    assert list(storage_root.iterdir()) == []
    session.add.assert_not_called()
    assert audit_calls == []


async def test_upload_rejects_oversized_file(storage_root: Path) -> None:
    session = _session([])
    _install(session)
    too_big = b"x" * (procedure_routes.MAX_UPLOAD_BYTES + 1)

    async with _client() as client:
        response = await client.post(
            "/api/v1/procedures",
            data={"name": "Huge"},
            files={"file": ("huge.txt", too_big, "text/plain")},
        )

    assert response.status_code == 413
    assert response.json()["detail"] == "File exceeds 10MB limit"
    assert list(storage_root.iterdir()) == []
    session.add.assert_not_called()


async def test_upload_duplicate_content_returns_409_and_cleans_up(
    storage_root: Path, audit_calls: list[dict[str, Any]]
) -> None:
    session = _session([], flush_error=IntegrityError("INSERT", {}, Exception("dup hash")))
    _install(session)

    async with _client() as client:
        response = await client.post(
            "/api/v1/procedures",
            data={"name": "Duplicate"},
            files={"file": ("dup.txt", b"same bytes", "text/plain")},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "A procedure with identical content already exists"
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
    assert list(storage_root.iterdir()) == []
    assert audit_calls == []


@pytest.mark.parametrize(
    ("data", "files"),
    [
        ({}, {"file": ("a.txt", b"x", "text/plain")}),
        ({"name": "No file"}, None),
    ],
)
async def test_upload_requires_name_and_file(
    data: dict[str, str], files: Optional[dict[str, Any]], storage_root: Path
) -> None:
    _install(_session([]))

    async with _client() as client:
        response = await client.post("/api/v1/procedures", data=data, files=files)

    assert response.status_code == 422
    assert list(storage_root.iterdir()) == []


# Delete --------------------------------------------------------


async def test_delete_removes_file_row_and_audits(
    storage_root: Path, audit_calls: list[dict[str, Any]]
) -> None:
    proc = _procedure()
    stored = procedure_storage.write_file(proc.id, proc.filename, b"bytes")
    session = _session([_scalar(proc)])
    user = _install(session)

    async with _client() as client:
        response = await client.delete(f"/api/v1/procedures/{proc.id}")

    assert response.status_code == 204
    assert not stored.path.exists()
    session.delete.assert_awaited_once_with(proc)
    session.commit.assert_awaited_once()
    assert audit_calls == [
        {
            "action_type": "procedure.delete",
            "entity_type": "procedure",
            "entity_id": str(proc.id),
            "user_id": user.id,
            "ip_address": "127.0.0.1",
            "detail": {"name": "Launch checklist", "filename": "checklist.md"},
        }
    ]


async def test_delete_succeeds_when_file_already_gone(audit_calls: list[dict[str, Any]]) -> None:
    proc = _procedure()
    session = _session([_scalar(proc)])
    _install(session)

    async with _client() as client:
        response = await client.delete(f"/api/v1/procedures/{proc.id}")

    assert response.status_code == 204
    session.delete.assert_awaited_once_with(proc)
    assert audit_calls[0]["action_type"] == "procedure.delete"


async def test_delete_missing_procedure_returns_404(
    storage_root: Path, audit_calls: list[dict[str, Any]]
) -> None:
    other = procedure_storage.write_file(uuid.uuid4(), "keep.txt", b"keep")
    session = _session([_scalar(None)])
    _install(session)

    async with _client() as client:
        response = await client.delete(f"/api/v1/procedures/{uuid.uuid4()}")

    assert response.status_code == 404
    assert other.path.exists()
    session.delete.assert_not_awaited()
    assert audit_calls == []
