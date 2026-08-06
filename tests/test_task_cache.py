import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from redis import asyncio as redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.integrations.cache import TaskListCache
from app.models.enums import TaskPriority, TaskStatus
from app.models.project import Project
from app.repositories.task import TaskRepository
from app.schemas.task import TaskListResponse, TaskRead
from tests.test_auth_api import set_user_active
from tests.test_tasks_api import (
    TaskApiContext,
    bearer_headers,
    insert_task,
    seed_task_context,
)


@dataclass
class RecordingTaskListCache:
    version: str | None = "0"
    stored: dict[tuple[Any, ...], TaskListResponse] = field(default_factory=dict)
    version_calls: list[UUID] = field(default_factory=list)
    get_calls: list[tuple[Any, ...]] = field(default_factory=list)
    set_calls: list[tuple[Any, ...]] = field(default_factory=list)
    invalidate_calls: list[UUID] = field(default_factory=list)

    async def get_project_version(self, project_id: UUID) -> str | None:
        self.version_calls.append(project_id)
        return self.version

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
        key = self._key(
            project_id=project_id,
            version=version,
            status=status,
            priority=priority,
            assignee_id=assignee_id,
            page=page,
            limit=limit,
        )
        self.get_calls.append(key)
        return self.stored.get(key)

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
        key = self._key(
            project_id=project_id,
            version=version,
            status=status,
            priority=priority,
            assignee_id=assignee_id,
            page=page,
            limit=limit,
        )
        self.set_calls.append(key)
        self.stored[key] = response

    async def invalidate_project(self, project_id: UUID) -> None:
        self.invalidate_calls.append(project_id)
        if self.version is not None:
            self.version = str(int(self.version) + 1)

    @staticmethod
    def _key(
        *,
        project_id: UUID,
        version: str,
        status: TaskStatus | None,
        priority: TaskPriority | None,
        assignee_id: UUID | None,
        page: int,
        limit: int,
    ) -> tuple[Any, ...]:
        return (
            project_id,
            version,
            status,
            priority,
            assignee_id,
            page,
            limit,
        )


class FakeRedisClient:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int] = {}
        self.fail_get = False
        self.fail_set = False
        self.fail_incr = False

    async def get(self, key: str) -> str | None:
        if self.fail_get:
            raise RedisConnectionError("cache unavailable")
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int) -> None:
        if self.fail_set:
            raise RedisConnectionError("cache unavailable")
        self.values[key] = value
        self.expirations[key] = ex

    async def incr(self, key: str) -> int:
        if self.fail_incr:
            raise RedisConnectionError("cache unavailable")
        next_value = int(self.values.get(key, "0")) + 1
        self.values[key] = str(next_value)
        return next_value


@pytest.fixture
def task_api_context(
    test_database_url: str, clean_test_database: None
) -> TaskApiContext:
    return asyncio.run(seed_task_context(test_database_url))


def build_task_list_response(project_id: UUID) -> TaskListResponse:
    created_at = datetime(2025, 1, 1, tzinfo=UTC)
    task_id = uuid4()

    return TaskListResponse(
        items=[
            TaskRead(
                id=task_id,
                project_id=project_id,
                assignee_id=None,
                title="Cached task",
                description=None,
                status=TaskStatus.TODO,
                priority=TaskPriority.MEDIUM,
                due_date=None,
                created_by=uuid4(),
                created_at=created_at,
                updated_at=created_at,
            )
        ],
        page=1,
        limit=20,
        total=1,
        total_pages=1,
    )


async def delete_project(database_url: str, project_id: UUID) -> None:
    engine = create_async_engine(database_url)
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            await session.execute(delete(Project).where(Project.id == project_id))
            await session.commit()
    finally:
        await engine.dispose()


def test_authorization_runs_before_task_list_cache_access(
    task_client: TestClient, task_api_context: TaskApiContext
) -> None:
    cache = RecordingTaskListCache()
    task_client.app.state.task_list_cache = cache

    missing_auth_response = task_client.get(
        f"/api/v1/projects/{task_api_context.project_id}/tasks"
    )
    non_member_response = task_client.get(
        f"/api/v1/projects/{task_api_context.project_id}/tasks",
        headers=bearer_headers(task_api_context.non_member_id),
    )

    assert missing_auth_response.status_code == 401
    assert non_member_response.status_code == 404
    assert cache.version_calls == []
    assert cache.get_calls == []
    assert cache.set_calls == []


