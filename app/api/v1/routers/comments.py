from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status

from app.api.dependencies import CommentServiceDep, CurrentActiveUserDep
from app.schemas.comment import CommentCreate, CommentRead
from app.services.comment import (
    CommentNotFoundError,
    CommentPermissionError,
    CommentTaskNotFoundError,
)

router = APIRouter(tags=["comments"])


@router.post(
    "/tasks/{task_id}/comments",
    response_model=CommentRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_comment(
    task_id: UUID,
    request: CommentCreate,
    current_user: CurrentActiveUserDep,
    service: CommentServiceDep,
) -> CommentRead:
    try:
        return await service.create_comment(current_user, task_id, request)
    except CommentTaskNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        ) from exc
    except CommentPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough comment permissions",
        ) from exc


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment_id: UUID,
    current_user: CurrentActiveUserDep,
    service: CommentServiceDep,
) -> Response:
    try:
        await service.delete_comment(current_user, comment_id)
    except CommentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comment not found",
        ) from exc
    except CommentPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough comment permissions",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
