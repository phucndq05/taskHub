from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.db.session import create_database_engine, create_database_session_factory
from app.repositories.task_memory import InMemoryTaskRepository


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize application resources for one FastAPI app instance."""
    engine: AsyncEngine | None = None
    try:
        settings = get_settings()
        engine = create_database_engine(settings.database_url)
        session_factory = create_database_session_factory(engine)
        task_repository = InMemoryTaskRepository()

        app.state.database_engine = engine
        app.state.database_session_factory = session_factory
        app.state.task_repository = task_repository

        yield
    finally:
        if hasattr(app.state, "task_repository"):
            del app.state.task_repository
        if hasattr(app.state, "database_session_factory"):
            del app.state.database_session_factory
        if hasattr(app.state, "database_engine"):
            del app.state.database_engine
        if engine is not None:
            await engine.dispose()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="TaskHub API",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health", tags=["health"])
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api_router)
    return app


app = create_app()
