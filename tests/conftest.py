import asyncio
import os
from collections.abc import Generator
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from app.core.config import get_settings
from app.main import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
LIGHTWEIGHT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://taskhub:password@localhost:5432/taskhub_test"
)
DOMAIN_TABLES = (
    "comments",
    "task_labels",
    "labels",
    "tasks",
    "workspace_members",
    "projects",
    "workspaces",
    "refresh_tokens",
    "users",
)


def _validated_test_database_url() -> str:
    raw_url = os.environ.get("TEST_DATABASE_URL")
    if raw_url is None or raw_url.strip() == "":
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests.")

    database_url = raw_url.strip()
    try:
        parsed_url = make_url(database_url)
    except ArgumentError:
        pytest.fail("TEST_DATABASE_URL must be a valid SQLAlchemy database URL.")

    if parsed_url.drivername != "postgresql+asyncpg":
        pytest.fail("TEST_DATABASE_URL must use the postgresql+asyncpg driver.")
    if parsed_url.database is None or not parsed_url.database.endswith("_test"):
        pytest.fail("TEST_DATABASE_URL database name must end with _test.")

    return database_url


def _restore_database_url(previous_database_url: str | None) -> None:
    if previous_database_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous_database_url
    get_settings.cache_clear()


async def _truncate_domain_tables(database_url: str) -> None:
    engine = create_async_engine(database_url)
    table_names = ", ".join(f'"{table_name}"' for table_name in DOMAIN_TABLES)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE")
            )
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def test_database_url() -> str:
    return _validated_test_database_url()


@pytest.fixture(scope="session")
def migrated_test_database(test_database_url: str) -> Generator[str, None, None]:
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_database_url
    get_settings.cache_clear()

    try:
        alembic_config = Config(str(ALEMBIC_INI))
        command.upgrade(alembic_config, "head")
    except Exception as exc:
        _restore_database_url(previous_database_url)
        pytest.fail(
            "TEST_DATABASE_URL could not be reached or migrated "
            f"({type(exc).__name__})."
        )
    else:
        _restore_database_url(previous_database_url)

    yield test_database_url


@pytest.fixture
def clean_test_database(
    migrated_test_database: str,
) -> Generator[None, None, None]:
    asyncio.run(_truncate_domain_tables(migrated_test_database))
    try:
        yield
    finally:
        asyncio.run(_truncate_domain_tables(migrated_test_database))


@pytest.fixture
def configured_database_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    migrated_test_database: str,
) -> Generator[None, None, None]:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", migrated_test_database)
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Generator[TestClient, None, None]:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", LIGHTWEIGHT_TEST_DATABASE_URL)
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as test_client:
            yield test_client
    finally:
        get_settings.cache_clear()


@pytest.fixture
def task_client(
    configured_database_url: None,
    clean_test_database: None,
) -> Generator[TestClient, None, None]:
    with TestClient(create_app()) as test_client:
        yield test_client
