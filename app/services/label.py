from collections.abc import Iterable
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import UserRole, WorkspaceMemberRole
from app.models.label import Label
from app.models.project import Project
from app.models.task import Task
from app.models.task_label import TaskLabel
from app.models.user import User
from app.repositories.label import LabelRepository
from app.repositories.workspace import WorkspaceRepository
from app.schemas.label import LabelCreate, LabelRead, LabelUpdate

LABEL_PROJECT_NAME_UQ = "uq_labels_project_id_name"
TASK_LABEL_PK = "pk_task_labels"


class LabelProjectNotFoundError(Exception):
    """Raised when a project is missing or hidden from the actor."""


class LabelNotFoundError(Exception):
    """Raised when a label is missing or hidden from the actor."""


class LabelTaskNotFoundError(Exception):
    """Raised when a task is missing or hidden from the actor."""


class LabelPermissionError(Exception):
    """Raised when a known workspace member lacks label permission."""


class NoLabelChangesError(Exception):
    """Raised when a Label PATCH request contains no editable changes."""


class DuplicateLabelNameError(Exception):
    """Raised when a label name already exists in the project."""


class TaskLabelAlreadyExistsError(Exception):
    """Raised when a label is already attached to a task."""


class TaskLabelNotFoundError(Exception):
    """Raised when a task-label association does not exist."""


