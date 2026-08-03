import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.security import create_access_token
from app.main import create_app
from app.models.enums import (
    ProjectStatus,
    TaskPriority,
    TaskStatus,
    UserRole,
    WorkspaceMemberRole,
)
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember

TASK_READ_FIELDS = {
    "id",
    "project_id",
    "assignee_id",
    "title",
    "description",
    "status",
    "priority",
    "due_date",
    "created_by",
    "created_at",
    "updated_at",
}
TASK_LIST_FIELDS = {"items", "page", "limit", "total", "total_pages"}
TEST_JWT_SECRET_KEY = "test-secret-key-with-at-least-32-characters"


@dataclass(frozen=True)
class TaskApiContext:
    owner_id: UUID
    assignee_id: UUID
    non_member_id: UUID
    project_id: UUID
    other_project_id: UUID


def bearer_headers(user_id: UUID) -> dict[str, str]:
    access_token, _ = create_access_token(
        user_id=user_id,
        secret_key=TEST_JWT_SECRET_KEY,
        algorithm="HS256",
        now=datetime.now(UTC) - timedelta(seconds=1),
    )
    return {"Authorization": f"Bearer {access_token}"}


def parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def seed_task_context(database_url: str) -> TaskApiContext:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    seed_id = uuid4().hex

    try:
        async with session_factory() as session:
            owner = User(
                email=f"owner-{seed_id}@example.com",
                full_name="Workspace Owner",
                hashed_password="hashed-password",
                role=UserRole.MEMBER,
            )
            assignee = User(
                email=f"assignee-{seed_id}@example.com",
                full_name="Workspace Assignee",
                hashed_password="hashed-password",
                role=UserRole.MEMBER,
            )
            non_member = User(
                email=f"non-member-{seed_id}@example.com",
                full_name="Other User",
                hashed_password="hashed-password",
                role=UserRole.MEMBER,
            )
            session.add_all([owner, assignee, non_member])
            await session.flush()

            workspace = Workspace(name="Product Workspace", owner_id=owner.id)
            other_workspace = Workspace(name="Other Workspace", owner_id=non_member.id)
            session.add_all([workspace, other_workspace])
            await session.flush()

            session.add_all(
                [
                    WorkspaceMember(
                        workspace_id=workspace.id,
                        user_id=owner.id,
                        role=WorkspaceMemberRole.OWNER,
                    ),
                    WorkspaceMember(
                        workspace_id=workspace.id,
                        user_id=assignee.id,
                        role=WorkspaceMemberRole.EDITOR,
                    ),
                    WorkspaceMember(
                        workspace_id=other_workspace.id,
                        user_id=non_member.id,
                        role=WorkspaceMemberRole.OWNER,
                    ),
                ]
            )

            project = Project(
                workspace_id=workspace.id,
                name="Task API",
                description=None,
                status=ProjectStatus.ACTIVE,
                created_by=owner.id,
            )
            other_project = Project(
                workspace_id=other_workspace.id,
                name="Other Project",
                description=None,
                status=ProjectStatus.ACTIVE,
                created_by=non_member.id,
            )
            session.add_all([project, other_project])
            await session.commit()

            return TaskApiContext(
                owner_id=owner.id,
                assignee_id=assignee.id,
                non_member_id=non_member.id,
                project_id=project.id,
                other_project_id=other_project.id,
            )
    finally:
        await engine.dispose()


async def count_tasks(database_url: str) -> int:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            count = await session.scalar(select(func.count()).select_from(Task))
            return int(count or 0)
    finally:
        await engine.dispose()


