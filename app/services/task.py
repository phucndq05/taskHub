from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task
from app.repositories.task import TaskRepository
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate


class ProjectNotFoundError(Exception):
    """Raised when a task project does not exist."""


class TaskNotFoundError(Exception):
    """Raised when a task does not exist."""


class ActorNotFoundError(Exception):
    """Raised when the temporary actor user does not exist."""


class AssigneeNotFoundError(Exception):
    """Raised when the requested assignee user does not exist."""


class AssigneeNotWorkspaceMemberError(Exception):
    """Raised when the assignee is not a member of the project workspace."""


class TaskService:
    """Coordinate task business rules and transaction boundaries."""

    def __init__(self, repository: TaskRepository, session: AsyncSession) -> None:
        self._repository = repository
        self._session = session

    async def create_task(
        self,
        project_id: UUID,
        actor_id: UUID,
        task: TaskCreate,
    ) -> TaskRead:
        project = await self._repository.get_project(project_id)
        if project is None:
            raise ProjectNotFoundError

        actor_exists = await self._repository.user_exists(actor_id)
        if not actor_exists:
            raise ActorNotFoundError

        if task.assignee_id is not None:
            await self._validate_assignee(project.workspace_id, task.assignee_id)

        task_model = Task(
            project_id=project_id,
            assignee_id=task.assignee_id,
            title=task.title,
            description=task.description,
            status=task.status,
            priority=task.priority,
            due_date=task.due_date,
            created_by=actor_id,
        )
        created_task = await self._repository.create(task_model)
        await self._commit()
        return self._to_read_model(created_task)

    async def list_tasks(self, project_id: UUID) -> list[TaskRead]:
        project = await self._repository.get_project(project_id)
        if project is None:
            raise ProjectNotFoundError

        tasks = await self._repository.list_by_project(project_id)
        return [self._to_read_model(task) for task in tasks]

    async def get_task(self, task_id: UUID) -> TaskRead:
        task = await self._repository.get(task_id)
        if task is None:
            raise TaskNotFoundError
        return self._to_read_model(task)

    async def update_task(self, task_id: UUID, task_update: TaskUpdate) -> TaskRead:
        task = await self._repository.get(task_id)
        if task is None:
            raise TaskNotFoundError

        if (
            "assignee_id" in task_update.model_fields_set
            and task_update.assignee_id is not None
        ):
            project = await self._repository.get_project(task.project_id)
            if project is None:
                raise ProjectNotFoundError
            await self._validate_assignee(project.workspace_id, task_update.assignee_id)

        if "title" in task_update.model_fields_set:
            assert task_update.title is not None
            task.title = task_update.title
        if "description" in task_update.model_fields_set:
            task.description = task_update.description
        if "assignee_id" in task_update.model_fields_set:
            task.assignee_id = task_update.assignee_id
        if "status" in task_update.model_fields_set:
            assert task_update.status is not None
            task.status = task_update.status
        if "priority" in task_update.model_fields_set:
            assert task_update.priority is not None
            task.priority = task_update.priority
        if "due_date" in task_update.model_fields_set:
            task.due_date = task_update.due_date

        updated_task = await self._repository.update(task)
        await self._commit()
        return self._to_read_model(updated_task)

    async def delete_task(self, task_id: UUID) -> None:
        task = await self._repository.get(task_id)
        if task is None:
            raise TaskNotFoundError

        await self._repository.delete(task)
        await self._commit()

    async def _validate_assignee(self, workspace_id: UUID, assignee_id: UUID) -> None:
        assignee_exists = await self._repository.user_exists(assignee_id)
        if not assignee_exists:
            raise AssigneeNotFoundError

        is_member = await self._repository.workspace_member_exists(
            workspace_id,
            assignee_id,
        )
        if not is_member:
            raise AssigneeNotWorkspaceMemberError

    async def _commit(self) -> None:
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

    def _to_read_model(self, task: Task) -> TaskRead:
        return TaskRead.model_validate(task)
