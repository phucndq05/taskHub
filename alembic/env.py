import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core.config import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def configure_database_url() -> str:
    """Load and inject the validated migration database URL."""
    raw_url = get_settings().database_url
    config.set_main_option("sqlalchemy.url", raw_url.replace("%", "%%"))
    return raw_url


def run_migrations_offline() -> None:
    """Run migrations without opening a database connection."""
    raw_url = configure_database_url()
    context.configure(
        url=raw_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations through a synchronous Alembic connection callback."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create and dispose the migration-specific async engine."""
    configure_database_url()
    section = config.get_section(config.config_ini_section)
    if section is None:
        raise RuntimeError("Alembic configuration section is missing.")

    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations through SQLAlchemy's async engine."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
