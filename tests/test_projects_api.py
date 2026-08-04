import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import create_app
from app.models.enums import (
    ProjectStatus,
    TaskPriority,
    TaskStatus,
    UserRole,
)
from app.models.label import Label
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from tests.test_auth_api import (
    assert_bearer_401,
    login_user,
    register_user,
    set_user_active,
)

PROJECT_FIELDS = {
    "id",
    "workspace_id",
    "name",
    "description",
    "status",
    "created_by",
    "created_at",
    "updated_at",
}


@dataclass(frozen=True)
class ProjectApiContext:
    owner: dict[str, object]
    editor: dict[str, object]
    viewer: dict[str, object]
    outsider: dict[str, object]
    admin: dict[str, object]
    workspace_id: UUID
    owner_headers: dict[str, str]
    editor_headers: dict[str, str]
    viewer_headers: dict[str, str]
    outsider_headers: dict[str, str]
    admin_headers: dict[str, str]


@dataclass(frozen=True)
class ProjectSnapshot:
    id: UUID
    workspace_id: UUID
    name: str
    description: str | None
    status: ProjectStatus
    created_by: UUID


def auth_headers(
    client: TestClient,
    *,
    email: str,
    password: str = "ValidPass123!",
) -> dict[str, str]:
    tokens = login_user(client, email=email, password=password)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def create_workspace(
    client: TestClient,
    headers: dict[str, str],
    *,
    name: str = "Project Workspace",
) -> dict[str, object]:
    response = client.post(
        "/api/v1/workspaces",
        headers=headers,
        json={"name": name},
    )
    assert response.status_code == 201
    return response.json()


def add_member(
    client: TestClient,
    headers: dict[str, str],
    workspace_id: UUID,
    *,
    email: str,
    role: str = "EDITOR",
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=headers,
        json={"email": email, "role": role},
    )
    assert response.status_code == 201
    return response.json()


def create_project(
    client: TestClient,
    headers: dict[str, str],
    workspace_id: UUID,
    *,
    name: str = "Project Alpha",
    description: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"name": name}
    if description is not None:
        payload["description"] = description

    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/projects",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 201
    return response.json()


async def set_user_role(
    database_url: str,
    user_id: UUID,
    role: UserRole,
) -> None:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            await session.execute(
                update(User).where(User.id == user_id).values(role=role)
            )
            await session.commit()
    finally:
        await engine.dispose()


def project_ids(response: object) -> list[str]:
    assert isinstance(response, list)
    return [str(item["id"]) for item in response]


def register_project_context(
    client: TestClient,
    database_url: str,
) -> ProjectApiContext:
    owner = register_user(client, email="owner@example.com", full_name="Owner User")
    editor = register_user(client, email="editor@example.com", full_name="Editor User")
    viewer = register_user(client, email="viewer@example.com", full_name="Viewer User")
    outsider = register_user(
        client,
        email="outsider@example.com",
        full_name="Outsider User",
    )
    admin = register_user(client, email="admin@example.com", full_name="Admin User")
    asyncio.run(set_user_role(database_url, UUID(str(admin["id"])), UserRole.ADMIN))

    owner_headers = auth_headers(client, email="owner@example.com")
    workspace = create_workspace(client, owner_headers)
    workspace_id = UUID(str(workspace["id"]))
    add_member(client, owner_headers, workspace_id, email=str(editor["email"]))
    add_member(
        client,
        owner_headers,
        workspace_id,
        email=str(viewer["email"]),
        role="VIEWER",
    )

    return ProjectApiContext(
        owner=owner,
        editor=editor,
        viewer=viewer,
        outsider=outsider,
        admin=admin,
        workspace_id=workspace_id,
        owner_headers=owner_headers,
        editor_headers=auth_headers(client, email="editor@example.com"),
        viewer_headers=auth_headers(client, email="viewer@example.com"),
        outsider_headers=auth_headers(client, email="outsider@example.com"),
        admin_headers=auth_headers(client, email="admin@example.com"),
    )


