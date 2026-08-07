from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    HTTPException,
    Path,
    Query,
    Response,
    status,
)

from app.api.dependencies import CurrentActiveUserDep, EmailSenderDep, TaskServiceDep
from app.integrations.email import send_assignment_email_safely
from app.models.enums import TaskPriority, TaskStatus
from app.schemas.task import TaskCreate, TaskListResponse, TaskRead, TaskUpdate
from app.services.task import (
    AssigneeNotFoundError,
    AssigneeNotWorkspaceMemberError,
    ProjectNotFoundError,
    TaskNotFoundError,
    TaskPermissionError,
)

router = APIRouter(tags=["tasks"])


@router.post(
    "/projects/{project_id}/tasks",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(
    project_id: UUID,
    task: TaskCreate,
    background_tasks: BackgroundTasks,
    current_user: CurrentActiveUserDep,
    service: TaskServiceDep,
    email_sender: EmailSenderDep,
) -> TaskRead:
    try:
        result = await service.create_task(current_user, project_id, task)
        if result.assignment_email is not None:
            background_tasks.add_task(
                send_assignment_email_safely,
                email_sender,
                result.assignment_email,
            )
        return result.task
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        ) from exc
    except TaskPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough task permissions.",
        ) from exc
    except AssigneeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assignee not found.",
        ) from exc
    except AssigneeNotWorkspaceMemberError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Assignee is not a member of the project workspace.",
        ) from exc


@router.get(
    "/projects/{project_id}/tasks",
    response_model=TaskListResponse,
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Missing or invalid Bearer access token.",
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Project was not found or is hidden from the user.",
        },
    },
)
async def list_tasks(
    project_id: Annotated[
        UUID,
        Path(description="Project whose tasks are listed."),
    ],
    current_user: CurrentActiveUserDep,
    service: TaskServiceDep,
    task_status: Annotated[
        TaskStatus | None,
        Query(alias="status", description="Filter by task workflow status."),
    ] = None,
    priority: Annotated[
        TaskPriority | None,
        Query(description="Filter by task priority."),
    ] = None,
    assignee_id: Annotated[
        UUID | None,
        Query(description="Filter to tasks assigned to this user ID."),
    ] = None,
    page: Annotated[
        int,
        Query(ge=1, description="Page number, starting at 1."),
    ] = 1,
    limit: Annotated[
        int,
        Query(ge=1, le=100, description="Maximum tasks per page, from 1 through 100."),
    ] = 20,
) -> TaskListResponse:
    try:
        return await service.list_tasks(
            current_user,
            project_id,
            status=task_status,
            priority=priority,
            assignee_id=assignee_id,
            page=page,
            limit=limit,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        ) from exc
    except TaskPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough task permissions.",
        ) from exc


@router.get("/tasks/{task_id}", response_model=TaskRead)
async def get_task(
    task_id: UUID,
    current_user: CurrentActiveUserDep,
    service: TaskServiceDep,
) -> TaskRead:
    try:
        return await service.get_task(current_user, task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found.",
        ) from exc
    except TaskPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough task permissions.",
        ) from exc


@router.patch("/tasks/{task_id}", response_model=TaskRead)
async def update_task(
    task_id: UUID,
    task_update: TaskUpdate,
    background_tasks: BackgroundTasks,
    current_user: CurrentActiveUserDep,
    service: TaskServiceDep,
    email_sender: EmailSenderDep,
) -> TaskRead:
    try:
        result = await service.update_task(current_user, task_id, task_update)
        if result.assignment_email is not None:
            background_tasks.add_task(
                send_assignment_email_safely,
                email_sender,
                result.assignment_email,
            )
        return result.task
    except TaskNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found.",
        ) from exc
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        ) from exc
    except TaskPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough task permissions.",
        ) from exc
    except AssigneeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assignee not found.",
        ) from exc
    except AssigneeNotWorkspaceMemberError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Assignee is not a member of the project workspace.",
        ) from exc


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: UUID,
    current_user: CurrentActiveUserDep,
    service: TaskServiceDep,
) -> Response:
    try:
        await service.delete_task(current_user, task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found.",
        ) from exc
    except TaskPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough task permissions.",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
