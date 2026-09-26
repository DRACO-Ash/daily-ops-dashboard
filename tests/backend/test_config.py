import pytest
from app.config import Settings

_POSTGRES_VARS = (
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
)


def test_settings_accept_appstore_pg_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _POSTGRES_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PGHOST", "pg.internal")
    monkeypatch.setenv("PGPORT", "5433")
    monkeypatch.setenv("PGDATABASE", "app")
    monkeypatch.setenv("PGUSER", "postgres")
    monkeypatch.setenv("PGPASSWORD", "p@ss:word")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.database_url == (
        "postgresql+asyncpg://postgres:p%40ss%3Aword@pg.internal:5433/app"
    )


def test_procedure_storage_follows_storage_mount(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROCEDURE_STORAGE_PATH", raising=False)
    monkeypatch.setenv("STORAGE_MOUNT_PATH", "/mnt/files")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.procedure_storage_path == "/mnt/files/procedures"


def test_explicit_procedure_storage_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORAGE_MOUNT_PATH", "/mnt/files")
    monkeypatch.setenv("PROCEDURE_STORAGE_PATH", "/srv/procedures")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.procedure_storage_path == "/srv/procedures"
