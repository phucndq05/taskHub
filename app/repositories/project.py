from uuid import UUID

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.label import Label
from app.models.project import Project
from app.models.task import Task
from app.repositories.base import BaseRepository


class ProjectRepository(BaseRepository[Project]):
    """Persist and load projects."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Project)

    async def get_by_id(self, project_id: UUID) -> Project | None:
        return await self.get(project_id)

    async def list_by_workspace(self, workspace_id: UUID) -> list[Project]:
        statement = (
            select(Project)
            .where(Project.workspace_id == workspace_id)
            .order_by(Project.created_at.desc(), Project.id.desc())
        )
        result = await self._session.scalars(statement)
        return list(result.all())

    async def has_tasks(self, project_id: UUID) -> bool:
        statement = select(exists().where(Task.project_id == project_id))
        return bool(await self._session.scalar(statement))

    async def has_labels(self, project_id: UUID) -> bool:
        statement = select(exists().where(Label.project_id == project_id))
        return bool(await self._session.scalar(statement))

    async def delete_project_by_id(self, project_id: UUID) -> None:
        await self._session.execute(delete(Project).where(Project.id == project_id))
        await self._session.flush()
