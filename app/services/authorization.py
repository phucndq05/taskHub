from collections.abc import Collection
from uuid import UUID

from app.models.enums import UserRole, WorkspaceMemberRole
from app.models.user import User
from app.models.workspace_member import WorkspaceMember
from app.repositories.workspace import WorkspaceRepository


def is_admin(user: User) -> bool:
    """Return whether a user has the system-wide administrator override."""
    return user.role is UserRole.ADMIN


async def get_workspace_member(
    repository: WorkspaceRepository,
    workspace_id: UUID,
    user_id: UUID,
) -> WorkspaceMember | None:
    """Load a user's membership in a workspace."""
    return await repository.get_member(workspace_id, user_id)


def workspace_role_is_allowed(
    role: WorkspaceMemberRole,
    allowed_roles: Collection[WorkspaceMemberRole],
) -> bool:
    """Return whether a workspace role is permitted for an action."""
    return role in allowed_roles
