from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status

from app.api.dependencies import CurrentActiveUserDep, ProjectServiceDep
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from app.services.project import (
    ActiveProjectDeleteError,
    NoProjectChangesError,
    ProjectHasChildrenError,
    ProjectNotFoundError,
    ProjectPermissionError,
    ProjectWorkspaceNotFoundError,
)

router = APIRouter(tags=["projects"])


@router.post(
    "/workspaces/{workspace_id}/projects",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_project(
    workspace_id: UUID,
    request: ProjectCreate,
    current_user: CurrentActiveUserDep,
    service: ProjectServiceDep,
) -> ProjectRead:
    try:
        return await service.create_project(current_user, workspace_id, request)
    except ProjectWorkspaceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        ) from exc
    except ProjectPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough project permissions",
        ) from exc


@router.get(
    "/workspaces/{workspace_id}/projects",
    response_model=list[ProjectRead],
)
async def list_projects(
    workspace_id: UUID,
    current_user: CurrentActiveUserDep,
    service: ProjectServiceDep,
) -> list[ProjectRead]:
    try:
        return await service.list_projects(current_user, workspace_id)
    except ProjectWorkspaceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        ) from exc
    except ProjectPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough project permissions",
        ) from exc


@router.get("/projects/{project_id}", response_model=ProjectRead)
async def get_project(
    project_id: UUID,
    current_user: CurrentActiveUserDep,
    service: ProjectServiceDep,
) -> ProjectRead:
    try:
        return await service.get_project(current_user, project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        ) from exc
    except ProjectPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough project permissions",
        ) from exc


@router.patch("/projects/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: UUID,
    request: ProjectUpdate,
    current_user: CurrentActiveUserDep,
    service: ProjectServiceDep,
) -> ProjectRead:
    try:
        return await service.update_project(current_user, project_id, request)
    except NoProjectChangesError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No project changes provided",
        ) from exc
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        ) from exc
    except ProjectPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough project permissions",
        ) from exc


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: UUID,
    current_user: CurrentActiveUserDep,
    service: ProjectServiceDep,
) -> Response:
    try:
        await service.delete_project(current_user, project_id)
    except ActiveProjectDeleteError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project must be archived before deletion",
        ) from exc
    except ProjectHasChildrenError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project contains tasks or labels",
        ) from exc
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        ) from exc
    except ProjectPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough project permissions",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
