from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI
from redis import asyncio as redis
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.db.session import create_database_engine, create_database_session_factory
from app.integrations.cache import TaskListCache

API_DESCRIPTION = (
    "TaskHub is a FastAPI task management API for authentication, workspaces, "
    "projects, tasks, labels, comments, RBAC, task-list caching, and assignment "
    "email notifications."
)

OPENAPI_TAGS = [
    {
        "name": "health",
        "description": "Application health check.",
    },
    {
        "name": "auth",
        "description": "Registration, login, refresh-token rotation, and logout.",
    },
    {
        "name": "users",
        "description": "Current-user profile and password management.",
    },
    {
        "name": "workspaces",
        "description": "Workspace CRUD and membership management.",
    },
    {
        "name": "projects",
        "description": "Workspace project CRUD and archive workflow.",
    },
    {
        "name": "tasks",
        "description": "Project task CRUD, filtering, assignment, and status updates.",
    },
    {
        "name": "labels",
        "description": "Project labels and task-label attachments.",
    },
    {
        "name": "comments",
        "description": "Task comments and comment deletion permissions.",
    },
]


def create_redis_client(redis_url: str) -> Redis:
    """Create a Redis client without opening a network connection."""
    return cast(Redis, redis.from_url(redis_url, decode_responses=True))


def create_task_list_cache(redis_client: Redis, ttl_seconds: int) -> TaskListCache:
    """Create the task-list cache integration."""
    return TaskListCache(redis_client, ttl_seconds=ttl_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize application resources for one FastAPI app instance."""
    engine: AsyncEngine | None = None
    redis_client: Redis | None = None
    try:
        settings = get_settings()
        engine = create_database_engine(settings.database_url)
        session_factory = create_database_session_factory(engine)
        redis_client = create_redis_client(settings.redis_url)
        task_list_cache = create_task_list_cache(
            redis_client,
            settings.task_list_cache_ttl_seconds,
        )

        app.state.database_engine = engine
        app.state.database_session_factory = session_factory
        app.state.redis_client = redis_client
        app.state.task_list_cache = task_list_cache

        yield
    finally:
        if hasattr(app.state, "task_list_cache"):
            del app.state.task_list_cache
        if hasattr(app.state, "redis_client"):
            del app.state.redis_client
        if redis_client is not None:
            await redis_client.aclose()
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
        description=API_DESCRIPTION,
        version="0.1.0",
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
    )

    @app.get("/health", tags=["health"])
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api_router)
    return app


app = create_app()