async def insert_project(
    database_url: str,
    *,
    workspace_id: UUID,
    created_by: UUID,
    name: str,
    description: str | None = None,
    status: ProjectStatus = ProjectStatus.ACTIVE,
    created_at: datetime | None = None,
    project_id: UUID | None = None,
) -> UUID:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            project = Project(
                workspace_id=workspace_id,
                created_by=created_by,
                name=name,
                description=description,
                status=status,
            )
            if project_id is not None:
                project.id = project_id
            if created_at is not None:
                project.created_at = created_at
                project.updated_at = created_at
            session.add(project)
            await session.commit()
            return project.id
    finally:
        await engine.dispose()


async def get_project(
    database_url: str,
    project_id: UUID,
) -> ProjectSnapshot | None:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            project = await session.get(Project, project_id)
            if project is None:
                return None
            return ProjectSnapshot(
                id=project.id,
                workspace_id=project.workspace_id,
                name=project.name,
                description=project.description,
                status=project.status,
                created_by=project.created_by,
            )
    finally:
        await engine.dispose()


async def count_project_rows(database_url: str, project_id: UUID) -> int:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(Project)
                .where(Project.id == project_id)
            )
            return int(count or 0)
    finally:
        await engine.dispose()


async def insert_task(
    database_url: str,
    *,
    project_id: UUID,
    created_by: UUID,
    title: str = "Referenced Task",
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
                created_by=created_by,
            )
            session.add(task)
            await session.commit()
            return task.id
    finally:
        await engine.dispose()


async def insert_label(
    database_url: str,
    *,
    project_id: UUID,
    name: str = "bug",
) -> UUID:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            label = Label(project_id=project_id, name=name, color="#3366FF")
            session.add(label)
            await session.commit()
            return label.id
    finally:
        await engine.dispose()


async def count_child_rows(
    database_url: str,
    *,
    project_id: UUID,
    model: type[Task] | type[Label],
) -> int:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.project_id == project_id)
            )
            return int(count or 0)
    finally:
        await engine.dispose()


