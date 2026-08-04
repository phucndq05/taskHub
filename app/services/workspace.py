from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import UserRole, WorkspaceMemberRole
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember
from app.repositories.user import UserRepository
from app.repositories.workspace import WorkspaceRepository
from app.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceMemberAdd,
    WorkspaceMemberRead,
    WorkspaceMemberRoleUpdate,
    WorkspaceRead,
    WorkspaceUpdate,
)

WORKSPACE_MEMBER_PK = "pk_workspace_members"
PROJECT_WORKSPACE_FK = "fk_projects_workspace_id_workspaces"


class WorkspaceNotFoundError(Exception):
    """Raised when a workspace is missing or hidden from the actor."""


class WorkspacePermissionError(Exception):
    """Raised when a known workspace member lacks permission."""


class NoWorkspaceChangesError(Exception):
    """Raised when a workspace PATCH request contains no editable changes."""


class WorkspaceMemberAlreadyExistsError(Exception):
    """Raised when a user already belongs to a workspace."""


class WorkspaceMemberNotFoundError(Exception):
    """Raised when a target workspace member does not exist."""


class WorkspaceMemberUserNotFoundError(Exception):
    """Raised when a requested member email does not match a registered user."""


class InactiveWorkspaceMemberUserError(Exception):
    """Raised when a requested member user is inactive."""


class OwnerMembershipMutationError(Exception):
    """Raised when attempting to remove or demote the workspace owner."""


class WorkspaceHasProjectsError(Exception):
    """Raised when a workspace cannot be deleted because projects reference it."""


