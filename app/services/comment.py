from collections.abc import Iterable
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.comment import Comment
from app.models.enums import UserRole, WorkspaceMemberRole
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.repositories.comment import CommentRepository
from app.repositories.workspace import WorkspaceRepository
from app.schemas.comment import CommentCreate, CommentRead

COMMENT_TASK_FK = "fk_comments_task_id_tasks"


class CommentTaskNotFoundError(Exception):
    """Raised when a task is missing or hidden from the actor."""


class CommentNotFoundError(Exception):
    """Raised when a comment is missing or hidden from the actor."""


class CommentPermissionError(Exception):
    """Raised when a known workspace member lacks comment permission."""


class CommentService:
    """Coordinate comment authorization, ownership, and transactions."""

    def __init__(
        self,
        comment_repository: CommentRepository,
        workspace_repository: WorkspaceRepository,
        session: AsyncSession,
    ) -> None:
        self._comment_repository = comment_repository
        self._workspace_repository = workspace_repository
        self._session = session

    async def create_comment(
        self,
        current_user: User,
        task_id: UUID,
        request: CommentCreate,
    ) -> CommentRead:
        await self._get_task_for_action(
            current_user,
            task_id,
            allowed_roles=(WorkspaceMemberRole.OWNER, WorkspaceMemberRole.EDITOR),
        )

        comment = Comment(
            task_id=task_id,
            author_id=current_user.id,
            content=request.content,
        )
        try:
            created_comment = await self._comment_repository.create(comment)
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            if _constraint_name(exc) == COMMENT_TASK_FK:
                raise CommentTaskNotFoundError from exc
            raise
        except Exception:
            await self._session.rollback()
            raise

        return CommentRead.model_validate(created_comment)

    async def delete_comment(self, current_user: User, comment_id: UUID) -> None:
        comment, _, project = await self._get_comment_context(comment_id)
        await self._authorize_delete_comment(current_user, comment, project)

        try:
            deleted = await self._comment_repository.delete_by_id(comment_id)
            if not deleted:
                await self._session.rollback()
                raise CommentNotFoundError
            await self._session.commit()
        except CommentNotFoundError:
            raise
        except Exception:
            await self._session.rollback()
            raise

    async def _get_task_for_action(
        self,
        current_user: User,
        task_id: UUID,
        *,
        allowed_roles: Iterable[WorkspaceMemberRole],
    ) -> Task:
        context = await self._comment_repository.get_task_context(task_id)
        if context is None:
            raise CommentTaskNotFoundError

        task, project = context
        await self._authorize_project_workspace(
            current_user,
            project.workspace_id,
            hidden_error=CommentTaskNotFoundError,
            allowed_roles=allowed_roles,
        )
        return task

    async def _get_comment_context(
        self,
        comment_id: UUID,
    ) -> tuple[Comment, Task, Project]:
        context = await self._comment_repository.get_comment_context(comment_id)
        if context is None:
            raise CommentNotFoundError
        return context

    async def _authorize_delete_comment(
        self,
        current_user: User,
        comment: Comment,
        project: Project,
    ) -> None:
        if current_user.role is UserRole.ADMIN:
            return

        member = await self._workspace_repository.get_member(
            project.workspace_id,
            current_user.id,
        )
        if member is None:
            raise CommentNotFoundError
        if member.role is WorkspaceMemberRole.OWNER:
            return
        if (
            member.role is WorkspaceMemberRole.EDITOR
            and comment.author_id == current_user.id
        ):
            return
        raise CommentPermissionError

    async def _authorize_project_workspace(
        self,
        current_user: User,
        workspace_id: UUID,
        *,
        hidden_error: type[Exception],
        allowed_roles: Iterable[WorkspaceMemberRole],
    ) -> None:
        if current_user.role is UserRole.ADMIN:
            return

        member = await self._workspace_repository.get_member(
            workspace_id,
            current_user.id,
        )
        if member is None:
            raise hidden_error
        if member.role not in set(allowed_roles):
            raise CommentPermissionError


def _constraint_name(exc: IntegrityError) -> str | None:
    original = getattr(exc, "orig", None)
    for candidate in (
        original,
        getattr(original, "__cause__", None),
        getattr(original, "__context__", None),
    ):
        constraint_name = getattr(candidate, "constraint_name", None)
        if isinstance(constraint_name, str):
            return constraint_name

        diagnostic = getattr(candidate, "diag", None)
        diagnostic_constraint_name = getattr(diagnostic, "constraint_name", None)
        if isinstance(diagnostic_constraint_name, str):
            return diagnostic_constraint_name

    return None
