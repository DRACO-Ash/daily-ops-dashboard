import asyncio
from logging.config import fileConfig

from alembic import context
from app.config import settings
from app.db.base import Base
from app.models import (  # noqa: F401  ensure models are registered on Base.metadata
    assistant_evaluation,
    audit,
    elset,
    event_summary,
    event_timer,
    maneuver,
    mattermost_ask,
    mattermost_message,
    notification,
    procedure,
    revoked_jti,
    shift_note,
    shift_summary,
    user,
)
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Serialises migrations when several replicas start at once. Arbitrary
# constant, unique to this application.
MIGRATION_LOCK_ID = 0x0D0D0A5B


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    connection.execute(text("SELECT pg_advisory_lock(:id)"), {"id": MIGRATION_LOCK_ID})
    connection.commit()
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    # Inject the URL into the engine section directly rather than via
    # config.set_main_option, which routes through ConfigParser and
    # treats `%` in the password as interpolation syntax.
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = settings.database_url
    connectable = async_engine_from_config(section, prefix="sqlalchemy.")

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
