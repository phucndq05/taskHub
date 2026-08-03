import importlib
from collections.abc import Generator
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI, Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.types import Scope

import app.main as main_module
from app.api.dependencies import (
    get_database_session,
    get_database_session_factory,
)
from app.db.session import (
    AsyncSessionFactory,
    create_database_engine,
    create_database_session_factory,
)

VALID_DATABASE_URL = "postgresql+asyncpg://taskhub:password@localhost:5432/taskhub_test"
VALID_JWT_SECRET_KEY = "test-secret-key-with-at-least-32-characters"


class StartupError(Exception):
    """Raised by tests to exercise startup cleanup paths."""


class SessionDependencyError(Exception):
    """Raised by tests to exercise session dependency rollback."""


@pytest.fixture
def isolated_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Generator[None, None, None]:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    main_module.get_settings.cache_clear()
    try:
        yield
    finally:
        main_module.get_settings.cache_clear()


def build_request(app: FastAPI) -> Request:
    scope: Scope = {
        "type": "http",
        "app": app,
        "headers": [],
        "method": "GET",
        "path": "/",
        "query_string": b"",
    }
    return Request(scope)


def build_mock_engine() -> tuple[AsyncEngine, AsyncMock]:
    engine_mock = MagicMock(spec=AsyncEngine)
    dispose_mock = AsyncMock()
    engine_mock.dispose = dispose_mock
    return cast(AsyncEngine, engine_mock), dispose_mock


def build_mock_session() -> tuple[AsyncSession, AsyncMock, AsyncMock, AsyncMock]:
    session_mock = MagicMock(spec=AsyncSession)
    rollback_mock = AsyncMock()
    close_mock = AsyncMock()
    commit_mock = AsyncMock()
    session_mock.rollback = rollback_mock
    session_mock.close = close_mock
    session_mock.commit = commit_mock
    return cast(AsyncSession, session_mock), rollback_mock, close_mock, commit_mock


def build_session_factory(
    *sessions: AsyncSession,
) -> tuple[AsyncSessionFactory, MagicMock]:
    factory_mock = MagicMock(side_effect=list(sessions))
    return cast(AsyncSessionFactory, factory_mock), factory_mock


def assert_database_state_absent(app: FastAPI) -> None:
    assert not hasattr(app.state, "database_engine")
    assert not hasattr(app.state, "database_session_factory")


def test_import_main_does_not_require_database_url(
    isolated_settings: None,
) -> None:
    reloaded_module = importlib.reload(main_module)

    assert hasattr(reloaded_module, "create_app")


def test_create_app_does_not_require_database_url(
    isolated_settings: None,
) -> None:
    app = main_module.create_app()

    assert isinstance(app, FastAPI)


@pytest.mark.asyncio
async def test_database_helpers_create_async_resources_without_connecting() -> None:
    engine = create_database_engine(VALID_DATABASE_URL)
    try:
        assert isinstance(engine, AsyncEngine)
        session_factory = create_database_session_factory(engine)
        assert isinstance(session_factory, async_sessionmaker)

        session = session_factory()
        try:
            assert isinstance(session, AsyncSession)
            assert session.sync_session.expire_on_commit is False
        finally:
            await session.close()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_lifespan_startup_requires_database_url(
    isolated_settings: None,
) -> None:
    app = main_module.create_app()

    with pytest.raises(ValidationError):
        async with LifespanManager(app):
            pass

    assert_database_state_absent(app)


