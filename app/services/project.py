from collections.abc import Iterable
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ProjectStatus, UserRole, WorkspaceMemberRole
from app.models.project import Project
from app.models.user import User
from app.repositories.project import ProjectRepository
from app.repositories.workspace import WorkspaceRepository
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate

TASK_PROJECT_FK = "fk_tasks_project_id_projects"
LABEL_PROJECT_FK = "fk_labels_project_id_projects"
PROJECT_CHILD_CONSTRAINTS = {TASK_PROJECT_FK, LABEL_PROJECT_FK}


class ProjectWorkspaceNotFoundError(Exception):
    """Raised when a workspace is missing or hidden from the actor."""


class ProjectNotFoundError(Exception):
    """Raised when a project is missing or hidden from the actor."""


class ProjectPermissionError(Exception):
    """Raised when a known workspace member lacks project permission."""


class NoProjectChangesError(Exception):
    """Raised when a project PATCH request contains no editable changes."""


class ActiveProjectDeleteError(Exception):
    """Raised when deleting a project that has not been archived."""


class ProjectHasChildrenError(Exception):
    """Raised when a project cannot be deleted because child rows reference it."""


class ProjectService:
    """Coordinate project business rules, authorization, and transactions."""

    def __init__(
        self,
        project_repository: ProjectRepository,
        workspace_repository: WorkspaceRepository,
        session: AsyncSession,
    ) -> None:
        self._project_repository = project_repository
        self._workspace_repository = workspace_repository
        self._session = session

    async def create_project(
        self,
        current_user: User,
        workspace_id: UUID,
        request: ProjectCreate,
    ) -> ProjectRead:
        await self._authorize_workspace(
            current_user,
            workspace_id,
            allowed_roles=(
                WorkspaceMemberRole.OWNER,
                WorkspaceMemberRole.EDITOR,
            ),
        )
        project = Project(
            workspace_id=workspace_id,
            name=request.name,
            description=request.description,
            status=ProjectStatus.ACTIVE,
            created_by=current_user.id,
        )

        try:
            created_project = await self._project_repository.create(project)
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

        return ProjectRead.model_validate(created_project)

    async def list_projects(
        self,
        current_user: User,
        workspace_id: UUID,
    ) -> list[ProjectRead]:
        await self._authorize_workspace(
            current_user,
            workspace_id,
            allowed_roles=(
                WorkspaceMemberRole.OWNER,
                WorkspaceMemberRole.EDITOR,
                WorkspaceMemberRole.VIEWER,
            ),
        )
        projects = await self._project_repository.list_by_workspace(workspace_id)
        return [ProjectRead.model_validate(project) for project in projects]

    async def get_project(
        self,
        current_user: User,
        project_id: UUID,
    ) -> ProjectRead:
        project = await self._get_project_for_action(
            current_user,
            project_id,
            allowed_roles=(
                WorkspaceMemberRole.OWNER,
                WorkspaceMemberRole.EDITOR,
                WorkspaceMemberRole.VIEWER,
            ),
        )
        return ProjectRead.model_validate(project)

    async def update_project(
        self,
        current_user: User,
        project_id: UUID,
        request: ProjectUpdate,
    ) -> ProjectRead:
        project = await self._get_project_for_action(
            current_user,
            project_id,
            allowed_roles=(
                WorkspaceMemberRole.OWNER,
                WorkspaceMemberRole.EDITOR,
            ),
        )
        if not request.model_fields_set:
            raise NoProjectChangesError

        if "name" in request.model_fields_set:
            assert request.name is not None
            project.name = request.name
        if "description" in request.model_fields_set:
            project.description = request.description

        try:
            updated_project = await self._project_repository.update(project)
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

        return ProjectRead.model_validate(updated_project)

    async def archive_project(
        self,
        current_user: User,
        project_id: UUID,
    ) -> ProjectRead:
        project = await self._get_project_for_action(
            current_user,
            project_id,
            allowed_roles=(
                WorkspaceMemberRole.OWNER,
                WorkspaceMemberRole.EDITOR,
            ),
        )
        if project.status is ProjectStatus.ARCHIVED:
            return ProjectRead.model_validate(project)

        project.status = ProjectStatus.ARCHIVED
        try:
            archived_project = await self._project_repository.update(project)
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

        return ProjectRead.model_validate(archived_project)

    async def delete_project(
        self,
        current_user: User,
        project_id: UUID,
    ) -> None:
        project = await self._get_project_for_action(
            current_user,
            project_id,
            allowed_roles=(WorkspaceMemberRole.OWNER,),
        )
        if project.status is not ProjectStatus.ARCHIVED:
            raise ActiveProjectDeleteError

        if await self._project_repository.has_tasks(
            project_id
        ) or await self._project_repository.has_labels(project_id):
            raise ProjectHasChildrenError

        try:
            await self._project_repository.delete_project_by_id(project_id)
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            if _constraint_name(exc) in PROJECT_CHILD_CONSTRAINTS:
                raise ProjectHasChildrenError from exc
            raise
        except Exception:
            await self._session.rollback()
            raise

    async def _authorize_workspace(
        self,
        current_user: User,
        workspace_id: UUID,
        *,
        allowed_roles: Iterable[WorkspaceMemberRole],
    ) -> None:
        workspace = await self._workspace_repository.get_by_id(workspace_id)
        if workspace is None:
            raise ProjectWorkspaceNotFoundError

        if _is_admin(current_user):
            return

        member = await self._workspace_repository.get_member(
            workspace_id,
            current_user.id,
        )
        if member is None:
            raise ProjectWorkspaceNotFoundError
        if member.role not in set(allowed_roles):
            raise ProjectPermissionError

    async def _get_project_for_action(
        self,
        current_user: User,
        project_id: UUID,
        *,
        allowed_roles: Iterable[WorkspaceMemberRole],
    ) -> Project:
        project = await self._project_repository.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundError

        if _is_admin(current_user):
            return project

        member = await self._workspace_repository.get_member(
            project.workspace_id,
            current_user.id,
        )
        if member is None:
            raise ProjectNotFoundError
        if member.role not in set(allowed_roles):
            raise ProjectPermissionError
        return project


def _is_admin(user: User) -> bool:
    return user.role is UserRole.ADMIN


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