class LabelService:
    """Coordinate label rules, authorization, and transactions."""

    def __init__(
        self,
        label_repository: LabelRepository,
        workspace_repository: WorkspaceRepository,
        session: AsyncSession,
    ) -> None:
        self._label_repository = label_repository
        self._workspace_repository = workspace_repository
        self._session = session

    async def create_label(
        self,
        current_user: User,
        project_id: UUID,
        request: LabelCreate,
    ) -> LabelRead:
        await self._get_project_for_action(
            current_user,
            project_id,
            allowed_roles=(WorkspaceMemberRole.OWNER, WorkspaceMemberRole.EDITOR),
        )
        await self._raise_for_duplicate_name(project_id, request.name)

        label = Label(
            project_id=project_id,
            name=request.name,
            color=request.color,
        )
        try:
            created_label = await self._label_repository.create(label)
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            if _constraint_name(exc) == LABEL_PROJECT_NAME_UQ:
                raise DuplicateLabelNameError from exc
            raise
        except Exception:
            await self._session.rollback()
            raise

        return LabelRead.model_validate(created_label)

    async def list_labels(
        self,
        current_user: User,
        project_id: UUID,
    ) -> list[LabelRead]:
        await self._get_project_for_action(
            current_user,
            project_id,
            allowed_roles=(
                WorkspaceMemberRole.OWNER,
                WorkspaceMemberRole.EDITOR,
                WorkspaceMemberRole.VIEWER,
            ),
        )
        labels = await self._label_repository.list_by_project(project_id)
        return [LabelRead.model_validate(label) for label in labels]

    async def get_label(
        self,
        current_user: User,
        label_id: UUID,
    ) -> LabelRead:
        label = await self._get_label_for_action(
            current_user,
            label_id,
            allowed_roles=(
                WorkspaceMemberRole.OWNER,
                WorkspaceMemberRole.EDITOR,
                WorkspaceMemberRole.VIEWER,
            ),
        )
        return LabelRead.model_validate(label)

    async def update_label(
        self,
        current_user: User,
        label_id: UUID,
        request: LabelUpdate,
    ) -> LabelRead:
        label = await self._get_label_for_action(
            current_user,
            label_id,
            allowed_roles=(WorkspaceMemberRole.OWNER, WorkspaceMemberRole.EDITOR),
        )
        if not request.model_fields_set:
            raise NoLabelChangesError

        if "name" in request.model_fields_set:
            assert request.name is not None
            await self._raise_for_duplicate_name(
                label.project_id,
                request.name,
                current_label_id=label.id,
            )
            label.name = request.name
        if "color" in request.model_fields_set:
            assert request.color is not None
            label.color = request.color

        try:
            updated_label = await self._label_repository.update(label)
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            if _constraint_name(exc) == LABEL_PROJECT_NAME_UQ:
                raise DuplicateLabelNameError from exc
            raise
        except Exception:
            await self._session.rollback()
            raise

        return LabelRead.model_validate(updated_label)

    async def delete_label(self, current_user: User, label_id: UUID) -> None:
        label = await self._get_label_for_action(
            current_user,
            label_id,
            allowed_roles=(WorkspaceMemberRole.OWNER, WorkspaceMemberRole.EDITOR),
        )
        try:
            await self._label_repository.delete(label)
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

    async def attach_label(
        self,
        current_user: User,
        task_id: UUID,
        label_id: UUID,
    ) -> LabelRead:
        task = await self._get_task_for_action(
            current_user,
            task_id,
            allowed_roles=(WorkspaceMemberRole.OWNER, WorkspaceMemberRole.EDITOR),
        )
        label = await self._label_repository.get_by_project_and_id(
            task.project_id,
            label_id,
        )
        if label is None:
            raise LabelNotFoundError

        existing_task_label = await self._label_repository.get_task_label(
            task_id,
            label_id,
        )
        if existing_task_label is not None:
            raise TaskLabelAlreadyExistsError

        try:
            await self._label_repository.create_task_label(
                TaskLabel(task_id=task_id, label_id=label_id)
            )
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            if _constraint_name(exc) == TASK_LABEL_PK:
                raise TaskLabelAlreadyExistsError from exc
            raise
        except Exception:
            await self._session.rollback()
            raise

        return LabelRead.model_validate(label)

    async def detach_label(
        self,
        current_user: User,
        task_id: UUID,
        label_id: UUID,
    ) -> None:
        task = await self._get_task_for_action(
            current_user,
            task_id,
            allowed_roles=(WorkspaceMemberRole.OWNER, WorkspaceMemberRole.EDITOR),
        )
        label = await self._label_repository.get_by_project_and_id(
            task.project_id,
            label_id,
        )
        if label is None:
            raise LabelNotFoundError

        task_label = await self._label_repository.get_task_label(task_id, label_id)
        if task_label is None:
            raise TaskLabelNotFoundError

        try:
            await self._label_repository.delete_task_label(task_id, label_id)
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

    async def _raise_for_duplicate_name(
        self,
        project_id: UUID,
        name: str,
        *,
        current_label_id: UUID | None = None,
    ) -> None:
        existing_label = await self._label_repository.get_by_project_and_name(
            project_id,
            name,
        )
        if existing_label is None:
            return
        if current_label_id is not None and existing_label.id == current_label_id:
            return
        raise DuplicateLabelNameError

    async def _get_project_for_action(
        self,
        current_user: User,
        project_id: UUID,
        *,
        allowed_roles: Iterable[WorkspaceMemberRole],
    ) -> Project:
        project = await self._label_repository.get_project(project_id)
        if project is None:
            raise LabelProjectNotFoundError

        await self._authorize_project_workspace(
            current_user,
            project.workspace_id,
            hidden_error=LabelProjectNotFoundError,
            allowed_roles=allowed_roles,
        )
        return project

    async def _get_label_for_action(
        self,
        current_user: User,
        label_id: UUID,
        *,
        allowed_roles: Iterable[WorkspaceMemberRole],
    ) -> Label:
        label = await self._label_repository.get_by_id(label_id)
        if label is None:
            raise LabelNotFoundError

        project = await self._label_repository.get_project(label.project_id)
        if project is None:
            raise LabelNotFoundError

        await self._authorize_project_workspace(
            current_user,
            project.workspace_id,
            hidden_error=LabelNotFoundError,
            allowed_roles=allowed_roles,
        )
        return label

    async def _get_task_for_action(
        self,
        current_user: User,
        task_id: UUID,
        *,
        allowed_roles: Iterable[WorkspaceMemberRole],
    ) -> Task:
        task = await self._label_repository.get_task(task_id)
        if task is None:
            raise LabelTaskNotFoundError

        project = await self._label_repository.get_project(task.project_id)
        if project is None:
            raise LabelTaskNotFoundError

        await self._authorize_project_workspace(
            current_user,
            project.workspace_id,
            hidden_error=LabelTaskNotFoundError,
            allowed_roles=allowed_roles,
        )
        return task

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
            raise LabelPermissionError


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
