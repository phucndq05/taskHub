from collections.abc import Collection
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.cache import TaskListCache
from app.integrations.email import AssignmentEmailPayload
from app.models.enums import TaskPriority, TaskStatus, WorkspaceMemberRole
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.repositories.task import TaskRepository
from app.repositories.user import UserRepository
from app.repositories.workspace import WorkspaceRepository
from app.schemas.task import TaskCreate, TaskListResponse, TaskRead, TaskUpdate
from app.services.authorization import (
    get_workspace_member,
    is_admin,
    workspace_role_is_allowed,
)


class ProjectNotFoundError(Exception):
    """Raised when a task project does not exist."""


class TaskNotFoundError(Exception):
    """Raised when a task does not exist."""


class TaskPermissionError(Exception):
    """Raised when a known workspace member lacks task permission."""


class AssigneeNotFoundError(Exception):
    """Raised when the requested assignee user does not exist."""


class AssigneeNotWorkspaceMemberError(Exception):
    """Raised when the assignee is not a member of the project workspace."""


@dataclass(frozen=True)
class TaskMutationResult:
    """Task mutation response plus optional post-commit assignment email payload."""

    task: TaskRead
    assignment_email: AssignmentEmailPayload | None


class TaskService:
    """Coordinate task business rules and transaction boundaries."""

    def __init__(
        self,
        repository: TaskRepository,
        user_repository: UserRepository,
        workspace_repository: WorkspaceRepository,
        session: AsyncSession,
        task_list_cache: TaskListCache | None = None,
    ) -> None:
        self._repository = repository
        self._user_repository = user_repository
        self._workspace_repository = workspace_repository
        self._session = session
        self._task_list_cache = task_list_cache

    async def create_task(
        self,
        current_user: User,
        project_id: UUID,
        task: TaskCreate,
    ) -> TaskMutationResult:
        project = await self._get_project_for_action(
            current_user,
            project_id,
            allowed_roles=(
                WorkspaceMemberRole.OWNER,
                WorkspaceMemberRole.EDITOR,
            ),
        )

        assignee: User | None = None
        if task.assignee_id is not None:
            assignee = await self._validate_assignee(
                project.workspace_id,
                task.assignee_id,
            )

        task_model = Task(
            project_id=project_id,
            assignee_id=task.assignee_id,
            title=task.title,
            description=task.description,
            status=task.status,
            priority=task.priority,
            due_date=task.due_date,
            created_by=current_user.id,
        )
        created_task = await self._repository.create(task_model)
        await self._commit()
        await self._invalidate_task_list(project_id)
        return TaskMutationResult(
            task=self._to_read_model(created_task),
            assignment_email=self._build_assignment_email_payload(
                assignee=assignee,
                task=created_task,
                project=project,
                assigner=current_user,
            ),
        )

    async def list_tasks(
        self,
        current_user: User,
        project_id: UUID,
        *,
        status: TaskStatus | None,
        priority: TaskPriority | None,
        assignee_id: UUID | None,
        page: int,
        limit: int,
    ) -> TaskListResponse:
        await self._get_project_for_action(
            current_user,
            project_id,
            allowed_roles=(
                WorkspaceMemberRole.OWNER,
                WorkspaceMemberRole.EDITOR,
                WorkspaceMemberRole.VIEWER,
            ),
        )

        cache_version = await self._get_task_list_cache_version(project_id)
        if cache_version is not None:
            cached_response = await self._get_cached_task_list(
                project_id,
                version=cache_version,
                status=status,
                priority=priority,
                assignee_id=assignee_id,
                page=page,
                limit=limit,
            )
            if cached_response is not None:
                return cached_response

        total = await self._repository.count_by_project(
            project_id,
            status=status,
            priority=priority,
            assignee_id=assignee_id,
        )
        tasks = await self._repository.list_by_project(
            project_id,
            status=status,
            priority=priority,
            assignee_id=assignee_id,
            page=page,
            limit=limit,
        )
        total_pages = 0 if total == 0 else (total + limit - 1) // limit
        response = TaskListResponse(
            items=[self._to_read_model(task) for task in tasks],
            page=page,
            limit=limit,
            total=total,
            total_pages=total_pages,
        )
        if cache_version is not None:
            await self._set_cached_task_list(
                project_id,
                version=cache_version,
                status=status,
                priority=priority,
                assignee_id=assignee_id,
                page=page,
                limit=limit,
                response=response,
            )
        return response

    async def get_task(self, current_user: User, task_id: UUID) -> TaskRead:
        task, _ = await self._get_task_for_action(
            current_user,
            task_id,
            allowed_roles=(
                WorkspaceMemberRole.OWNER,
                WorkspaceMemberRole.EDITOR,
                WorkspaceMemberRole.VIEWER,
            ),
        )
        return self._to_read_model(task)

    async def update_task(
        self,
        current_user: User,
        task_id: UUID,
        task_update: TaskUpdate,
    ) -> TaskMutationResult:
        task, project = await self._get_task_for_action(
            current_user,
            task_id,
            allowed_roles=(
                WorkspaceMemberRole.OWNER,
                WorkspaceMemberRole.EDITOR,
            ),
        )

        previous_assignee_id = task.assignee_id
        assignee: User | None = None
        if (
            "assignee_id" in task_update.model_fields_set
            and task_update.assignee_id is not None
            and task_update.assignee_id != previous_assignee_id
        ):
            assignee = await self._validate_assignee(
                project.workspace_id,
                task_update.assignee_id,
            )

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
        await self._invalidate_task_list(project.id)
        return TaskMutationResult(
            task=self._to_read_model(updated_task),
            assignment_email=self._build_assignment_email_payload(
                assignee=assignee,
                task=updated_task,
                project=project,
                assigner=current_user,
            ),
        )

    async def delete_task(self, current_user: User, task_id: UUID) -> None:
        task, _ = await self._get_task_for_action(
            current_user,
            task_id,
            allowed_roles=(
                WorkspaceMemberRole.OWNER,
                WorkspaceMemberRole.EDITOR,
            ),
        )
        project_id = task.project_id

        await self._repository.delete(task)
        await self._commit()
        await self._invalidate_task_list(project_id)

    async def _get_task_list_cache_version(self, project_id: UUID) -> str | None:
        if self._task_list_cache is None:
            return None
        return await self._task_list_cache.get_project_version(project_id)

    async def _get_cached_task_list(
        self,
        project_id: UUID,
        *,
        version: str,
        status: TaskStatus | None,
        priority: TaskPriority | None,
        assignee_id: UUID | None,
        page: int,
        limit: int,
    ) -> TaskListResponse | None:
        if self._task_list_cache is None:
            return None
        return await self._task_list_cache.get_task_list(
            project_id,
            version=version,
            status=status,
            priority=priority,
            assignee_id=assignee_id,
            page=page,
            limit=limit,
        )

    async def _set_cached_task_list(
        self,
        project_id: UUID,
        *,
        version: str,
        status: TaskStatus | None,
        priority: TaskPriority | None,
        assignee_id: UUID | None,
        page: int,
        limit: int,
        response: TaskListResponse,
    ) -> None:
        if self._task_list_cache is None:
            return
        await self._task_list_cache.set_task_list(
            project_id,
            version=version,
            status=status,
            priority=priority,
            assignee_id=assignee_id,
            page=page,
            limit=limit,
            response=response,
        )

    async def _invalidate_task_list(self, project_id: UUID) -> None:
        if self._task_list_cache is None:
            return
        await self._task_list_cache.invalidate_project(project_id)

    async def _validate_assignee(self, workspace_id: UUID, assignee_id: UUID) -> User:
        assignee = await self._user_repository.get_by_id(assignee_id)
        if assignee is None:
            raise AssigneeNotFoundError

        is_member = await self._repository.workspace_member_exists(
            workspace_id,
            assignee_id,
        )
        if not is_member:
            raise AssigneeNotWorkspaceMemberError

        return assignee

    def _build_assignment_email_payload(
        self,
        *,
        assignee: User | None,
        task: Task,
        project: Project,
        assigner: User,
    ) -> AssignmentEmailPayload | None:
        if assignee is None:
            return None
        return AssignmentEmailPayload(
            recipient_email=assignee.email,
            recipient_name=assignee.full_name,
            task_id=str(task.id),
            task_title=task.title,
            project_name=project.name,
            assigner_name=assigner.full_name,
        )

    async def _get_project_for_action(
        self,
        current_user: User,
        project_id: UUID,
        *,
        allowed_roles: Collection[WorkspaceMemberRole],
    ) -> Project:
        project = await self._repository.get_project(project_id)
        if project is None:
            raise ProjectNotFoundError

        await self._authorize_project_workspace(
            current_user,
            project.workspace_id,
            hidden_error=ProjectNotFoundError,
            allowed_roles=allowed_roles,
        )
        return project

    async def _get_task_for_action(
        self,
        current_user: User,
        task_id: UUID,
        *,
        allowed_roles: Collection[WorkspaceMemberRole],
    ) -> tuple[Task, Project]:
        context = await self._repository.get_task_context(task_id)
        if context is None:
            raise TaskNotFoundError

        task, project = context
        await self._authorize_project_workspace(
            current_user,
            project.workspace_id,
            hidden_error=TaskNotFoundError,
            allowed_roles=allowed_roles,
        )
        return task, project

    async def _authorize_project_workspace(
        self,
        current_user: User,
        workspace_id: UUID,
        *,
        hidden_error: type[Exception],
        allowed_roles: Collection[WorkspaceMemberRole],
    ) -> None:
        if is_admin(current_user):
            return

        member = await get_workspace_member(
            self._workspace_repository,
            workspace_id,
            current_user.id,
        )
        if member is None:
            raise hidden_error
        if not workspace_role_is_allowed(member.role, allowed_roles):
            raise TaskPermissionError

    async def _commit(self) -> None:
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

    def _to_read_model(self, task: Task) -> TaskRead:
        return TaskRead.model_validate(task)
