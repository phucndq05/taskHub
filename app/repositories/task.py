from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.enums import TaskPriority, TaskStatus
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

    async def count_by_project(
        self,
        project_id: UUID,
        *,
        status: TaskStatus | None,
        priority: TaskPriority | None,
        assignee_id: UUID | None,
    ) -> int:
        conditions = self._project_task_conditions(
            project_id,
            status=status,
            priority=priority,
            assignee_id=assignee_id,
        )
        statement = select(func.count()).select_from(Task).where(*conditions)
        total = await self._session.scalar(statement)
        return int(total or 0)

    async def list_by_project(
        self,
        project_id: UUID,
        *,
        status: TaskStatus | None,
        priority: TaskPriority | None,
        assignee_id: UUID | None,
        page: int,
        limit: int,
    ) -> list[Task]:
        conditions = self._project_task_conditions(
            project_id,
            status=status,
            priority=priority,
            assignee_id=assignee_id,
        )
        offset = (page - 1) * limit
        statement = (
            select(Task)
            .where(*conditions)
            .order_by(Task.created_at.desc(), Task.id.desc())
            .offset(offset)
            .limit(limit)
        )
        tasks = await self._session.scalars(statement)
        return list(tasks.all())

    def _project_task_conditions(
        self,
        project_id: UUID,
        *,
        status: TaskStatus | None,
        priority: TaskPriority | None,
        assignee_id: UUID | None,
    ) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = [Task.project_id == project_id]
        if status is not None:
            conditions.append(Task.status == status)
        if priority is not None:
            conditions.append(Task.priority == priority)
        if assignee_id is not None:
            conditions.append(Task.assignee_id == assignee_id)
        return conditions
