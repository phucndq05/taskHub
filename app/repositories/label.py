from typing import cast
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.label import Label
from app.models.project import Project
from app.models.task import Task
from app.models.task_label import TaskLabel
from app.repositories.base import BaseRepository


class LabelRepository(BaseRepository[Label]):
    """Persist labels and task-label associations."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Label)

    async def get_project(self, project_id: UUID) -> Project | None:
        return await self._session.get(Project, project_id)

    async def get_task(self, task_id: UUID) -> Task | None:
        return await self._session.get(Task, task_id)

    async def get_by_id(self, label_id: UUID) -> Label | None:
        return await self.get(label_id)

    async def get_by_project_and_name(
        self,
        project_id: UUID,
        name: str,
    ) -> Label | None:
        statement = select(Label).where(
            Label.project_id == project_id,
            Label.name == name,
        )
        return cast(Label | None, await self._session.scalar(statement))

    async def get_by_project_and_id(
        self,
        project_id: UUID,
        label_id: UUID,
    ) -> Label | None:
        statement = select(Label).where(
            Label.project_id == project_id,
            Label.id == label_id,
        )
        return cast(Label | None, await self._session.scalar(statement))

    async def list_by_project(self, project_id: UUID) -> list[Label]:
        statement = (
            select(Label)
            .where(Label.project_id == project_id)
            .order_by(Label.created_at.desc(), Label.id.desc())
        )
        result = await self._session.scalars(statement)
        return list(result.all())

    async def create_task_label(self, task_label: TaskLabel) -> TaskLabel:
        self._session.add(task_label)
        await self._session.flush()
        return task_label

    async def get_task_label(
        self,
        task_id: UUID,
        label_id: UUID,
    ) -> TaskLabel | None:
        return await self._session.get(TaskLabel, (task_id, label_id))

    async def delete_task_label(
        self,
        task_id: UUID,
        label_id: UUID,
    ) -> None:
        await self._session.execute(
            delete(TaskLabel).where(
                TaskLabel.task_id == task_id,
                TaskLabel.label_id == label_id,
            )
        )
        await self._session.flush()
