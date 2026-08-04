from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status

from app.api.dependencies import CurrentActiveUserDep, WorkspaceServiceDep
from app.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceMemberAdd,
    WorkspaceMemberRead,
    WorkspaceMemberRoleUpdate,
    WorkspaceRead,
    WorkspaceUpdate,
)
from app.services.workspace import (
    InactiveWorkspaceMemberUserError,
    NoWorkspaceChangesError,
    OwnerMembershipMutationError,
    WorkspaceHasProjectsError,
    WorkspaceMemberAlreadyExistsError,
    WorkspaceMemberNotFoundError,
    WorkspaceMemberUserNotFoundError,
    WorkspaceNotFoundError,
    WorkspacePermissionError,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.post(
    "",
    response_model=WorkspaceRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace(
    request: WorkspaceCreate,
    current_user: CurrentActiveUserDep,
    service: WorkspaceServiceDep,
) -> WorkspaceRead:
    return await service.create_workspace(current_user, request)


@router.get("", response_model=list[WorkspaceRead])
async def list_workspaces(
    current_user: CurrentActiveUserDep,
    service: WorkspaceServiceDep,
) -> list[WorkspaceRead]:
    return await service.list_workspaces(current_user)


@router.get("/{workspace_id}", response_model=WorkspaceRead)
async def get_workspace(
    workspace_id: UUID,
    current_user: CurrentActiveUserDep,
    service: WorkspaceServiceDep,
) -> WorkspaceRead:
    try:
        return await service.get_workspace(current_user, workspace_id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        ) from exc


@router.patch("/{workspace_id}", response_model=WorkspaceRead)
async def update_workspace(
    workspace_id: UUID,
    request: WorkspaceUpdate,
    current_user: CurrentActiveUserDep,
    service: WorkspaceServiceDep,
) -> WorkspaceRead:
    try:
        return await service.update_workspace(current_user, workspace_id, request)
    except NoWorkspaceChangesError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No workspace changes provided",
        ) from exc
    except WorkspaceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        ) from exc
    except WorkspacePermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough workspace permissions",
        ) from exc


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    workspace_id: UUID,
    current_user: CurrentActiveUserDep,
    service: WorkspaceServiceDep,
) -> Response:
    try:
        await service.delete_workspace(current_user, workspace_id)
    except WorkspaceHasProjectsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workspace contains projects",
        ) from exc
    except WorkspaceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        ) from exc
    except WorkspacePermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough workspace permissions",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMemberRead])
async def list_members(
    workspace_id: UUID,
    current_user: CurrentActiveUserDep,
    service: WorkspaceServiceDep,
) -> list[WorkspaceMemberRead]:
    try:
        return await service.list_members(current_user, workspace_id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        ) from exc


@router.post(
    "/{workspace_id}/members",
    response_model=WorkspaceMemberRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    workspace_id: UUID,
    request: WorkspaceMemberAdd,
    current_user: CurrentActiveUserDep,
    service: WorkspaceServiceDep,
) -> WorkspaceMemberRead:
    try:
        return await service.add_member(current_user, workspace_id, request)
    except WorkspaceMemberAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workspace member already exists",
        ) from exc
    except InactiveWorkspaceMemberUserError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Target user is inactive",
        ) from exc
    except WorkspaceMemberUserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        ) from exc
    except WorkspaceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        ) from exc
    except WorkspacePermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough workspace permissions",
        ) from exc


@router.patch(
    "/{workspace_id}/members/{user_id}",
    response_model=WorkspaceMemberRead,
)
async def update_member_role(
    workspace_id: UUID,
    user_id: UUID,
    request: WorkspaceMemberRoleUpdate,
    current_user: CurrentActiveUserDep,
    service: WorkspaceServiceDep,
) -> WorkspaceMemberRead:
    try:
        return await service.update_member_role(
            current_user,
            workspace_id,
            user_id,
            request,
        )
    except OwnerMembershipMutationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workspace owner membership cannot be changed",
        ) from exc
    except WorkspaceMemberNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace member not found",
        ) from exc
    except WorkspaceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        ) from exc
    except WorkspacePermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough workspace permissions",
        ) from exc


@router.delete(
    "/{workspace_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_member(
    workspace_id: UUID,
    user_id: UUID,
    current_user: CurrentActiveUserDep,
    service: WorkspaceServiceDep,
) -> Response:
    try:
        await service.remove_member(current_user, workspace_id, user_id)
    except OwnerMembershipMutationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workspace owner membership cannot be changed",
        ) from exc
    except WorkspaceMemberNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace member not found",
        ) from exc
    except WorkspaceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        ) from exc
    except WorkspacePermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough workspace permissions",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
