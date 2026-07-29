from uuid import UUID

from app.repositories.task_memory import (
    InMemoryTaskRepository,
    TaskChanges,
    TaskRecord,
)
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate


class TaskService:
    """Coordinate sample task CRUD operations."""

    def __init__(self, repository: InMemoryTaskRepository) -> None:
        self._repository = repository

    def create_task(self, task: TaskCreate) -> TaskRead:
        record = self._repository.create(
            title=task.title,
            description=task.description,
        )
        return self._to_read_model(record)

    def list_tasks(self) -> list[TaskRead]:
        return [self._to_read_model(task) for task in self._repository.list()]

    def get_task(self, task_id: UUID) -> TaskRead | None:
        record = self._repository.get(task_id)
        if record is None:
            return None
        return self._to_read_model(record)

    def update_task(self, task_id: UUID, task_update: TaskUpdate) -> TaskRead | None:
        changes: TaskChanges = {}
        if task_update.title is not None:
            changes["title"] = task_update.title
        if "description" in task_update.model_fields_set:
            changes["description"] = task_update.description

        record = self._repository.update(task_id, changes)
        if record is None:
            return None
        return self._to_read_model(record)

    def delete_task(self, task_id: UUID) -> bool:
        return self._repository.delete(task_id)

    def _to_read_model(self, task: TaskRecord) -> TaskRead:
        return TaskRead(
            id=task.id,
            title=task.title,
            description=task.description,
        )
