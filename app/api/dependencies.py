from collections.abc import AsyncGenerator
from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import AsyncSessionFactory
from app.repositories.task_memory import InMemoryTaskRepository
from app.services.task import TaskService


def get_task_repository(request: Request) -> InMemoryTaskRepository:
    """Return the in-memory task repository for the current app."""
    repository = getattr(request.app.state, "task_repository", None)
    if not isinstance(repository, InMemoryTaskRepository):
        raise RuntimeError("Task repository is not initialized.")
    return repository


TaskRepositoryDep = Annotated[InMemoryTaskRepository, Depends(get_task_repository)]


def get_task_service(repository: TaskRepositoryDep) -> TaskService:
    """Create a task service for the current request."""
    return TaskService(repository)


TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]


def get_database_session_factory(request: Request) -> AsyncSessionFactory:
    """Return the app-level async session factory."""
    session_factory = getattr(request.app.state, "database_session_factory", None)
    if not isinstance(session_factory, async_sessionmaker):
        raise RuntimeError("Database session factory is not initialized.")
    return cast(AsyncSessionFactory, session_factory)


DatabaseSessionFactoryDep = Annotated[
    AsyncSessionFactory,
    Depends(get_database_session_factory),
]


async def get_database_session(
    session_factory: DatabaseSessionFactoryDep,
) -> AsyncGenerator[AsyncSession, None]:
    """Yield one request-scoped async database session."""
    session = session_factory()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


DatabaseSessionDep = Annotated[AsyncSession, Depends(get_database_session)]
