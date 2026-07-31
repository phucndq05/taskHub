from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.models.workspace_member import WorkspaceMember
from app.repositories.base import BaseRepository


class TaskRepository(BaseRepository[Task]):
    """Persist Task data with SQLAlchemy async sessions."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Task)

    async def get_project(self, project_id: UUID) -> Project | None:
        return await self._session.get(Project, project_id)

    async def user_exists(self, user_id: UUID) -> bool:
        user = await self._session.get(User, user_id)
        return user is not None

    async def workspace_member_exists(self, workspace_id: UUID, user_id: UUID) -> bool:
        statement = select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
        membership = await self._session.scalar(statement)
        return membership is not None

    async def list_by_project(self, project_id: UUID) -> list[Task]:
        statement = (
            select(Task)
            .where(Task.project_id == project_id)
            .order_by(Task.created_at.desc(), Task.id.desc())
        )
        tasks = await self._session.scalars(statement)
        return list(tasks.all())