def test_project_routes_require_auth_and_active_current_user(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    active_user = register_user(task_client, email="active-current@example.com")
    active_headers = auth_headers(task_client, email="active-current@example.com")
    workspace = create_workspace(task_client, active_headers, name="Auth Workspace")
    workspace_id = UUID(str(workspace["id"]))

    missing_response = task_client.get(f"/api/v1/workspaces/{workspace_id}/projects")
    invalid_response = task_client.post(
        f"/api/v1/workspaces/{workspace_id}/projects",
        headers={"Authorization": "Bearer not-a-jwt"},
        json={"name": "Invalid Auth Project"},
    )
    inactive_headers = auth_headers(task_client, email="active-current@example.com")
    asyncio.run(set_user_active(test_database_url, UUID(str(active_user["id"])), False))
    inactive_response = task_client.get(
        f"/api/v1/workspaces/{workspace_id}/projects",
        headers=inactive_headers,
    )

    assert_bearer_401(missing_response, "Could not validate credentials")
    assert_bearer_401(invalid_response, "Could not validate credentials")
    assert inactive_response.status_code == 403
    assert inactive_response.json() == {"detail": "Inactive user"}


def test_create_project_permissions_created_by_and_persistence(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    context = register_project_context(task_client, test_database_url)

    owner_body = create_project(
        task_client,
        context.owner_headers,
        context.workspace_id,
        name="  Owner Project  ",
        description="Owner created",
    )
    editor_body = create_project(
        task_client,
        context.editor_headers,
        context.workspace_id,
        name="Editor Project",
    )
    admin_body = create_project(
        task_client,
        context.admin_headers,
        context.workspace_id,
        name="Admin Project",
    )
    viewer_response = task_client.post(
        f"/api/v1/workspaces/{context.workspace_id}/projects",
        headers=context.viewer_headers,
        json={"name": "Viewer Attempt"},
    )
    outsider_response = task_client.post(
        f"/api/v1/workspaces/{context.workspace_id}/projects",
        headers=context.outsider_headers,
        json={"name": "Outsider Attempt"},
    )

    assert set(owner_body) == PROJECT_FIELDS
    assert owner_body["name"] == "Owner Project"
    assert owner_body["description"] == "Owner created"
    assert owner_body["status"] == "ACTIVE"
    assert owner_body["workspace_id"] == str(context.workspace_id)
    assert owner_body["created_by"] == context.owner["id"]
    assert editor_body["created_by"] == context.editor["id"]
    assert admin_body["created_by"] == context.admin["id"]
    assert viewer_response.status_code == 403
    assert viewer_response.json() == {"detail": "Not enough project permissions"}
    assert outsider_response.status_code == 404
    assert outsider_response.json() == {"detail": "Workspace not found"}

    persisted = asyncio.run(get_project(test_database_url, UUID(str(owner_body["id"]))))
    assert persisted == ProjectSnapshot(
        id=UUID(str(owner_body["id"])),
        workspace_id=context.workspace_id,
        name="Owner Project",
        description="Owner created",
        status=ProjectStatus.ACTIVE,
        created_by=UUID(str(context.owner["id"])),
    )


def test_create_project_rejects_invalid_read_only_and_extra_fields(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    context = register_project_context(task_client, test_database_url)
    invalid_payloads: list[dict[str, object]] = [
        {"name": None},
        {"name": ""},
        {"name": "   "},
        {"name": "A" * 256},
        {"name": "Valid", "description": "A" * 1001},
        {"name": "Valid", "id": str(uuid4())},
        {"name": "Valid", "workspace_id": str(context.workspace_id)},
        {"name": "Valid", "status": "ARCHIVED"},
        {"name": "Valid", "created_by": context.owner["id"]},
        {"name": "Valid", "created_at": "2026-08-04T00:00:00Z"},
        {"name": "Valid", "updated_at": "2026-08-04T00:00:00Z"},
        {"name": "Valid", "unknown": "value"},
    ]

    for payload in invalid_payloads:
        response = task_client.post(
            f"/api/v1/workspaces/{context.workspace_id}/projects",
            headers=context.owner_headers,
            json=payload,
        )
        assert response.status_code == 422


def test_project_list_visibility_ordering_and_includes_archived(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    context = register_project_context(task_client, test_database_url)
    older_created_at = datetime(2026, 8, 1, 8, 0, tzinfo=UTC)
    newer_created_at = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    equal_created_at = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    low_project_id = UUID("00000000-0000-4000-8000-000000000001")
    high_project_id = UUID("00000000-0000-4000-8000-000000000002")
    asyncio.run(
        insert_project(
            test_database_url,
            workspace_id=context.workspace_id,
            created_by=UUID(str(context.owner["id"])),
            name="Older project",
            created_at=older_created_at,
        )
    )
    asyncio.run(
        insert_project(
            test_database_url,
            workspace_id=context.workspace_id,
            created_by=UUID(str(context.owner["id"])),
            name="Newer archived project",
            status=ProjectStatus.ARCHIVED,
            created_at=newer_created_at,
        )
    )
    asyncio.run(
        insert_project(
            test_database_url,
            workspace_id=context.workspace_id,
            created_by=UUID(str(context.owner["id"])),
            name="Same timestamp lower id",
            created_at=equal_created_at,
            project_id=low_project_id,
        )
    )
    asyncio.run(
        insert_project(
            test_database_url,
            workspace_id=context.workspace_id,
            created_by=UUID(str(context.owner["id"])),
            name="Same timestamp higher id",
            created_at=equal_created_at,
            project_id=high_project_id,
        )
    )

    visible_headers = [
        context.admin_headers,
        context.owner_headers,
        context.editor_headers,
        context.viewer_headers,
    ]
    for headers in visible_headers:
        response = task_client.get(
            f"/api/v1/workspaces/{context.workspace_id}/projects",
            headers=headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert [project["name"] for project in body] == [
            "Same timestamp higher id",
            "Same timestamp lower id",
            "Newer archived project",
            "Older project",
        ]
        assert {project["status"] for project in body} == {"ACTIVE", "ARCHIVED"}

    outsider_response = task_client.get(
        f"/api/v1/workspaces/{context.workspace_id}/projects",
        headers=context.outsider_headers,
    )
    assert outsider_response.status_code == 404
    assert outsider_response.json() == {"detail": "Workspace not found"}


def test_read_project_visibility_for_admin_and_workspace_roles(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    context = register_project_context(task_client, test_database_url)
    project = create_project(task_client, context.owner_headers, context.workspace_id)
    project_id = UUID(str(project["id"]))

    for headers in [
        context.admin_headers,
        context.owner_headers,
        context.editor_headers,
        context.viewer_headers,
    ]:
        response = task_client.get(f"/api/v1/projects/{project_id}", headers=headers)
        assert response.status_code == 200
        assert response.json()["id"] == str(project_id)

    outsider_response = task_client.get(
        f"/api/v1/projects/{project_id}",
        headers=context.outsider_headers,
    )
    missing_response = task_client.get(
        f"/api/v1/projects/{uuid4()}",
        headers=context.owner_headers,
    )

    assert outsider_response.status_code == 404
    assert outsider_response.json() == {"detail": "Project not found"}
    assert missing_response.status_code == 404
    assert missing_response.json() == {"detail": "Project not found"}


def test_update_project_permissions_empty_patch_and_archived_metadata(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    context = register_project_context(task_client, test_database_url)
    project = create_project(
        task_client,
        context.owner_headers,
        context.workspace_id,
        description="Initial description",
    )
    project_id = UUID(str(project["id"]))

    editor_update = task_client.patch(
        f"/api/v1/projects/{project_id}",
        headers=context.editor_headers,
        json={"name": "Editor Updated", "description": None},
    )
    viewer_update = task_client.patch(
        f"/api/v1/projects/{project_id}",
        headers=context.viewer_headers,
        json={"name": "Viewer Attempt"},
    )
    outsider_update = task_client.patch(
        f"/api/v1/projects/{project_id}",
        headers=context.outsider_headers,
        json={"name": "Outsider Attempt"},
    )
    missing_empty = task_client.patch(
        f"/api/v1/projects/{uuid4()}",
        headers=context.owner_headers,
        json={},
    )
    non_member_empty = task_client.patch(
        f"/api/v1/projects/{project_id}",
        headers=context.outsider_headers,
        json={},
    )
    viewer_empty = task_client.patch(
        f"/api/v1/projects/{project_id}",
        headers=context.viewer_headers,
        json={},
    )
    owner_empty = task_client.patch(
        f"/api/v1/projects/{project_id}",
        headers=context.owner_headers,
        json={},
    )
    admin_empty = task_client.patch(
        f"/api/v1/projects/{project_id}",
        headers=context.admin_headers,
        json={},
    )

    assert editor_update.status_code == 200
    assert editor_update.json()["name"] == "Editor Updated"
    assert editor_update.json()["description"] is None
    assert viewer_update.status_code == 403
    assert viewer_update.json() == {"detail": "Not enough project permissions"}
    assert outsider_update.status_code == 404
    assert outsider_update.json() == {"detail": "Project not found"}
    assert missing_empty.status_code == 404
    assert missing_empty.json() == {"detail": "Project not found"}
    assert non_member_empty.status_code == 404
    assert non_member_empty.json() == {"detail": "Project not found"}
    assert viewer_empty.status_code == 403
    assert viewer_empty.json() == {"detail": "Not enough project permissions"}
    assert owner_empty.status_code == 400
    assert owner_empty.json() == {"detail": "No project changes provided"}
    assert admin_empty.status_code == 400
    assert admin_empty.json() == {"detail": "No project changes provided"}

    invalid_payloads: list[dict[str, object]] = [
        {"name": None},
        {"name": ""},
        {"name": "   "},
        {"name": "A" * 256},
        {"description": "A" * 1001},
        {"workspace_id": str(context.workspace_id)},
        {"status": "ARCHIVED"},
        {"created_by": context.owner["id"]},
        {"created_at": "2026-08-04T00:00:00Z"},
        {"updated_at": "2026-08-04T00:00:00Z"},
        {"unknown": "value"},
    ]
    for payload in invalid_payloads:
        response = task_client.patch(
            f"/api/v1/projects/{project_id}",
            headers=context.owner_headers,
            json=payload,
        )
        assert response.status_code == 422

    archive_response = task_client.patch(
        f"/api/v1/projects/{project_id}/archive",
        headers=context.owner_headers,
    )
    archived_update = task_client.patch(
        f"/api/v1/projects/{project_id}",
        headers=context.editor_headers,
        json={"name": "Archived Project", "description": "Still editable"},
    )
    persisted = asyncio.run(get_project(test_database_url, project_id))

    assert archive_response.status_code == 200
    assert archived_update.status_code == 200
    assert archived_update.json()["status"] == "ARCHIVED"
    assert archived_update.json()["name"] == "Archived Project"
    assert archived_update.json()["description"] == "Still editable"
    assert persisted == ProjectSnapshot(
        id=project_id,
        workspace_id=context.workspace_id,
        name="Archived Project",
        description="Still editable",
        status=ProjectStatus.ARCHIVED,
        created_by=UUID(str(context.owner["id"])),
    )


def test_archive_project_permissions_idempotency_and_child_preservation(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    context = register_project_context(task_client, test_database_url)
    project = create_project(task_client, context.owner_headers, context.workspace_id)
    project_id = UUID(str(project["id"]))
    asyncio.run(
        insert_task(
            test_database_url,
            project_id=project_id,
            created_by=UUID(str(context.owner["id"])),
        )
    )
    asyncio.run(insert_label(test_database_url, project_id=project_id))

    viewer_response = task_client.patch(
        f"/api/v1/projects/{project_id}/archive",
        headers=context.viewer_headers,
    )
    outsider_response = task_client.patch(
        f"/api/v1/projects/{project_id}/archive",
        headers=context.outsider_headers,
    )
    editor_response = task_client.patch(
        f"/api/v1/projects/{project_id}/archive",
        headers=context.editor_headers,
    )
    repeat_response = task_client.patch(
        f"/api/v1/projects/{project_id}/archive",
        headers=context.editor_headers,
    )
    persisted = asyncio.run(get_project(test_database_url, project_id))

    assert viewer_response.status_code == 403
    assert viewer_response.json() == {"detail": "Not enough project permissions"}
    assert outsider_response.status_code == 404
    assert outsider_response.json() == {"detail": "Project not found"}
    assert editor_response.status_code == 200
    assert editor_response.json()["status"] == "ARCHIVED"
    assert repeat_response.status_code == 200
    assert repeat_response.json()["status"] == "ARCHIVED"
    assert persisted is not None
    assert persisted.status is ProjectStatus.ARCHIVED
    assert (
        asyncio.run(
            count_child_rows(test_database_url, project_id=project_id, model=Task)
        )
        == 1
    )
    assert (
        asyncio.run(
            count_child_rows(test_database_url, project_id=project_id, model=Label)
        )
        == 1
    )


def test_delete_project_permissions_lifecycle_and_child_conflicts(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    context = register_project_context(task_client, test_database_url)
    active_project = create_project(
        task_client,
        context.owner_headers,
        context.workspace_id,
        name="Active Delete Conflict",
    )
    active_project_id = UUID(str(active_project["id"]))
    active_response = task_client.delete(
        f"/api/v1/projects/{active_project_id}",
        headers=context.owner_headers,
    )

    empty_project = create_project(
        task_client,
        context.owner_headers,
        context.workspace_id,
        name="Empty Archived Delete",
    )
    empty_project_id = UUID(str(empty_project["id"]))
    archive_empty = task_client.patch(
        f"/api/v1/projects/{empty_project_id}/archive",
        headers=context.owner_headers,
    )
    delete_empty = task_client.delete(
        f"/api/v1/projects/{empty_project_id}",
        headers=context.owner_headers,
    )

    protected_project = create_project(
        task_client,
        context.owner_headers,
        context.workspace_id,
        name="Protected Delete",
    )
    protected_project_id = UUID(str(protected_project["id"]))
    task_client.patch(
        f"/api/v1/projects/{protected_project_id}/archive",
        headers=context.owner_headers,
    )
    editor_response = task_client.delete(
        f"/api/v1/projects/{protected_project_id}",
        headers=context.editor_headers,
    )
    viewer_response = task_client.delete(
        f"/api/v1/projects/{protected_project_id}",
        headers=context.viewer_headers,
    )
    outsider_response = task_client.delete(
        f"/api/v1/projects/{protected_project_id}",
        headers=context.outsider_headers,
    )

    task_project = create_project(
        task_client,
        context.owner_headers,
        context.workspace_id,
        name="Task Conflict",
    )
    task_project_id = UUID(str(task_project["id"]))
    task_client.patch(
        f"/api/v1/projects/{task_project_id}/archive",
        headers=context.owner_headers,
    )
    asyncio.run(
        insert_task(
            test_database_url,
            project_id=task_project_id,
            created_by=UUID(str(context.owner["id"])),
        )
    )
    task_conflict = task_client.delete(
        f"/api/v1/projects/{task_project_id}",
        headers=context.owner_headers,
    )

    label_project = create_project(
        task_client,
        context.owner_headers,
        context.workspace_id,
        name="Label Conflict",
    )
    label_project_id = UUID(str(label_project["id"]))
    task_client.patch(
        f"/api/v1/projects/{label_project_id}/archive",
        headers=context.owner_headers,
    )
    asyncio.run(insert_label(test_database_url, project_id=label_project_id))
    label_conflict = task_client.delete(
        f"/api/v1/projects/{label_project_id}",
        headers=context.admin_headers,
    )

    assert active_response.status_code == 409
    assert active_response.json() == {
        "detail": "Project must be archived before deletion"
    }
    assert archive_empty.status_code == 200
    assert delete_empty.status_code == 204
    assert delete_empty.content == b""
    assert asyncio.run(count_project_rows(test_database_url, empty_project_id)) == 0
    assert editor_response.status_code == 403
    assert editor_response.json() == {"detail": "Not enough project permissions"}
    assert viewer_response.status_code == 403
    assert viewer_response.json() == {"detail": "Not enough project permissions"}
    assert outsider_response.status_code == 404
    assert outsider_response.json() == {"detail": "Project not found"}
    assert task_conflict.status_code == 409
    assert task_conflict.json() == {"detail": "Project contains tasks or labels"}
    assert label_conflict.status_code == 409
    assert label_conflict.json() == {"detail": "Project contains tasks or labels"}
    assert asyncio.run(count_project_rows(test_database_url, task_project_id)) == 1
    assert asyncio.run(count_project_rows(test_database_url, label_project_id)) == 1


def test_project_persists_across_independent_requests_and_app_instances(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    context = register_project_context(task_client, test_database_url)
    created = create_project(
        task_client,
        context.owner_headers,
        context.workspace_id,
        name="Persistent Project",
    )
    project_id = UUID(str(created["id"]))

    same_client_response = task_client.get(
        f"/api/v1/projects/{project_id}",
        headers=context.owner_headers,
    )
    list_response = task_client.get(
        f"/api/v1/workspaces/{context.workspace_id}/projects",
        headers=context.owner_headers,
    )
    with TestClient(create_app()) as second_client:
        fresh_app_response = second_client.get(
            f"/api/v1/projects/{project_id}",
            headers=context.owner_headers,
        )

    assert same_client_response.status_code == 200
    assert fresh_app_response.status_code == 200
    assert same_client_response.json()["id"] == str(project_id)
    assert fresh_app_response.json()["id"] == str(project_id)
    assert str(project_id) in project_ids(list_response.json())
