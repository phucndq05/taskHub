import json
import logging
from uuid import UUID

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.models.enums import TaskPriority, TaskStatus
from app.schemas.task import TaskListResponse

DEFAULT_PROJECT_CACHE_VERSION = "0"
TASK_LIST_CACHE_KEY_VERSION = "v1"
TASK_LIST_CACHE_NAMESPACE = "taskhub"

logger = logging.getLogger(__name__)


class TaskListCache:
    """Redis cache for project task-list responses."""

    def __init__(
        self,
        redis_client: Redis,
        *,
        ttl_seconds: int,
        namespace: str = TASK_LIST_CACHE_NAMESPACE,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("Task-list cache TTL must be positive.")

        self._redis = redis_client
        self._ttl_seconds = ttl_seconds
        self._namespace = namespace

    def build_version_key(self, project_id: UUID) -> str:
        return (
            f"{self._namespace}:{TASK_LIST_CACHE_KEY_VERSION}:task-list:"
            f"project:{project_id}:version"
        )

    def build_data_key(
        self,
        project_id: UUID,
        *,
        version: str,
        status: TaskStatus | None,
        priority: TaskPriority | None,
        assignee_id: UUID | None,
        page: int,
        limit: int,
    ) -> str:
        return (
            f"{self._namespace}:{TASK_LIST_CACHE_KEY_VERSION}:task-list:"
            f"project:{project_id}:version:{version}:"
            f"status:{self._normalize_enum(status)}:"
            f"priority:{self._normalize_enum(priority)}:"
            f"assignee:{self._normalize_uuid(assignee_id)}:"
            f"page:{page}:limit:{limit}"
        )

    async def get_project_version(self, project_id: UUID) -> str | None:
        try:
            value = await self._redis.get(self.build_version_key(project_id))
        except RedisError:
            logger.warning(
                "Task-list cache version read failed; using PostgreSQL.",
                exc_info=True,
            )
            return None

        if value is None:
            return DEFAULT_PROJECT_CACHE_VERSION

        try:
            return str(int(value))
        except (TypeError, ValueError):
            logger.warning("Task-list cache version is invalid; using PostgreSQL.")
            return None

    async def get_task_list(
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
        key = self.build_data_key(
            project_id,
            version=version,
            status=status,
            priority=priority,
            assignee_id=assignee_id,
            page=page,
            limit=limit,
        )

        try:
            payload = await self._redis.get(key)
        except RedisError:
            logger.warning(
                "Task-list cache read failed; using PostgreSQL.",
                exc_info=True,
            )
            return None

        if payload is None:
            return None

        try:
            return TaskListResponse.model_validate(json.loads(payload))
        except (TypeError, json.JSONDecodeError, ValidationError):
            logger.warning("Task-list cache payload is invalid; using PostgreSQL.")
            return None

    async def set_task_list(
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
        key = self.build_data_key(
            project_id,
            version=version,
            status=status,
            priority=priority,
            assignee_id=assignee_id,
            page=page,
            limit=limit,
        )
        payload = json.dumps(
            response.model_dump(mode="json"),
            separators=(",", ":"),
            sort_keys=True,
        )

        try:
            await self._redis.set(key, payload, ex=self._ttl_seconds)
        except RedisError:
            logger.warning(
                "Task-list cache write failed; returning PostgreSQL response.",
                exc_info=True,
            )

    async def invalidate_project(self, project_id: UUID) -> None:
        try:
            await self._redis.incr(self.build_version_key(project_id))
        except RedisError:
            logger.warning(
                "Task-list cache invalidation failed after database commit.",
                exc_info=True,
            )

    def _normalize_uuid(self, value: UUID | None) -> str:
        if value is None:
            return "none"
        return str(value)

    def _normalize_enum(self, value: TaskStatus | TaskPriority | None) -> str:
        if value is None:
            return "none"
        return value.value
