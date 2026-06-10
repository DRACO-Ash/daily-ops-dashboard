import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.config import settings

_PREVIEW_MAX_BYTES = 64 * 1024
_PREVIEWABLE_TYPES = {"text/plain", "text/markdown", "application/json", "text/csv"}


@dataclass(frozen=True)
class StoredFile:
    path: Path
    size_bytes: int
    file_hash: str


def _root() -> Path:
    return Path(settings.procedure_storage_path)


def _path_for(procedure_id: uuid.UUID, filename: str) -> Path:
    suffix = Path(filename).suffix
    return _root() / f"{procedure_id}{suffix}"


def write_file(procedure_id: uuid.UUID, filename: str, data: bytes) -> StoredFile:
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    path = _path_for(procedure_id, filename)
    path.write_bytes(data)
    return StoredFile(
        path=path,
        size_bytes=len(data),
        file_hash=hashlib.sha256(data).hexdigest(),
    )


def delete_file(procedure_id: uuid.UUID, filename: str) -> None:
    path = _path_for(procedure_id, filename)
    if path.exists():
        os.remove(path)


def read_file_bytes(procedure_id: uuid.UUID, filename: str) -> bytes:
    return _path_for(procedure_id, filename).read_bytes()


def read_preview(
    procedure_id: uuid.UUID,
    filename: str,
    content_type: str,
) -> tuple[Optional[str], bool]:
    """Return (text content, truncated flag) for previewable types, else (None, False)."""
    if content_type not in _PREVIEWABLE_TYPES:
        return None, False
    path = _path_for(procedure_id, filename)
    if not path.exists():
        return None, False
    raw = path.read_bytes()
    truncated = len(raw) > _PREVIEW_MAX_BYTES
    snippet = raw[:_PREVIEW_MAX_BYTES]
    try:
        return snippet.decode("utf-8"), truncated
    except UnicodeDecodeError:
        return snippet.decode("utf-8", errors="replace"), truncated
