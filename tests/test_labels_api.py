import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.enums import UserRole
from app.models.label import Label
from app.models.task_label import TaskLabel
from app.models.user import User
from tests.test_auth_api import (
    assert_bearer_401,
    login_user,
    register_user,
    set_user_active,
)

LABEL_FIELDS = {"id", "project_id", "name", "color", "created_at"}


@dataclass(frozen=True)
class LabelApiContext:
    owner: dict[str, object]
    editor: dict[str, object]
    viewer: dict[str, object]
    outsider: dict[str, object]
    admin: dict[str, object]
    workspace_id: UUID
    project_id: UUID
    task_id: UUID
    other_workspace_id: UUID
    other_project_id: UUID
    other_task_id: UUID
    owner_headers: dict[str, str]
    editor_headers: dict[str, str]
    viewer_headers: dict[str, str]
    outsider_headers: dict[str, str]
    admin_headers: dict[str, str]


@dataclass(frozen=True)
class LabelSnapshot:
    id: UUID
    project_id: UUID
    name: str
    color: str


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
    name: str,
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
    role: str,
) -> None:
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=headers,
        json={"email": email, "role": role},
    )
    assert response.status_code == 201


def create_project(
    client: TestClient,
    headers: dict[str, str],
    workspace_id: UUID,
    *,
    name: str,
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/projects",
        headers=headers,
        json={"name": name},
    )
    assert response.status_code == 201
    return response.json()


def create_task(
    client: TestClient,
    headers: dict[str, str],
    project_id: UUID,
    *,
    title: str,
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/projects/{project_id}/tasks",
        headers=headers,
        json={"title": title},
    )
    assert response.status_code == 201
    return response.json()