@pytest.mark.asyncio
async def test_lifespan_initializes_and_cleans_database_resources(
    isolated_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_DATABASE_URL)
    monkeypatch.setenv("JWT_SECRET_KEY", VALID_JWT_SECRET_KEY)
    engine, dispose_mock = build_mock_engine()

    def fake_create_database_engine(database_url: str) -> AsyncEngine:
        assert database_url == VALID_DATABASE_URL
        return engine

    monkeypatch.setattr(
        main_module,
        "create_database_engine",
        fake_create_database_engine,
    )
    app = main_module.create_app()

    async with LifespanManager(app):
        assert app.state.database_engine is engine
        assert isinstance(app.state.database_session_factory, async_sessionmaker)

    assert_database_state_absent(app)
    dispose_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_disposes_engine_when_session_factory_creation_fails(
    isolated_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_DATABASE_URL)
    monkeypatch.setenv("JWT_SECRET_KEY", VALID_JWT_SECRET_KEY)
    engine, dispose_mock = build_mock_engine()

    def fake_create_database_engine(database_url: str) -> AsyncEngine:
        return engine

    def fail_create_session_factory(engine: AsyncEngine) -> AsyncSessionFactory:
        raise StartupError("session factory creation failed")

    monkeypatch.setattr(
        main_module,
        "create_database_engine",
        fake_create_database_engine,
    )
    monkeypatch.setattr(
        main_module,
        "create_database_session_factory",
        fail_create_session_factory,
    )
    app = main_module.create_app()

    with pytest.raises(StartupError):
        async with LifespanManager(app):
            pass

    assert_database_state_absent(app)
    dispose_mock.assert_awaited_once()


def test_database_session_factory_getter_requires_lifespan_resource() -> None:
    request = build_request(FastAPI())

    with pytest.raises(RuntimeError, match="Database session factory"):
        get_database_session_factory(request)


@pytest.mark.asyncio
async def test_database_session_factory_getter_returns_configured_factory() -> None:
    engine = create_database_engine(VALID_DATABASE_URL)
    try:
        session_factory = create_database_session_factory(engine)
        app = FastAPI()
        app.state.database_session_factory = session_factory
        request = build_request(app)

        assert get_database_session_factory(request) is session_factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_database_session_dependency_yields_async_session() -> None:
    engine = create_database_engine(VALID_DATABASE_URL)
    try:
        session_factory = create_database_session_factory(engine)
        session_generator = get_database_session(session_factory)
        session = await anext(session_generator)

        assert isinstance(session, AsyncSession)

        with pytest.raises(StopAsyncIteration):
            await session_generator.asend(None)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_database_session_dependency_creates_session_per_invocation() -> None:
    engine = create_database_engine(VALID_DATABASE_URL)
    try:
        session_factory = create_database_session_factory(engine)

        first_generator = get_database_session(session_factory)
        first_session = await anext(first_generator)
        with pytest.raises(StopAsyncIteration):
            await first_generator.asend(None)

        second_generator = get_database_session(session_factory)
        second_session = await anext(second_generator)
        with pytest.raises(StopAsyncIteration):
            await second_generator.asend(None)

        assert first_session is not second_session
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_database_session_dependency_closes_without_commit_or_rollback() -> None:
    session, rollback_mock, close_mock, commit_mock = build_mock_session()
    session_factory, factory_mock = build_session_factory(session)
    session_generator = get_database_session(session_factory)

    yielded_session = await anext(session_generator)

    assert yielded_session is session
    factory_mock.assert_called_once_with()
    with pytest.raises(StopAsyncIteration):
        await session_generator.asend(None)
    rollback_mock.assert_not_awaited()
    close_mock.assert_awaited_once()
    commit_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_database_session_dependency_rolls_back_and_closes_on_exception() -> None:
    session, rollback_mock, close_mock, commit_mock = build_mock_session()
    session_factory, factory_mock = build_session_factory(session)
    session_generator = get_database_session(session_factory)
    expected_error = SessionDependencyError("downstream failed")

    yielded_session = await anext(session_generator)

    assert yielded_session is session
    factory_mock.assert_called_once_with()
    with pytest.raises(SessionDependencyError) as exc_info:
        await session_generator.athrow(expected_error)
    assert exc_info.value is expected_error
    rollback_mock.assert_awaited_once()
    close_mock.assert_awaited_once()
    commit_mock.assert_not_awaited()