class WorkspaceService:
    """Coordinate workspace and membership business rules."""

    def __init__(
        self,
        workspace_repository: WorkspaceRepository,
        user_repository: UserRepository,
        session: AsyncSession,
    ) -> None:
        self._workspace_repository = workspace_repository
        self._user_repository = user_repository
        self._session = session

    async def create_workspace(
        self,
        current_user: User,
        request: WorkspaceCreate,
    ) -> WorkspaceRead:
        workspace = Workspace(name=request.name, owner_id=current_user.id)
        owner_member = WorkspaceMember(
            workspace_id=workspace.id,
            user_id=current_user.id,
            role=WorkspaceMemberRole.OWNER,
        )

        try:
            created_workspace = await self._workspace_repository.create(workspace)
            owner_member.workspace_id = created_workspace.id
            await self._workspace_repository.create_member(owner_member)
            await self._commit()
        except Exception:
            await self._session.rollback()
            raise

        return WorkspaceRead.model_validate(created_workspace)

    async def list_workspaces(self, current_user: User) -> list[WorkspaceRead]:
        if _is_admin(current_user):
            workspaces = await self._workspace_repository.list_all()
        else:
            workspaces = await self._workspace_repository.list_for_member(
                current_user.id
            )
        return [WorkspaceRead.model_validate(workspace) for workspace in workspaces]

    async def get_workspace(
        self,
        current_user: User,
        workspace_id: UUID,
    ) -> WorkspaceRead:
        workspace = await self._get_visible_workspace(current_user, workspace_id)
        return WorkspaceRead.model_validate(workspace)

    async def update_workspace(
        self,
        current_user: User,
        workspace_id: UUID,
        request: WorkspaceUpdate,
    ) -> WorkspaceRead:
        workspace = await self._get_mutable_workspace(current_user, workspace_id)
        if "name" not in request.model_fields_set:
            raise NoWorkspaceChangesError

        assert request.name is not None
        workspace.name = request.name
        updated_workspace = await self._workspace_repository.update(workspace)
        await self._commit()
        return WorkspaceRead.model_validate(updated_workspace)

    async def delete_workspace(
        self,
        current_user: User,
        workspace_id: UUID,
    ) -> None:
        await self._get_mutable_workspace(current_user, workspace_id)
        if await self._workspace_repository.has_projects(workspace_id):
            raise WorkspaceHasProjectsError

        try:
            await self._workspace_repository.delete_workspace_by_id(workspace_id)
            await self._commit()
        except IntegrityError as exc:
            await self._session.rollback()
            if _constraint_name(exc) == PROJECT_WORKSPACE_FK:
                raise WorkspaceHasProjectsError from exc
            raise

    async def list_members(
        self,
        current_user: User,
        workspace_id: UUID,
    ) -> list[WorkspaceMemberRead]:
        await self._get_visible_workspace(current_user, workspace_id)
        member_rows = await self._workspace_repository.list_members_with_users(
            workspace_id
        )
        return [_member_read(member, user) for member, user in member_rows]

    async def add_member(
        self,
        current_user: User,
        workspace_id: UUID,
        request: WorkspaceMemberAdd,
    ) -> WorkspaceMemberRead:
        await self._get_mutable_workspace(current_user, workspace_id)
        user = await self._user_repository.get_by_email(request.email)
        if user is None:
            raise WorkspaceMemberUserNotFoundError
        if not user.is_active:
            raise InactiveWorkspaceMemberUserError

        existing_member = await self._workspace_repository.get_member(
            workspace_id,
            user.id,
        )
        if existing_member is not None:
            raise WorkspaceMemberAlreadyExistsError

        member = WorkspaceMember(
            workspace_id=workspace_id,
            user_id=user.id,
            role=request.role,
        )
        try:
            created_member = await self._workspace_repository.create_member(member)
            await self._commit()
        except IntegrityError as exc:
            await self._session.rollback()
            if _constraint_name(exc) == WORKSPACE_MEMBER_PK:
                raise WorkspaceMemberAlreadyExistsError from exc
            raise

        return _member_read(created_member, user)

    async def update_member_role(
        self,
        current_user: User,
        workspace_id: UUID,
        user_id: UUID,
        request: WorkspaceMemberRoleUpdate,
    ) -> WorkspaceMemberRead:
        workspace = await self._get_mutable_workspace(current_user, workspace_id)
        member = await self._workspace_repository.get_member(workspace_id, user_id)
        if member is None:
            raise WorkspaceMemberNotFoundError
        if _is_owner_membership(workspace, member):
            raise OwnerMembershipMutationError

        member.role = request.role
        updated_member = await self._workspace_repository.update_member(member)
        await self._commit()

        member_row = await self._workspace_repository.get_member_with_user(
            workspace_id,
            user_id,
        )
        if member_row is None:
            raise WorkspaceMemberNotFoundError
        _, user = member_row
        return _member_read(updated_member, user)

    async def remove_member(
        self,
        current_user: User,
        workspace_id: UUID,
        user_id: UUID,
    ) -> None:
        workspace = await self._get_mutable_workspace(current_user, workspace_id)
        member = await self._workspace_repository.get_member(workspace_id, user_id)
        if member is None:
            raise WorkspaceMemberNotFoundError
        if _is_owner_membership(workspace, member):
            raise OwnerMembershipMutationError

        await self._workspace_repository.delete_member(member)
        await self._commit()

    async def _get_visible_workspace(
        self,
        current_user: User,
        workspace_id: UUID,
    ) -> Workspace:
        workspace = await self._workspace_repository.get_by_id(workspace_id)
        if workspace is None:
            raise WorkspaceNotFoundError

        if _is_admin(current_user):
            return workspace

        member = await self._workspace_repository.get_member(
            workspace_id,
            current_user.id,
        )
        if member is None:
            raise WorkspaceNotFoundError
        return workspace

    async def _get_mutable_workspace(
        self,
        current_user: User,
        workspace_id: UUID,
    ) -> Workspace:
        workspace = await self._workspace_repository.get_by_id(workspace_id)
        if workspace is None:
            raise WorkspaceNotFoundError

        if _is_admin(current_user):
            return workspace

        member = await self._workspace_repository.get_member(
            workspace_id,
            current_user.id,
        )
        if member is None:
            raise WorkspaceNotFoundError
        if member.role is not WorkspaceMemberRole.OWNER:
            raise WorkspacePermissionError
        return workspace

    async def _commit(self) -> None:
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise


def _is_admin(user: User) -> bool:
    return user.role is UserRole.ADMIN


def _is_owner_membership(
    workspace: Workspace,
    member: WorkspaceMember,
) -> bool:
    return (
        member.user_id == workspace.owner_id or member.role is WorkspaceMemberRole.OWNER
    )


def _member_read(member: WorkspaceMember, user: User) -> WorkspaceMemberRead:
    return WorkspaceMemberRead(
        workspace_id=member.workspace_id,
        user_id=member.user_id,
        email=user.email,
        full_name=user.full_name,
        role=member.role,
        joined_at=member.joined_at,
    )


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
