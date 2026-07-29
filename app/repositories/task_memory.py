from dataclasses import dataclass, replace
from typing import TypedDict
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class TaskRecord:
    """Stored representation of a Day 1 sample task."""

    id: UUID
    title: str
    description: str | None


class TaskChanges(TypedDict, total=False):
    """Fields that may be changed for a sample task."""

    title: str
    description: str | None


class InMemoryTaskRepository:
    """Store sample tasks in memory for the current app instance."""

    def __init__(self) -> None:
        self._tasks: dict[UUID, TaskRecord] = {}

    def create(self, title: str, description: str | None) -> TaskRecord:
        task = TaskRecord(id=uuid4(), title=title, description=description)
        self._tasks[task.id] = task
        return task

    def list(self) -> list[TaskRecord]:
        return list(self._tasks.values())

    def get(self, task_id: UUID) -> TaskRecord | None:
        return self._tasks.get(task_id)

    def update(self, task_id: UUID, changes: TaskChanges) -> TaskRecord | None:
        task = self._tasks.get(task_id)
        if task is None:
            return None

        title = changes["title"] if "title" in changes else task.title
        description = (
            changes["description"] if "description" in changes else task.description
        )
        updated_task = replace(task, title=title, description=description)
        self._tasks[task_id] = updated_task
        return updated_task

    def delete(self, task_id: UUID) -> bool:
        if task_id not in self._tasks:
            return False

        del self._tasks[task_id]
        return True
