from typing import Annotated

from fastapi import Depends, Request

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