def test_inactive_user_is_rejected_before_task_list_cache_access(
    task_client: TestClient,
    test_database_url: str,
    task_api_context: TaskApiContext,
) -> None:
    cache = RecordingTaskListCache()
    task_client.app.state.task_list_cache = cache
    asyncio.run(set_user_active(test_database_url, task_api_context.owner_id, False))

    response = task_client.get(
        f"/api/v1/projects/{task_api_context.project_id}/tasks",
        headers=bearer_headers(task_api_context.owner_id),
    )

    assert response.status_code == 403
    assert cache.version_calls == []
    assert cache.get_calls == []
    assert cache.set_calls == []


def test_task_list_cache_miss_writes_then_hit_reuses_cached_response(
    task_client: TestClient,
    test_database_url: str,
    task_api_context: TaskApiContext,
) -> None:
    cache = RecordingTaskListCache()
    task_client.app.state.task_list_cache = cache
    asyncio.run(
        insert_task(
            test_database_url,
            project_id=task_api_context.project_id,
            title="First task",
            actor_id=task_api_context.owner_id,
            created_at=datetime.now(UTC),
        )
    )

    first_response = task_client.get(
        f"/api/v1/projects/{task_api_context.project_id}/tasks",
        headers=bearer_headers(task_api_context.owner_id),
    )
    asyncio.run(
        insert_task(
            test_database_url,
            project_id=task_api_context.project_id,
            title="Second task",
            actor_id=task_api_context.owner_id,
            created_at=datetime.now(UTC),
        )
    )
    second_response = task_client.get(
        f"/api/v1/projects/{task_api_context.project_id}/tasks",
        headers=bearer_headers(task_api_context.owner_id),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json()["total"] == 1
    assert second_response.json() == first_response.json()
    assert cache.version_calls == [
        task_api_context.project_id,
        task_api_context.project_id,
    ]
    assert len(cache.get_calls) == 2
    assert len(cache.set_calls) == 1


def test_task_list_uses_postgresql_when_cache_version_is_unavailable(
    task_client: TestClient,
    test_database_url: str,
    task_api_context: TaskApiContext,
) -> None:
    cache = RecordingTaskListCache(version=None)
    task_client.app.state.task_list_cache = cache
    asyncio.run(
        insert_task(
            test_database_url,
            project_id=task_api_context.project_id,
            title="Database fallback task",
            actor_id=task_api_context.owner_id,
            created_at=datetime.now(UTC),
        )
    )

    response = task_client.get(
        f"/api/v1/projects/{task_api_context.project_id}/tasks",
        headers=bearer_headers(task_api_context.owner_id),
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert cache.version_calls == [task_api_context.project_id]
    assert cache.get_calls == []
    assert cache.set_calls == []


def test_task_list_cache_key_is_project_filter_page_and_version_aware(
    task_client: TestClient,
    test_database_url: str,
    task_api_context: TaskApiContext,
) -> None:
    cache = RecordingTaskListCache()
    task_client.app.state.task_list_cache = cache
    asyncio.run(
        insert_task(
            test_database_url,
            project_id=task_api_context.project_id,
            title="Todo task",
            actor_id=task_api_context.owner_id,
            created_at=datetime.now(UTC),
            status=TaskStatus.TODO,
            priority=TaskPriority.HIGH,
            assignee_id=task_api_context.assignee_id,
        )
    )

    first_response = task_client.get(
        (
            f"/api/v1/projects/{task_api_context.project_id}/tasks"
            f"?status={TaskStatus.TODO.value}"
            f"&priority={TaskPriority.HIGH.value}"
            f"&assignee_id={task_api_context.assignee_id}"
            "&page=1&limit=1"
        ),
        headers=bearer_headers(task_api_context.owner_id),
    )
    second_response = task_client.get(
        (
            f"/api/v1/projects/{task_api_context.other_project_id}/tasks"
            f"?status={TaskStatus.TODO.value}"
            f"&priority={TaskPriority.HIGH.value}"
            f"&assignee_id={task_api_context.assignee_id}"
            "&page=1&limit=1"
        ),
        headers=bearer_headers(task_api_context.non_member_id),
    )
    cache.version = "1"
    third_response = task_client.get(
        (
            f"/api/v1/projects/{task_api_context.project_id}/tasks"
            f"?status={TaskStatus.TODO.value}"
            f"&priority={TaskPriority.HIGH.value}"
            f"&assignee_id={task_api_context.assignee_id}"
            "&page=2&limit=1"
        ),
        headers=bearer_headers(task_api_context.owner_id),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert third_response.status_code == 200
    assert len(set(cache.get_calls)) == 3
    assert cache.get_calls[0] == (
        task_api_context.project_id,
        "0",
        TaskStatus.TODO,
        TaskPriority.HIGH,
        task_api_context.assignee_id,
        1,
        1,
    )
    assert cache.get_calls[1][0] == task_api_context.other_project_id
    assert cache.get_calls[2][1] == "1"
    assert cache.get_calls[2][5] == 2


def test_task_mutations_invalidate_project_task_list_after_commit(
    task_client: TestClient, task_api_context: TaskApiContext
) -> None:
    cache = RecordingTaskListCache()
    task_client.app.state.task_list_cache = cache

    create_response = task_client.post(
        f"/api/v1/projects/{task_api_context.project_id}/tasks",
        headers=bearer_headers(task_api_context.owner_id),
        json={"title": "Created task"},
    )
    task_id = create_response.json()["id"]
    update_response = task_client.patch(
        f"/api/v1/tasks/{task_id}",
        headers=bearer_headers(task_api_context.owner_id),
        json={
            "title": "Updated task",
            "description": "Updated description",
            "status": TaskStatus.IN_PROGRESS.value,
            "priority": TaskPriority.HIGH.value,
            "assignee_id": str(task_api_context.assignee_id),
            "due_date": "2025-01-31T00:00:00Z",
        },
    )
    delete_response = task_client.delete(
        f"/api/v1/tasks/{task_id}",
        headers=bearer_headers(task_api_context.owner_id),
    )

    assert create_response.status_code == 201
    assert update_response.status_code == 200
    assert delete_response.status_code == 204
    assert cache.invalidate_calls == [
        task_api_context.project_id,
        task_api_context.project_id,
        task_api_context.project_id,
    ]


def test_successful_mutation_uses_next_task_list_cache_version(
    task_client: TestClient,
    test_database_url: str,
    task_api_context: TaskApiContext,
) -> None:
    cache = RecordingTaskListCache()
    task_client.app.state.task_list_cache = cache
    asyncio.run(
        insert_task(
            test_database_url,
            project_id=task_api_context.project_id,
            title="Existing task",
            actor_id=task_api_context.owner_id,
            created_at=datetime.now(UTC),
        )
    )

    first_response = task_client.get(
        f"/api/v1/projects/{task_api_context.project_id}/tasks",
        headers=bearer_headers(task_api_context.owner_id),
    )
    create_response = task_client.post(
        f"/api/v1/projects/{task_api_context.project_id}/tasks",
        headers=bearer_headers(task_api_context.owner_id),
        json={"title": "New task"},
    )
    second_response = task_client.get(
        f"/api/v1/projects/{task_api_context.project_id}/tasks",
        headers=bearer_headers(task_api_context.owner_id),
    )

    assert first_response.status_code == 200
    assert create_response.status_code == 201
    assert second_response.status_code == 200
    assert first_response.json()["total"] == 1
    assert second_response.json()["total"] == 2
    assert cache.get_calls[0][1] == "0"
    assert cache.get_calls[1][1] == "1"
    assert len(cache.set_calls) == 2


def test_failed_task_create_does_not_invalidate_task_list_cache(
    monkeypatch: pytest.MonkeyPatch,
    task_client: TestClient,
    test_database_url: str,
    task_api_context: TaskApiContext,
) -> None:
    cache = RecordingTaskListCache()
    task_client.app.state.task_list_cache = cache
    original_create = TaskRepository.create

    async def delete_project_before_create(self: TaskRepository, task: Any) -> Any:
        await delete_project(test_database_url, task.project_id)
        return await original_create(self, task)

    monkeypatch.setattr(TaskRepository, "create", delete_project_before_create)

    with pytest.raises(IntegrityError):
        task_client.post(
            f"/api/v1/projects/{task_api_context.project_id}/tasks",
            headers=bearer_headers(task_api_context.owner_id),
            json={"title": "Transaction failure"},
        )

    assert cache.invalidate_calls == []


def test_label_and_comment_writes_do_not_invalidate_task_list_cache(
    task_client: TestClient, task_api_context: TaskApiContext
) -> None:
    cache = RecordingTaskListCache()
    task_client.app.state.task_list_cache = cache
    create_response = task_client.post(
        f"/api/v1/projects/{task_api_context.project_id}/tasks",
        headers=bearer_headers(task_api_context.owner_id),
        json={"title": "Task with related data"},
    )
    assert create_response.status_code == 201
    task_id = create_response.json()["id"]
    cache.invalidate_calls.clear()

    label_response = task_client.post(
        f"/api/v1/projects/{task_api_context.project_id}/labels",
        headers=bearer_headers(task_api_context.owner_id),
        json={"name": "Bug", "color": "#EF4444"},
    )
    assert label_response.status_code == 201
    label_id = label_response.json()["id"]
    attach_label_response = task_client.post(
        f"/api/v1/tasks/{task_id}/labels/{label_id}",
        headers=bearer_headers(task_api_context.owner_id),
    )
    assert attach_label_response.status_code == 201
    comment_response = task_client.post(
        f"/api/v1/tasks/{task_id}/comments",
        headers=bearer_headers(task_api_context.owner_id),
        json={"content": "Comment does not alter task list payload."},
    )
    assert comment_response.status_code == 201
    comment_id = comment_response.json()["id"]
    delete_comment_response = task_client.delete(
        f"/api/v1/comments/{comment_id}",
        headers=bearer_headers(task_api_context.owner_id),
    )
    assert delete_comment_response.status_code == 204

    assert cache.invalidate_calls == []


def test_task_list_cache_serializes_with_ttl_and_validates_payloads() -> None:
    project_id = uuid4()
    response = build_task_list_response(project_id)
    redis_client = FakeRedisClient()
    cache = TaskListCache(redis_client, ttl_seconds=60)
    version = asyncio.run(cache.get_project_version(project_id))

    asyncio.run(
        cache.set_task_list(
            project_id=project_id,
            version=version,
            status=TaskStatus.TODO,
            priority=TaskPriority.MEDIUM,
            assignee_id=None,
            page=1,
            limit=20,
            response=response,
        )
    )
    cached_response = asyncio.run(
        cache.get_task_list(
            project_id=project_id,
            version=version,
            status=TaskStatus.TODO,
            priority=TaskPriority.MEDIUM,
            assignee_id=None,
            page=1,
            limit=20,
        )
    )
    data_key = cache.build_data_key(
        project_id=project_id,
        version=version,
        status=TaskStatus.TODO,
        priority=TaskPriority.MEDIUM,
        assignee_id=None,
        page=1,
        limit=20,
    )

    assert version == "0"
    assert redis_client.expirations[data_key] == 60
    assert cached_response == response
    assert json.loads(redis_client.values[data_key]) == response.model_dump(mode="json")


def test_task_list_cache_returns_none_for_redis_and_payload_failures() -> None:
    project_id = uuid4()
    response = build_task_list_response(project_id)
    redis_client = FakeRedisClient()
    cache = TaskListCache(redis_client, ttl_seconds=60)

    redis_client.fail_get = True
    assert asyncio.run(cache.get_project_version(project_id)) is None
    assert (
        asyncio.run(
            cache.get_task_list(
                project_id=project_id,
                version="0",
                status=None,
                priority=None,
                assignee_id=None,
                page=1,
                limit=20,
            )
        )
        is None
    )

    redis_client.fail_get = False
    data_key = cache.build_data_key(
        project_id=project_id,
        version="0",
        status=None,
        priority=None,
        assignee_id=None,
        page=1,
        limit=20,
    )
    redis_client.values[data_key] = "not-json"
    assert (
        asyncio.run(
            cache.get_task_list(
                project_id=project_id,
                version="0",
                status=None,
                priority=None,
                assignee_id=None,
                page=1,
                limit=20,
            )
        )
        is None
    )

    redis_client.fail_set = True
    asyncio.run(
        cache.set_task_list(
            project_id=project_id,
            version="0",
            status=None,
            priority=None,
            assignee_id=None,
            page=1,
            limit=20,
            response=response,
        )
    )

    redis_client.fail_incr = True
    asyncio.run(cache.invalidate_project(project_id))


@pytest.mark.asyncio
async def test_real_redis_task_list_cache_round_trip_when_configured() -> None:
    redis_url = os.getenv("TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("TEST_REDIS_URL is not set")

    project_id = uuid4()
    response = build_task_list_response(project_id)
    namespace = f"taskhub-test:{uuid4().hex}"
    redis_client = redis.from_url(redis_url, decode_responses=True)
    cache = TaskListCache(redis_client, ttl_seconds=60, namespace=namespace)
    version_key = cache.build_version_key(project_id)
    data_key = cache.build_data_key(
        project_id=project_id,
        version="0",
        status=None,
        priority=None,
        assignee_id=None,
        page=1,
        limit=20,
    )

    try:
        assert await cache.get_project_version(project_id) == "0"
        await cache.set_task_list(
            project_id=project_id,
            version="0",
            status=None,
            priority=None,
            assignee_id=None,
            page=1,
            limit=20,
            response=response,
        )

        cached_response = await cache.get_task_list(
            project_id=project_id,
            version="0",
            status=None,
            priority=None,
            assignee_id=None,
            page=1,
            limit=20,
        )
        ttl_seconds = await redis_client.ttl(data_key)

        assert cached_response == response
        assert 0 < ttl_seconds <= 60

        await cache.invalidate_project(project_id)

        assert await cache.get_project_version(project_id) == "1"
    finally:
        await redis_client.delete(data_key, version_key)
        await redis_client.aclose()
