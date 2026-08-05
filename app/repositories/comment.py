from typing import Any, cast
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.comment import Comment
from app.models.project import Project
from app.models.task import Task
from app.repositories.base import BaseRepository

TaskContext = tuple[Task, Project]
CommentContext = tuple[Comment, Task, Project]


class CommentRepository(BaseRepository[Comment]):
    """Persist comments and load their task/project context."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Comment)

    async def get_task_context(self, task_id: UUID) -> TaskContext | None:
        statement = (
            select(Task, Project)
            .join(Project, Task.project_id == Project.id)
            .where(Task.id == task_id)
        )
        row = (await self._session.execute(statement)).one_or_none()
        if row is None:
            return None
        task, project = row
        return task, project

    async def get_comment_context(
        self,
        comment_id: UUID,
    ) -> CommentContext | None:
        statement = (
            select(Comment, Task, Project)
            .join(Task, Comment.task_id == Task.id)
            .join(Project, Task.project_id == Project.id)
            .where(Comment.id == comment_id)
        )
        row = (await self._session.execute(statement)).one_or_none()
        if row is None:
            return None
        comment, task, project = row
        return comment, task, project

    async def delete_by_id(self, comment_id: UUID) -> bool:
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                delete(Comment).where(Comment.id == comment_id)
            ),
        )
        await self._session.flush()
        return result.rowcount > 0
