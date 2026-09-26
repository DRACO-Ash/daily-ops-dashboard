import hashlib
import uuid
from pathlib import Path

import pytest
from app.config import settings
from app.services import procedure_storage as storage


@pytest.fixture(autouse=True)
def storage_root(monkeypatch, tmp_path: Path) -> Path:
    root = tmp_path / "procedures"
    monkeypatch.setattr(settings, "procedure_storage_path", str(root))
    return root


def test_write_file_creates_root_and_returns_metadata(storage_root: Path) -> None:
    proc_id = uuid.uuid4()
    data = b"# Launch checklist\n"

    stored = storage.write_file(proc_id, "checklist.md", data)

    assert storage_root.is_dir()
    assert stored.path == storage_root / f"{proc_id}.md"
    assert stored.path.read_bytes() == data
    assert stored.size_bytes == len(data)
    assert stored.file_hash == hashlib.sha256(data).hexdigest()


def test_write_file_overwrites_existing_content(storage_root: Path) -> None:
    proc_id = uuid.uuid4()
    storage.write_file(proc_id, "a.txt", b"first")

    stored = storage.write_file(proc_id, "a.txt", b"second")

    assert stored.path.read_bytes() == b"second"
    assert list(storage_root.iterdir()) == [stored.path]


@pytest.mark.parametrize(
    ("filename", "expected_suffix"),
    [
        ("../../etc/passwd", ""),
        ("../../../tmp/evil.sh", ".sh"),
        ("/absolute/path/report.pdf", ".pdf"),
        ("report.tar.gz", ".gz"),
        (".bashrc", ""),
        ("trailing.", ""),
        ("UPPER.PDF", ".PDF"),
        ("no_extension", ""),
        ("spaces in name .md", ".md"),
        ("a.b\\..\\x", ".\\x"),
    ],
)
def test_stored_path_never_leaves_root(
    storage_root: Path, filename: str, expected_suffix: str
) -> None:
    proc_id = uuid.uuid4()

    stored = storage.write_file(proc_id, filename, b"payload")

    assert stored.path.parent == storage_root
    assert stored.path.name == f"{proc_id}{expected_suffix}"
    assert stored.path.resolve().is_relative_to(storage_root.resolve())
    assert storage.read_file_bytes(proc_id, filename) == b"payload"


def test_delete_file_removes_file(storage_root: Path) -> None:
    proc_id = uuid.uuid4()
    other_id = uuid.uuid4()
    stored = storage.write_file(proc_id, "doc.txt", b"x")
    keep = storage.write_file(other_id, "doc.txt", b"y")

    storage.delete_file(proc_id, "doc.txt")

    assert not stored.path.exists()
    assert keep.path.exists()


def test_delete_file_missing_is_silent(storage_root: Path) -> None:
    storage.delete_file(uuid.uuid4(), "never-written.txt")
    assert not storage_root.exists()


def test_read_file_bytes_missing_raises(storage_root: Path) -> None:
    with pytest.raises(FileNotFoundError):
        storage.read_file_bytes(uuid.uuid4(), "missing.txt")


@pytest.mark.parametrize(
    "content_type", ["text/plain", "text/markdown", "application/json", "text/csv"]
)
def test_read_preview_returns_text_for_previewable_types(content_type: str) -> None:
    proc_id = uuid.uuid4()
    storage.write_file(proc_id, "doc.txt", "Café ☕ procedure".encode())

    content, truncated = storage.read_preview(proc_id, "doc.txt", content_type)

    assert content == "Café ☕ procedure"
    assert truncated is False


@pytest.mark.parametrize("content_type", ["application/pdf", "text/html", "image/png", ""])
def test_read_preview_skips_non_previewable_types(content_type: str) -> None:
    proc_id = uuid.uuid4()
    storage.write_file(proc_id, "doc.bin", b"plain text anyway")

    assert storage.read_preview(proc_id, "doc.bin", content_type) == (None, False)


def test_read_preview_missing_file_returns_none() -> None:
    assert storage.read_preview(uuid.uuid4(), "gone.txt", "text/plain") == (None, False)


def test_read_preview_truncates_large_files() -> None:
    proc_id = uuid.uuid4()
    limit = storage._PREVIEW_MAX_BYTES
    storage.write_file(proc_id, "big.txt", b"a" * limit + b"TAIL")

    content, truncated = storage.read_preview(proc_id, "big.txt", "text/plain")

    assert truncated is True
    assert content == "a" * limit


def test_read_preview_at_exact_limit_is_not_truncated() -> None:
    proc_id = uuid.uuid4()
    limit = storage._PREVIEW_MAX_BYTES
    storage.write_file(proc_id, "edge.txt", b"b" * limit)

    content, truncated = storage.read_preview(proc_id, "edge.txt", "text/plain")

    assert truncated is False
    assert content is not None
    assert len(content) == limit


def test_read_preview_replaces_invalid_utf8() -> None:
    proc_id = uuid.uuid4()
    storage.write_file(proc_id, "latin1.txt", b"caf\xe9 ok")

    content, truncated = storage.read_preview(proc_id, "latin1.txt", "text/plain")

    assert content == "caf� ok"
    assert truncated is False


def test_read_preview_empty_file_returns_empty_string() -> None:
    proc_id = uuid.uuid4()
    storage.write_file(proc_id, "empty.txt", b"")

    assert storage.read_preview(proc_id, "empty.txt", "text/plain") == ("", False)
