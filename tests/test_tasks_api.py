import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

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


@dataclass(frozen=True)
class TaskApiContext:
    owner_id: UUID
    assignee_id: UUID
    non_member_id: UUID
    project_id: UUID
    other_project_id: UUID


def actor_headers(actor_id: UUID) -> dict[str, str]:
    return {"X-Actor-ID": str(actor_id)}


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
) -> UUID:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            task = Task(
                project_id=project_id,
                assignee_id=None,
                title=title,
                description=None,
                status=TaskStatus.TODO,
                priority=TaskPriority.MEDIUM,
                due_date=None,
                created_by=actor_id,
                created_at=created_at,
                updated_at=created_at,
            )
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
        headers=actor_headers(context.owner_id),
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
        headers=actor_headers(task_context.owner_id),
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


def test_project_scoped_list_is_isolated_and_deterministically_ordered(
    task_client: TestClient,
    task_context: TaskApiContext,
    test_database_url: str,
) -> None:
    first_created_at = datetime(2026, 8, 1, 8, 0, tzinfo=UTC)
    second_created_at = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
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
            project_id=task_context.other_project_id,
            actor_id=task_context.owner_id,
            title="Other project task",
            created_at=datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
        )
    )

    response = task_client.get(f"/api/v1/projects/{task_context.project_id}/tasks")

    assert response.status_code == 200
    assert [task["title"] for task in response.json()] == ["Newer task", "Older task"]


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
        headers=actor_headers(task_context.owner_id),
        json={"title": "Missing project"},
    )
    list_response = task_client.get(f"/api/v1/projects/{missing_project_id}/tasks")

    assert create_response.status_code == 404
    assert list_response.status_code == 404


def test_create_requires_valid_actor_header(
    task_client: TestClient,
    task_context: TaskApiContext,
) -> None:
    absent_response = task_client.post(
        f"/api/v1/projects/{task_context.project_id}/tasks",
        json={"title": "No actor"},
    )
    malformed_response = task_client.post(
        f"/api/v1/projects/{task_context.project_id}/tasks",
        headers={"X-Actor-ID": "not-a-uuid"},
        json={"title": "Bad actor"},
    )
    unknown_response = task_client.post(
        f"/api/v1/projects/{task_context.project_id}/tasks",
        headers=actor_headers(uuid4()),
        json={"title": "Unknown actor"},
    )

    assert absent_response.status_code == 422
    assert malformed_response.status_code == 422
    assert unknown_response.status_code == 404


def test_create_rejects_unknown_assignee_without_persisting_task(
    task_client: TestClient,
    task_context: TaskApiContext,
    test_database_url: str,
) -> None:
    response = task_client.post(
        f"/api/v1/projects/{task_context.project_id}/tasks",
        headers=actor_headers(task_context.owner_id),
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
        headers=actor_headers(task_context.owner_id),
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
        headers=actor_headers(task_context.owner_id),
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
        headers=actor_headers(task_context.owner_id),
        json={"title": "   "},
    )
    stripped_response = task_client.post(
        f"/api/v1/projects/{task_context.project_id}/tasks",
        headers=actor_headers(task_context.owner_id),
        json={"title": "  Trimmed title  "},
    )
    null_title_response = task_client.patch(
        f"/api/v1/tasks/{uuid4()}",
        json={"title": None},
    )
    create_unknown_response = task_client.post(
        f"/api/v1/projects/{task_context.project_id}/tasks",
        headers=actor_headers(task_context.owner_id),
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
        headers=actor_headers(task_context.owner_id),
        json={"title": "Old route"},
    )
    get_response = task_client.get("/api/v1/tasks")

    assert post_response.status_code == 404
    assert get_response.status_code == 404


def test_invalid_task_id_format_returns_422(task_client: TestClient) -> None:
    response = task_client.get("/api/v1/tasks/not-a-uuid")

    assert response.status_code == 422
