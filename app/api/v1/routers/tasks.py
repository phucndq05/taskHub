from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status

from app.api.dependencies import TaskServiceDep
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(task: TaskCreate, service: TaskServiceDep) -> TaskRead:
    return service.create_task(task)


@router.get("", response_model=list[TaskRead])
def list_tasks(service: TaskServiceDep) -> list[TaskRead]:
    return service.list_tasks()


@router.get("/{task_id}", response_model=TaskRead)
def get_task(task_id: UUID, service: TaskServiceDep) -> TaskRead:
    task = service.get_task(task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found.",
        )
    return task


@router.patch("/{task_id}", response_model=TaskRead)
def update_task(
    task_id: UUID,
    task_update: TaskUpdate,
    service: TaskServiceDep,
) -> TaskRead:
    task = service.update_task(task_id, task_update)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found.",
        )
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: UUID, service: TaskServiceDep) -> Response:
    deleted = service.delete_task(task_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
