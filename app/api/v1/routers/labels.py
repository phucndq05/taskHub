from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status

from app.api.dependencies import CurrentActiveUserDep, LabelServiceDep
from app.schemas.label import LabelCreate, LabelRead, LabelUpdate
from app.services.label import (
    DuplicateLabelNameError,
    LabelNotFoundError,
    LabelPermissionError,
    LabelProjectNotFoundError,
    LabelTaskNotFoundError,
    NoLabelChangesError,
    TaskLabelAlreadyExistsError,
    TaskLabelNotFoundError,
)

router = APIRouter(tags=["labels"])


@router.post(
    "/projects/{project_id}/labels",
    response_model=LabelRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_label(
    project_id: UUID,
    request: LabelCreate,
    current_user: CurrentActiveUserDep,
    service: LabelServiceDep,
) -> LabelRead:
    try:
        return await service.create_label(current_user, project_id, request)
    except DuplicateLabelNameError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Label name already exists",
        ) from exc
    except LabelProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        ) from exc
    except LabelPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough label permissions",
        ) from exc


@router.get("/projects/{project_id}/labels", response_model=list[LabelRead])
async def list_labels(
    project_id: UUID,
    current_user: CurrentActiveUserDep,
    service: LabelServiceDep,
) -> list[LabelRead]:
    try:
        return await service.list_labels(current_user, project_id)
    except LabelProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        ) from exc
    except LabelPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough label permissions",
        ) from exc


@router.get("/labels/{label_id}", response_model=LabelRead)
async def get_label(
    label_id: UUID,
    current_user: CurrentActiveUserDep,
    service: LabelServiceDep,
) -> LabelRead:
    try:
        return await service.get_label(current_user, label_id)
    except LabelNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Label not found",
        ) from exc
    except LabelPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough label permissions",
        ) from exc


@router.patch("/labels/{label_id}", response_model=LabelRead)
async def update_label(
    label_id: UUID,
    request: LabelUpdate,
    current_user: CurrentActiveUserDep,
    service: LabelServiceDep,
) -> LabelRead:
    try:
        return await service.update_label(current_user, label_id, request)
    except NoLabelChangesError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No label changes provided",
        ) from exc
    except DuplicateLabelNameError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Label name already exists",
        ) from exc
    except LabelNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Label not found",
        ) from exc
    except LabelPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough label permissions",
        ) from exc


@router.delete("/labels/{label_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_label(
    label_id: UUID,
    current_user: CurrentActiveUserDep,
    service: LabelServiceDep,
) -> Response:
    try:
        await service.delete_label(current_user, label_id)
    except LabelNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Label not found",
        ) from exc
    except LabelPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough label permissions",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/tasks/{task_id}/labels/{label_id}",
    response_model=LabelRead,
    status_code=status.HTTP_201_CREATED,
)
async def attach_label(
    task_id: UUID,
    label_id: UUID,
    current_user: CurrentActiveUserDep,
    service: LabelServiceDep,
) -> LabelRead:
    try:
        return await service.attach_label(current_user, task_id, label_id)
    except TaskLabelAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Task label already exists",
        ) from exc
    except LabelTaskNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        ) from exc
    except LabelNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Label not found",
        ) from exc
    except LabelPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough label permissions",
        ) from exc


@router.delete(
    "/tasks/{task_id}/labels/{label_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def detach_label(
    task_id: UUID,
    label_id: UUID,
    current_user: CurrentActiveUserDep,
    service: LabelServiceDep,
) -> Response:
    try:
        await service.detach_label(current_user, task_id, label_id)
    except TaskLabelNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task label not found",
        ) from exc
    except LabelTaskNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        ) from exc
    except LabelNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Label not found",
        ) from exc
    except LabelPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough label permissions",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