async def insert_task(
    database_url: str,
    *,
    project_id: UUID,
    actor_id: UUID,
    title: str,
    created_at: datetime,
    task_id: UUID | None = None,
    assignee_id: UUID | None = None,
    status: TaskStatus = TaskStatus.TODO,
    priority: TaskPriority = TaskPriority.MEDIUM,
) -> UUID:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            task = Task(
                project_id=project_id,
                assignee_id=assignee_id,
                title=title,
                description=None,
                status=status,
                priority=priority,
                due_date=None,
                created_by=actor_id,
                created_at=created_at,
                updated_at=created_at,
            )
            if task_id is not None:
                task.id = task_id
            session.add(task)
            await session.commit()
            return task.id
    finally:
        await engine.dispose()


@pytest.fixture
def task_context(
    test_database_url: str,
    clean_test_database: None,
) -> TaskApiContext:
    return asyncio.run(seed_task_context(test_database_url))


def create_task(
    task_client: TestClient,
    context: TaskApiContext,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    response = task_client.post(
        f"/api/v1/projects/{context.project_id}/tasks",
        headers=bearer_headers(context.owner_id),
        json=payload or {"title": "Persisted task"},
    )
    assert response.status_code == 201
    return response.json()


def test_project_scoped_create_returns_all_scalar_task_fields(
    task_client: TestClient,
    task_context: TaskApiContext,
) -> None:
    due_date = "2026-08-01T16:30:00+07:00"
    expected_utc_due_date = datetime(2026, 8, 1, 9, 30, tzinfo=UTC)

    response = task_client.post(
        f"/api/v1/projects/{task_context.project_id}/tasks",
        headers={
            **bearer_headers(task_context.owner_id),
            "X-Actor-ID": str(task_context.non_member_id),
        },
        json={
            "title": "  Build persisted tasks  ",
            "description": "Store tasks in PostgreSQL",
            "assignee_id": str(task_context.assignee_id),
            "status": "IN_PROGRESS",
            "priority": "HIGH",
            "due_date": due_date,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == TASK_READ_FIELDS
    assert UUID(body["id"]).version == 4
    assert UUID(body["project_id"]) == task_context.project_id
    assert UUID(body["assignee_id"]) == task_context.assignee_id
    assert body["title"] == "Build persisted tasks"
    assert body["description"] == "Store tasks in PostgreSQL"
    assert body["status"] == "IN_PROGRESS"
    assert body["priority"] == "HIGH"
    assert parse_datetime(body["due_date"]) == expected_utc_due_date
    assert UUID(body["created_by"]) == task_context.owner_id
    assert parse_datetime(body["created_at"]).tzinfo is not None
    assert parse_datetime(body["updated_at"]).tzinfo is not None


def test_create_defaults_status_priority_and_nullable_assignee(
    task_client: TestClient,
    task_context: TaskApiContext,
) -> None:
    body = create_task(
        task_client,
        task_context,
        {"title": "Use defaults", "assignee_id": None},
    )

    assert body["status"] == "TODO"
    assert body["priority"] == "MEDIUM"
    assert body["assignee_id"] is None
    assert body["due_date"] is None


def test_project_scoped_list_defaults_metadata_isolation_and_ordering(
    task_client: TestClient,
    task_context: TaskApiContext,
    test_database_url: str,
) -> None:
    first_created_at = datetime(2026, 8, 1, 8, 0, tzinfo=UTC)
    second_created_at = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    equal_created_at = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    low_task_id = UUID("00000000-0000-4000-8000-000000000001")
    high_task_id = UUID("00000000-0000-4000-8000-000000000002")
    asyncio.run(
        insert_task(
            test_database_url,
            project_id=task_context.project_id,
            actor_id=task_context.owner_id,
            title="Older task",
            created_at=first_created_at,
        )
    )
    asyncio.run(
        insert_task(
            test_database_url,
            project_id=task_context.project_id,
            actor_id=task_context.owner_id,
            title="Newer task",
            created_at=second_created_at,
        )
    )
    asyncio.run(
        insert_task(
            test_database_url,
            project_id=task_context.project_id,
            actor_id=task_context.owner_id,
            title="Same timestamp lower id",
            created_at=equal_created_at,
            task_id=low_task_id,
        )
    )
    asyncio.run(
        insert_task(
            test_database_url,
            project_id=task_context.project_id,
            actor_id=task_context.owner_id,
            title="Same timestamp higher id",
            created_at=equal_created_at,
            task_id=high_task_id,
        )
    )
    asyncio.run(
        insert_task(
            test_database_url,
            project_id=task_context.other_project_id,
            actor_id=task_context.owner_id,
            title="Other project task",
            created_at=datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
        )
    )

    response = task_client.get(f"/api/v1/projects/{task_context.project_id}/tasks")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == TASK_LIST_FIELDS
    assert body["page"] == 1
    assert body["limit"] == 20
    assert body["total"] == 4
    assert body["total_pages"] == 1
    assert [task["title"] for task in body["items"]] == [
        "Same timestamp higher id",
        "Same timestamp lower id",
        "Newer task",
        "Older task",
    ]


def test_list_filters_by_status_priority_assignee_and_combines_with_and(
    task_client: TestClient,
    task_context: TaskApiContext,
    test_database_url: str,
) -> None:
    created_at = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    seed_tasks = [
        ("Matching task", TaskStatus.DONE, TaskPriority.HIGH, task_context.assignee_id),
        ("Wrong status", TaskStatus.TODO, TaskPriority.HIGH, task_context.assignee_id),
        ("Wrong priority", TaskStatus.DONE, TaskPriority.LOW, task_context.assignee_id),
        ("Wrong assignee", TaskStatus.DONE, TaskPriority.HIGH, task_context.owner_id),
    ]
    for title, task_status, priority, assignee_id in seed_tasks:
        asyncio.run(
            insert_task(
                test_database_url,
                project_id=task_context.project_id,
                actor_id=task_context.owner_id,
                title=title,
                created_at=created_at,
                status=task_status,
                priority=priority,
                assignee_id=assignee_id,
            )
        )

    status_response = task_client.get(
        f"/api/v1/projects/{task_context.project_id}/tasks?status=DONE"
    )
    priority_response = task_client.get(
        f"/api/v1/projects/{task_context.project_id}/tasks?priority=HIGH"
    )
    assignee_response = task_client.get(
        f"/api/v1/projects/{task_context.project_id}/tasks"
        f"?assignee_id={task_context.assignee_id}"
    )
    combined_response = task_client.get(
        f"/api/v1/projects/{task_context.project_id}/tasks"
        f"?status=DONE&priority=HIGH&assignee_id={task_context.assignee_id}"
    )

    assert status_response.status_code == 200
    assert {task["title"] for task in status_response.json()["items"]} == {
        "Matching task",
        "Wrong priority",
        "Wrong assignee",
    }
    assert priority_response.status_code == 200
    assert {task["title"] for task in priority_response.json()["items"]} == {
        "Matching task",
        "Wrong status",
        "Wrong assignee",
    }
    assert assignee_response.status_code == 200
    assert {task["title"] for task in assignee_response.json()["items"]} == {
        "Matching task",
        "Wrong status",
        "Wrong priority",
    }
    assert combined_response.status_code == 200
    combined_body = combined_response.json()
    assert combined_body["total"] == 1
    assert combined_body["total_pages"] == 1
    assert [task["title"] for task in combined_body["items"]] == ["Matching task"]


def test_list_pagination_counts_before_limit_and_handles_beyond_range(
    task_client: TestClient,
    task_context: TaskApiContext,
    test_database_url: str,
) -> None:
    for index in range(3):
        asyncio.run(
            insert_task(
                test_database_url,
                project_id=task_context.project_id,
                actor_id=task_context.owner_id,
                title=f"Page task {index + 1}",
                created_at=datetime(2026, 8, 1, 10 - index, 0, tzinfo=UTC),
            )
        )

    first_page_response = task_client.get(
        f"/api/v1/projects/{task_context.project_id}/tasks?limit=1"
    )
    second_page_response = task_client.get(
        f"/api/v1/projects/{task_context.project_id}/tasks?page=2&limit=1"
    )
    beyond_range_response = task_client.get(
        f"/api/v1/projects/{task_context.project_id}/tasks?page=5&limit=1"
    )

    assert first_page_response.status_code == 200
    first_page = first_page_response.json()
    assert first_page["page"] == 1
    assert first_page["limit"] == 1
    assert first_page["total"] == 3
    assert first_page["total_pages"] == 3
    assert [task["title"] for task in first_page["items"]] == ["Page task 1"]
    assert second_page_response.status_code == 200
    second_page = second_page_response.json()
    assert second_page["page"] == 2
    assert second_page["limit"] == 1
    assert second_page["total"] == 3
    assert second_page["total_pages"] == 3
    assert [task["title"] for task in second_page["items"]] == ["Page task 2"]
    assert beyond_range_response.status_code == 200
    beyond_range = beyond_range_response.json()
    assert beyond_range["page"] == 5
    assert beyond_range["limit"] == 1
    assert beyond_range["total"] == 3
    assert beyond_range["total_pages"] == 3
    assert beyond_range["items"] == []


def test_list_empty_filtered_result_and_limit_100_boundary(
    task_client: TestClient,
    task_context: TaskApiContext,
) -> None:
    response = task_client.get(
        f"/api/v1/projects/{task_context.project_id}/tasks"
        f"?assignee_id={uuid4()}&limit=100"
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "items": [],
        "page": 1,
        "limit": 100,
        "total": 0,
        "total_pages": 0,
    }


@pytest.mark.parametrize(
    "query_string",
    [
        "page=0",
        "limit=0",
        "limit=101",
        "status=NOT_A_STATUS",
        "status=",
        "priority=NOT_A_PRIORITY",
        "priority=",
        "assignee_id=not-a-uuid",
        "assignee_id=",
    ],
)
def test_list_rejects_invalid_query_values(
    task_client: TestClient,
    task_context: TaskApiContext,
    query_string: str,
) -> None:
    response = task_client.get(
        f"/api/v1/projects/{task_context.project_id}/tasks?{query_string}"
    )

    assert response.status_code == 422


def test_task_persists_across_requests_and_fresh_app_instances(
    task_client: TestClient,
    task_context: TaskApiContext,
) -> None:
    created = create_task(task_client, task_context)
    same_app_response = task_client.get(f"/api/v1/tasks/{created['id']}")

    with TestClient(create_app()) as second_client:
        fresh_app_response = second_client.get(f"/api/v1/tasks/{created['id']}")

    assert same_app_response.status_code == 200
    assert same_app_response.json()["id"] == created["id"]
    assert fresh_app_response.status_code == 200
    assert fresh_app_response.json()["id"] == created["id"]


def test_create_and_list_return_404_for_missing_project(
    task_client: TestClient,
    task_context: TaskApiContext,
) -> None:
    missing_project_id = uuid4()

    create_response = task_client.post(
        f"/api/v1/projects/{missing_project_id}/tasks",
        headers=bearer_headers(task_context.owner_id),
        json={"title": "Missing project"},
    )
    list_response = task_client.get(f"/api/v1/projects/{missing_project_id}/tasks")

    assert create_response.status_code == 404
    assert list_response.status_code == 404


def test_create_requires_valid_access_token(
    task_client: TestClient,
    task_context: TaskApiContext,
) -> None:
    absent_response = task_client.post(
        f"/api/v1/projects/{task_context.project_id}/tasks",
        json={"title": "No actor"},
    )
    malformed_response = task_client.post(
        f"/api/v1/projects/{task_context.project_id}/tasks",
        headers={"Authorization": "Bearer not-a-jwt"},
        json={"title": "Bad actor"},
    )
    unknown_access_token, _ = create_access_token(
        user_id=uuid4(),
        secret_key=TEST_JWT_SECRET_KEY,
        algorithm="HS256",
        now=datetime.now(UTC) - timedelta(seconds=1),
    )
    unknown_access_claims = jwt.decode(
        unknown_access_token,
        TEST_JWT_SECRET_KEY,
        algorithms=["HS256"],
    )
    assert unknown_access_claims["type"] == "access"
    assert datetime.fromtimestamp(int(unknown_access_claims["exp"]), UTC) > (
        datetime.now(UTC)
    )
    unknown_response = task_client.post(
        f"/api/v1/projects/{task_context.project_id}/tasks",
        headers={"Authorization": f"Bearer {unknown_access_token}"},
        json={"title": "Unknown actor"},
    )

    assert absent_response.status_code == 401
    assert absent_response.json() == {"detail": "Could not validate credentials"}
    assert absent_response.headers["WWW-Authenticate"] == "Bearer"
    assert malformed_response.status_code == 401
    assert malformed_response.json() == {"detail": "Could not validate credentials"}
    assert malformed_response.headers["WWW-Authenticate"] == "Bearer"
    assert unknown_response.status_code == 401
    assert unknown_response.json() == {"detail": "Could not validate credentials"}
    assert unknown_response.headers["WWW-Authenticate"] == "Bearer"


def test_create_rejects_unknown_assignee_without_persisting_task(
    task_client: TestClient,
    task_context: TaskApiContext,
    test_database_url: str,
) -> None:
    response = task_client.post(
        f"/api/v1/projects/{task_context.project_id}/tasks",
        headers=bearer_headers(task_context.owner_id),
        json={"title": "Unknown assignee", "assignee_id": str(uuid4())},
    )

    assert response.status_code == 404
    assert asyncio.run(count_tasks(test_database_url)) == 0


def test_create_rejects_non_member_assignee_without_persisting_task(
    task_client: TestClient,
    task_context: TaskApiContext,
    test_database_url: str,
) -> None:
    response = task_client.post(
        f"/api/v1/projects/{task_context.project_id}/tasks",
        headers=bearer_headers(task_context.owner_id),
        json={
            "title": "Non-member assignee",
            "assignee_id": str(task_context.non_member_id),
        },
    )

    assert response.status_code == 400
    assert asyncio.run(count_tasks(test_database_url)) == 0


def test_get_partial_update_clear_nullable_fields_and_delete(
    task_client: TestClient,
    task_context: TaskApiContext,
) -> None:
    due_date = datetime(2026, 8, 3, 17, 0, tzinfo=UTC)
    created = create_task(
        task_client,
        task_context,
        {
            "title": "Original title",
            "description": "Original description",
            "assignee_id": str(task_context.assignee_id),
            "due_date": due_date.isoformat(),
        },
    )

    get_response = task_client.get(f"/api/v1/tasks/{created['id']}")
    update_response = task_client.patch(
        f"/api/v1/tasks/{created['id']}",
        json={
            "title": "Updated title",
            "description": None,
            "assignee_id": None,
            "status": "DONE",
            "priority": "URGENT",
            "due_date": None,
        },
    )
    delete_response = task_client.delete(f"/api/v1/tasks/{created['id']}")
    missing_after_delete = task_client.get(f"/api/v1/tasks/{created['id']}")

    assert get_response.status_code == 200
    assert get_response.json() == created
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["title"] == "Updated title"
    assert updated["description"] is None
    assert updated["assignee_id"] is None
    assert updated["status"] == "DONE"
    assert updated["priority"] == "URGENT"
    assert updated["due_date"] is None
    assert updated["project_id"] == created["project_id"]
    assert updated["created_by"] == created["created_by"]
    assert delete_response.status_code == 204
    assert delete_response.content == b""
    assert missing_after_delete.status_code == 404


def test_due_date_requires_timezone_for_create_and_update(
    task_client: TestClient,
    task_context: TaskApiContext,
) -> None:
    create_response = task_client.post(
        f"/api/v1/projects/{task_context.project_id}/tasks",
        headers=bearer_headers(task_context.owner_id),
        json={"title": "Naive create due date", "due_date": "2026-08-01T09:30:00"},
    )
    created = create_task(task_client, task_context)
    update_response = task_client.patch(
        f"/api/v1/tasks/{created['id']}",
        json={"due_date": "2026-08-01T09:30:00"},
    )

    assert create_response.status_code == 422
    assert update_response.status_code == 422


def test_update_validates_assignee_membership(
    task_client: TestClient,
    task_context: TaskApiContext,
) -> None:
    created = create_task(task_client, task_context)

    valid_response = task_client.patch(
        f"/api/v1/tasks/{created['id']}",
        json={"assignee_id": str(task_context.assignee_id)},
    )
    non_member_response = task_client.patch(
        f"/api/v1/tasks/{created['id']}",
        json={"assignee_id": str(task_context.non_member_id)},
    )
    unknown_response = task_client.patch(
        f"/api/v1/tasks/{created['id']}",
        json={"assignee_id": str(uuid4())},
    )

    assert valid_response.status_code == 200
    assert valid_response.json()["assignee_id"] == str(task_context.assignee_id)
    assert non_member_response.status_code == 400
    assert unknown_response.status_code == 404


def test_missing_task_behavior(task_client: TestClient) -> None:
    missing_task_id = uuid4()

    get_response = task_client.get(f"/api/v1/tasks/{missing_task_id}")
    patch_response = task_client.patch(
        f"/api/v1/tasks/{missing_task_id}",
        json={"title": "No task"},
    )
    delete_response = task_client.delete(f"/api/v1/tasks/{missing_task_id}")

    assert get_response.status_code == 404
    assert patch_response.status_code == 404
    assert delete_response.status_code == 404


def test_title_validation_and_unknown_fields(
    task_client: TestClient,
    task_context: TaskApiContext,
) -> None:
    blank_response = task_client.post(
        f"/api/v1/projects/{task_context.project_id}/tasks",
        headers=bearer_headers(task_context.owner_id),
        json={"title": "   "},
    )
    stripped_response = task_client.post(
        f"/api/v1/projects/{task_context.project_id}/tasks",
        headers=bearer_headers(task_context.owner_id),
        json={"title": "  Trimmed title  "},
    )
    null_title_response = task_client.patch(
        f"/api/v1/tasks/{uuid4()}",
        json={"title": None},
    )
    create_unknown_response = task_client.post(
        f"/api/v1/projects/{task_context.project_id}/tasks",
        headers=bearer_headers(task_context.owner_id),
        json={"title": "Valid title", "project_id": str(task_context.project_id)},
    )
    patch_unknown_response = task_client.patch(
        f"/api/v1/tasks/{uuid4()}",
        json={"created_by": str(task_context.owner_id)},
    )

    assert blank_response.status_code == 422
    assert stripped_response.status_code == 201
    assert stripped_response.json()["title"] == "Trimmed title"
    assert null_title_response.status_code == 422
    assert create_unknown_response.status_code == 422
    assert patch_unknown_response.status_code == 422


def test_old_unscoped_collection_routes_are_not_retained(
    task_client: TestClient,
    task_context: TaskApiContext,
) -> None:
    post_response = task_client.post(
        "/api/v1/tasks",
        headers=bearer_headers(task_context.owner_id),
        json={"title": "Old route"},
    )
    get_response = task_client.get("/api/v1/tasks")

    assert post_response.status_code == 404
    assert get_response.status_code == 404


def test_invalid_task_id_format_returns_422(task_client: TestClient) -> None:
    response = task_client.get("/api/v1/tasks/not-a-uuid")

    assert response.status_code == 422