def create_label(
    client: TestClient,
    headers: dict[str, str],
    project_id: UUID,
    *,
    name: str = "bug",
    color: str = "#3366FF",
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/projects/{project_id}/labels",
        headers=headers,
        json={"name": name, "color": color},
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


async def get_label(database_url: str, label_id: UUID) -> LabelSnapshot | None:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            label = await session.get(Label, label_id)
            if label is None:
                return None
            return LabelSnapshot(
                id=label.id,
                project_id=label.project_id,
                name=label.name,
                color=label.color,
            )
    finally:
        await engine.dispose()


async def count_labels(
    database_url: str,
    *,
    project_id: UUID | None = None,
    name: str | None = None,
) -> int:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            statement = select(func.count()).select_from(Label)
            if project_id is not None:
                statement = statement.where(Label.project_id == project_id)
            if name is not None:
                statement = statement.where(Label.name == name)
            count = await session.scalar(statement)
            return int(count or 0)
    finally:
        await engine.dispose()


async def count_task_labels(
    database_url: str,
    *,
    task_id: UUID | None = None,
    label_id: UUID | None = None,
) -> int:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            statement = select(func.count()).select_from(TaskLabel)
            if task_id is not None:
                statement = statement.where(TaskLabel.task_id == task_id)
            if label_id is not None:
                statement = statement.where(TaskLabel.label_id == label_id)
            count = await session.scalar(statement)
            return int(count or 0)
    finally:
        await engine.dispose()


def label_ids(response: object) -> list[str]:
    assert isinstance(response, list)
    return [str(item["id"]) for item in response]


def register_label_context(
    client: TestClient,
    database_url: str,
) -> LabelApiContext:
    owner = register_user(client, email="label-owner@example.com")
    editor = register_user(client, email="label-editor@example.com")
    viewer = register_user(client, email="label-viewer@example.com")
    outsider = register_user(client, email="label-outsider@example.com")
    admin = register_user(client, email="label-admin@example.com")
    asyncio.run(set_user_role(database_url, UUID(str(admin["id"])), UserRole.ADMIN))

    owner_headers = auth_headers(client, email="label-owner@example.com")
    editor_headers = auth_headers(client, email="label-editor@example.com")
    viewer_headers = auth_headers(client, email="label-viewer@example.com")
    outsider_headers = auth_headers(client, email="label-outsider@example.com")
    admin_headers = auth_headers(client, email="label-admin@example.com")

    workspace = create_workspace(
        client,
        owner_headers,
        name="Label Workspace",
    )
    workspace_id = UUID(str(workspace["id"]))
    add_member(
        client,
        owner_headers,
        workspace_id,
        email=str(editor["email"]),
        role="EDITOR",
    )
    add_member(
        client,
        owner_headers,
        workspace_id,
        email=str(viewer["email"]),
        role="VIEWER",
    )
    project = create_project(
        client,
        owner_headers,
        workspace_id,
        name="Label Project",
    )
    project_id = UUID(str(project["id"]))
    task = create_task(
        client,
        owner_headers,
        project_id,
        title="Label Task",
    )

    other_workspace = create_workspace(
        client,
        outsider_headers,
        name="Other Label Workspace",
    )
    other_workspace_id = UUID(str(other_workspace["id"]))
    other_project = create_project(
        client,
        outsider_headers,
        other_workspace_id,
        name="Other Label Project",
    )
    other_project_id = UUID(str(other_project["id"]))
    other_task = create_task(
        client,
        outsider_headers,
        other_project_id,
        title="Other Label Task",
    )

    return LabelApiContext(
        owner=owner,
        editor=editor,
        viewer=viewer,
        outsider=outsider,
        admin=admin,
        workspace_id=workspace_id,
        project_id=project_id,
        task_id=UUID(str(task["id"])),
        other_workspace_id=other_workspace_id,
        other_project_id=other_project_id,
        other_task_id=UUID(str(other_task["id"])),
        owner_headers=owner_headers,
        editor_headers=editor_headers,
        viewer_headers=viewer_headers,
        outsider_headers=outsider_headers,
        admin_headers=admin_headers,
    )


def test_label_routes_require_auth_and_active_current_user(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    context = register_label_context(task_client, test_database_url)
    inactive_headers = auth_headers(task_client, email="label-owner@example.com")
    asyncio.run(
        set_user_active(test_database_url, UUID(str(context.owner["id"])), False)
    )

    missing_response = task_client.get(f"/api/v1/projects/{context.project_id}/labels")
    invalid_response = task_client.post(
        f"/api/v1/projects/{context.project_id}/labels",
        headers={"Authorization": "Bearer not-a-jwt"},
        json={"name": "invalid-auth", "color": "#3366FF"},
    )
    inactive_response = task_client.get(
        f"/api/v1/projects/{context.project_id}/labels",
        headers=inactive_headers,
    )

    assert_bearer_401(missing_response, "Could not validate credentials")
    assert_bearer_401(invalid_response, "Could not validate credentials")
    assert inactive_response.status_code == 403
    assert inactive_response.json() == {"detail": "Inactive user"}


def test_create_list_read_update_and_delete_label_permissions(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    context = register_label_context(task_client, test_database_url)

    owner_label = create_label(
        task_client,
        context.owner_headers,
        context.project_id,
        name="  Owner Label  ",
        color="#1122AA",
    )
    editor_label = create_label(
        task_client,
        context.editor_headers,
        context.project_id,
        name="Editor Label",
        color="#3344BB",
    )
    admin_label = create_label(
        task_client,
        context.admin_headers,
        context.project_id,
        name="Admin Label",
        color="#5566CC",
    )
    viewer_create = task_client.post(
        f"/api/v1/projects/{context.project_id}/labels",
        headers=context.viewer_headers,
        json={"name": "Viewer Label", "color": "#7788DD"},
    )
    outsider_create = task_client.post(
        f"/api/v1/projects/{context.project_id}/labels",
        headers=context.outsider_headers,
        json={"name": "Outsider Label", "color": "#99AAEE"},
    )

    assert set(owner_label) == LABEL_FIELDS
    assert owner_label["name"] == "Owner Label"
    assert owner_label["color"] == "#1122AA"
    assert owner_label["project_id"] == str(context.project_id)
    assert set(editor_label) == LABEL_FIELDS
    assert set(admin_label) == LABEL_FIELDS
    assert viewer_create.status_code == 403
    assert viewer_create.json() == {"detail": "Not enough label permissions"}
    assert outsider_create.status_code == 404
    assert outsider_create.json() == {"detail": "Project not found"}

    visible_headers = [
        context.admin_headers,
        context.owner_headers,
        context.editor_headers,
        context.viewer_headers,
    ]
    for headers in visible_headers:
        list_response = task_client.get(
            f"/api/v1/projects/{context.project_id}/labels",
            headers=headers,
        )
        read_response = task_client.get(
            f"/api/v1/labels/{owner_label['id']}",
            headers=headers,
        )
        assert list_response.status_code == 200
        assert owner_label["id"] in label_ids(list_response.json())
        assert read_response.status_code == 200
        assert read_response.json()["id"] == owner_label["id"]

    outsider_list = task_client.get(
        f"/api/v1/projects/{context.project_id}/labels",
        headers=context.outsider_headers,
    )
    outsider_read = task_client.get(
        f"/api/v1/labels/{owner_label['id']}",
        headers=context.outsider_headers,
    )
    editor_update = task_client.patch(
        f"/api/v1/labels/{owner_label['id']}",
        headers=context.editor_headers,
        json={"name": "Editor Updated Label", "color": "#AABBCC"},
    )
    viewer_update = task_client.patch(
        f"/api/v1/labels/{owner_label['id']}",
        headers=context.viewer_headers,
        json={"name": "Viewer Attempt"},
    )
    outsider_update = task_client.patch(
        f"/api/v1/labels/{owner_label['id']}",
        headers=context.outsider_headers,
        json={"name": "Outsider Attempt"},
    )
    viewer_delete = task_client.delete(
        f"/api/v1/labels/{owner_label['id']}",
        headers=context.viewer_headers,
    )
    owner_delete = task_client.delete(
        f"/api/v1/labels/{owner_label['id']}",
        headers=context.owner_headers,
    )
    missing_after_delete = task_client.get(
        f"/api/v1/labels/{owner_label['id']}",
        headers=context.owner_headers,
    )

    assert outsider_list.status_code == 404
    assert outsider_list.json() == {"detail": "Project not found"}
    assert outsider_read.status_code == 404
    assert outsider_read.json() == {"detail": "Label not found"}
    assert editor_update.status_code == 200
    assert editor_update.json()["name"] == "Editor Updated Label"
    assert editor_update.json()["color"] == "#AABBCC"
    assert viewer_update.status_code == 403
    assert viewer_update.json() == {"detail": "Not enough label permissions"}
    assert outsider_update.status_code == 404
    assert outsider_update.json() == {"detail": "Label not found"}
    assert viewer_delete.status_code == 403
    assert viewer_delete.json() == {"detail": "Not enough label permissions"}
    assert owner_delete.status_code == 204
    assert owner_delete.content == b""
    assert missing_after_delete.status_code == 404
    assert (
        asyncio.run(get_label(test_database_url, UUID(str(owner_label["id"])))) is None
    )


def test_label_empty_patch_checks_authorization_first(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    context = register_label_context(task_client, test_database_url)
    label = create_label(task_client, context.owner_headers, context.project_id)

    missing = task_client.patch(
        f"/api/v1/labels/{uuid4()}",
        headers=context.owner_headers,
        json={},
    )
    outsider = task_client.patch(
        f"/api/v1/labels/{label['id']}",
        headers=context.outsider_headers,
        json={},
    )
    viewer = task_client.patch(
        f"/api/v1/labels/{label['id']}",
        headers=context.viewer_headers,
        json={},
    )
    owner = task_client.patch(
        f"/api/v1/labels/{label['id']}",
        headers=context.owner_headers,
        json={},
    )
    admin = task_client.patch(
        f"/api/v1/labels/{label['id']}",
        headers=context.admin_headers,
        json={},
    )

    assert missing.status_code == 404
    assert missing.json() == {"detail": "Label not found"}
    assert outsider.status_code == 404
    assert outsider.json() == {"detail": "Label not found"}
    assert viewer.status_code == 403
    assert viewer.json() == {"detail": "Not enough label permissions"}
    assert owner.status_code == 400
    assert owner.json() == {"detail": "No label changes provided"}
    assert admin.status_code == 400
    assert admin.json() == {"detail": "No label changes provided"}


def test_label_validation_unknown_and_read_only_fields(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    context = register_label_context(task_client, test_database_url)
    label = create_label(task_client, context.owner_headers, context.project_id)
    invalid_create_payloads: list[dict[str, object]] = [
        {"name": None, "color": "#3366FF"},
        {"name": "", "color": "#3366FF"},
        {"name": "   ", "color": "#3366FF"},
        {"name": "Valid", "color": None},
        {"name": "Valid", "color": "3366FF"},
        {"name": "Valid", "color": "#3366ff"},
        {"name": "Valid", "color": "#3366F"},
        {"name": "Valid", "color": "#3366FFF"},
        {"name": "Valid", "color": "#GG66FF"},
        {"name": "Valid", "color": "#3366FF", "id": str(uuid4())},
        {"name": "Valid", "color": "#3366FF", "project_id": str(context.project_id)},
        {
            "name": "Valid",
            "color": "#3366FF",
            "created_at": datetime.now(UTC).isoformat(),
        },
        {"name": "Valid", "color": "#3366FF", "unknown": "value"},
    ]

    for payload in invalid_create_payloads:
        response = task_client.post(
            f"/api/v1/projects/{context.project_id}/labels",
            headers=context.owner_headers,
            json=payload,
        )
        assert response.status_code == 422

    invalid_update_payloads: list[dict[str, object]] = [
        {"name": None},
        {"name": ""},
        {"name": "   "},
        {"color": None},
        {"color": "3366FF"},
        {"color": "#3366ff"},
        {"color": "#3366F"},
        {"color": "#3366FFF"},
        {"color": "#GG66FF"},
        {"id": label["id"]},
        {"project_id": str(context.project_id)},
        {"created_at": datetime.now(UTC).isoformat()},
        {"unknown": "value"},
    ]
    for payload in invalid_update_payloads:
        response = task_client.patch(
            f"/api/v1/labels/{label['id']}",
            headers=context.owner_headers,
            json=payload,
        )
        assert response.status_code == 422

    persisted = asyncio.run(get_label(test_database_url, UUID(str(label["id"]))))
    assert persisted == LabelSnapshot(
        id=UUID(str(label["id"])),
        project_id=context.project_id,
        name="bug",
        color="#3366FF",
    )


def test_label_duplicate_create_update_and_case_sensitive_uniqueness(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    context = register_label_context(task_client, test_database_url)
    first = create_label(
        task_client,
        context.owner_headers,
        context.project_id,
        name="Bug",
    )
    same_name_other_case = create_label(
        task_client,
        context.owner_headers,
        context.project_id,
        name="bug",
    )
    same_name_other_project = create_label(
        task_client,
        context.outsider_headers,
        context.other_project_id,
        name="Bug",
    )
    duplicate_create = task_client.post(
        f"/api/v1/projects/{context.project_id}/labels",
        headers=context.editor_headers,
        json={"name": "Bug", "color": "#1122AA"},
    )
    target = create_label(
        task_client,
        context.owner_headers,
        context.project_id,
        name="Feature",
    )
    duplicate_update = task_client.patch(
        f"/api/v1/labels/{target['id']}",
        headers=context.owner_headers,
        json={"name": "Bug"},
    )
    same_name_update = task_client.patch(
        f"/api/v1/labels/{first['id']}",
        headers=context.owner_headers,
        json={"name": "Bug"},
    )

    assert set(same_name_other_case) == LABEL_FIELDS
    assert set(same_name_other_project) == LABEL_FIELDS
    assert duplicate_create.status_code == 409
    assert duplicate_create.json() == {"detail": "Label name already exists"}
    assert duplicate_update.status_code == 409
    assert duplicate_update.json() == {"detail": "Label name already exists"}
    assert same_name_update.status_code == 200
    assert same_name_update.json()["name"] == "Bug"
    assert (
        asyncio.run(
            count_labels(test_database_url, project_id=context.project_id, name="Bug")
        )
        == 1
    )
    assert asyncio.run(count_labels(test_database_url, name="Bug")) == 2


def test_attach_and_detach_label_contracts(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    context = register_label_context(task_client, test_database_url)
    label = create_label(
        task_client,
        context.owner_headers,
        context.project_id,
        name="ready",
        color="#00AACC",
    )
    label_id = UUID(str(label["id"]))

    viewer_attach = task_client.post(
        f"/api/v1/tasks/{context.task_id}/labels/{label_id}",
        headers=context.viewer_headers,
    )
    outsider_attach = task_client.post(
        f"/api/v1/tasks/{context.task_id}/labels/{label_id}",
        headers=context.outsider_headers,
    )
    attach = task_client.post(
        f"/api/v1/tasks/{context.task_id}/labels/{label_id}",
        headers=context.editor_headers,
    )
    duplicate_attach = task_client.post(
        f"/api/v1/tasks/{context.task_id}/labels/{label_id}",
        headers=context.owner_headers,
    )
    viewer_detach = task_client.delete(
        f"/api/v1/tasks/{context.task_id}/labels/{label_id}",
        headers=context.viewer_headers,
    )
    detach = task_client.delete(
        f"/api/v1/tasks/{context.task_id}/labels/{label_id}",
        headers=context.owner_headers,
    )
    missing_association = task_client.delete(
        f"/api/v1/tasks/{context.task_id}/labels/{label_id}",
        headers=context.owner_headers,
    )

    assert viewer_attach.status_code == 403
    assert viewer_attach.json() == {"detail": "Not enough label permissions"}
    assert outsider_attach.status_code == 404
    assert outsider_attach.json() == {"detail": "Task not found"}
    assert attach.status_code == 201
    assert attach.json() == label
    assert duplicate_attach.status_code == 409
    assert duplicate_attach.json() == {"detail": "Task label already exists"}
    assert viewer_detach.status_code == 403
    assert viewer_detach.json() == {"detail": "Not enough label permissions"}
    assert detach.status_code == 204
    assert detach.content == b""
    assert missing_association.status_code == 404
    assert missing_association.json() == {"detail": "Task label not found"}
    assert (
        asyncio.run(count_task_labels(test_database_url, task_id=context.task_id)) == 0
    )


def test_attach_detach_missing_hidden_and_cross_project_resources(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    context = register_label_context(task_client, test_database_url)
    label = create_label(task_client, context.owner_headers, context.project_id)
    other_label = create_label(
        task_client,
        context.outsider_headers,
        context.other_project_id,
        name="other",
    )

    missing_task = task_client.post(
        f"/api/v1/tasks/{uuid4()}/labels/{label['id']}",
        headers=context.owner_headers,
    )
    missing_label = task_client.post(
        f"/api/v1/tasks/{context.task_id}/labels/{uuid4()}",
        headers=context.owner_headers,
    )
    cross_project_label = task_client.post(
        f"/api/v1/tasks/{context.task_id}/labels/{other_label['id']}",
        headers=context.owner_headers,
    )
    hidden_task = task_client.post(
        f"/api/v1/tasks/{context.other_task_id}/labels/{other_label['id']}",
        headers=context.owner_headers,
    )
    hidden_label_read = task_client.get(
        f"/api/v1/labels/{other_label['id']}",
        headers=context.owner_headers,
    )
    hidden_project_list = task_client.get(
        f"/api/v1/projects/{context.other_project_id}/labels",
        headers=context.owner_headers,
    )
    admin_cross_project = task_client.post(
        f"/api/v1/tasks/{context.task_id}/labels/{other_label['id']}",
        headers=context.admin_headers,
    )

    assert missing_task.status_code == 404
    assert missing_task.json() == {"detail": "Task not found"}
    assert missing_label.status_code == 404
    assert missing_label.json() == {"detail": "Label not found"}
    assert cross_project_label.status_code == 404
    assert cross_project_label.json() == {"detail": "Label not found"}
    assert hidden_task.status_code == 404
    assert hidden_task.json() == {"detail": "Task not found"}
    assert hidden_label_read.status_code == 404
    assert hidden_label_read.json() == {"detail": "Label not found"}
    assert hidden_project_list.status_code == 404
    assert hidden_project_list.json() == {"detail": "Project not found"}
    assert admin_cross_project.status_code == 404
    assert admin_cross_project.json() == {"detail": "Label not found"}


def test_project_safe_delete_still_rejects_projects_with_labels(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    context = register_label_context(task_client, test_database_url)
    project = create_project(
        task_client,
        context.owner_headers,
        context.workspace_id,
        name="Label Only Delete Conflict",
    )
    project_id = UUID(str(project["id"]))
    create_label(task_client, context.owner_headers, project_id)

    archive_response = task_client.patch(
        f"/api/v1/projects/{project_id}/archive",
        headers=context.owner_headers,
    )
    delete_response = task_client.delete(
        f"/api/v1/projects/{project_id}",
        headers=context.owner_headers,
    )

    assert archive_response.status_code == 200
    assert delete_response.status_code == 409
    assert delete_response.json() == {"detail": "Project contains tasks or labels"}
    assert asyncio.run(count_labels(test_database_url, project_id=project_id)) == 1
