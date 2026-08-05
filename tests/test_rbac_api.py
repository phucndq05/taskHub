import asyncio
from dataclasses import dataclass
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.comment import Comment
from app.models.enums import UserRole
from app.models.label import Label
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from tests.test_auth_api import login_user, register_user


@dataclass(frozen=True)
class RbacApiContext:
    owner_id: UUID
    editor_id: UUID
    viewer_id: UUID
    outsider_id: UUID
    admin_id: UUID
    workspace_id: UUID
    project_id: UUID
    task_id: UUID
    label_id: UUID
    owner_comment_id: UUID
    editor_comment_id: UUID
    owner_headers: dict[str, str]
    editor_headers: dict[str, str]
    viewer_headers: dict[str, str]
    outsider_headers: dict[str, str]
    admin_headers: dict[str, str]


def auth_headers(client: TestClient, email: str) -> dict[str, str]:
    tokens = login_user(client, email=email)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def set_user_role(database_url: str, user_id: UUID, role: UserRole) -> None:
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


async def count_rows(database_url: str, model: type[object]) -> int:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            count = await session.scalar(select(func.count()).select_from(model))
            return int(count or 0)
    finally:
        await engine.dispose()


def create_rbac_context(client: TestClient, database_url: str) -> RbacApiContext:
    seed = uuid4().hex
    owner = register_user(client, email=f"owner-{seed}@example.com")
    editor = register_user(client, email=f"editor-{seed}@example.com")
    viewer = register_user(client, email=f"viewer-{seed}@example.com")
    outsider = register_user(client, email=f"outsider-{seed}@example.com")
    admin = register_user(client, email=f"admin-{seed}@example.com")
    admin_id = UUID(str(admin["id"]))
    asyncio.run(set_user_role(database_url, admin_id, UserRole.ADMIN))

    owner_headers = auth_headers(client, str(owner["email"]))
    editor_headers = auth_headers(client, str(editor["email"]))
    viewer_headers = auth_headers(client, str(viewer["email"]))
    outsider_headers = auth_headers(client, str(outsider["email"]))
    admin_headers = auth_headers(client, str(admin["email"]))

    workspace_response = client.post(
        "/api/v1/workspaces",
        headers=owner_headers,
        json={"name": "RBAC Workspace"},
    )
    assert workspace_response.status_code == 201
    workspace_id = UUID(workspace_response.json()["id"])

    editor_member_response = client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=owner_headers,
        json={"email": editor["email"], "role": "EDITOR"},
    )
    viewer_member_response = client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=owner_headers,
        json={"email": viewer["email"], "role": "VIEWER"},
    )
    assert editor_member_response.status_code == 201
    assert viewer_member_response.status_code == 201

    project_response = client.post(
        f"/api/v1/workspaces/{workspace_id}/projects",
        headers=owner_headers,
        json={"name": "RBAC Project"},
    )
    assert project_response.status_code == 201
    project_id = UUID(project_response.json()["id"])

    task_response = client.post(
        f"/api/v1/projects/{project_id}/tasks",
        headers=owner_headers,
        json={"title": "RBAC task"},
    )
    assert task_response.status_code == 201
    task_id = UUID(task_response.json()["id"])

    label_response = client.post(
        f"/api/v1/projects/{project_id}/labels",
        headers=owner_headers,
        json={"name": "RBAC", "color": "#AABBCC"},
    )
    assert label_response.status_code == 201
    label_id = UUID(label_response.json()["id"])

    owner_comment_response = client.post(
        f"/api/v1/tasks/{task_id}/comments",
        headers=owner_headers,
        json={"content": "Owner comment"},
    )
    editor_comment_response = client.post(
        f"/api/v1/tasks/{task_id}/comments",
        headers=editor_headers,
        json={"content": "Editor comment"},
    )
    assert owner_comment_response.status_code == 201
    assert editor_comment_response.status_code == 201

    return RbacApiContext(
        owner_id=UUID(str(owner["id"])),
        editor_id=UUID(str(editor["id"])),
        viewer_id=UUID(str(viewer["id"])),
        outsider_id=UUID(str(outsider["id"])),
        admin_id=admin_id,
        workspace_id=workspace_id,
        project_id=project_id,
        task_id=task_id,
        label_id=label_id,
        owner_comment_id=UUID(owner_comment_response.json()["id"]),
        editor_comment_id=UUID(editor_comment_response.json()["id"]),
        owner_headers=owner_headers,
        editor_headers=editor_headers,
        viewer_headers=viewer_headers,
        outsider_headers=outsider_headers,
        admin_headers=admin_headers,
    )


def test_representative_cross_resource_permissions(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    context = create_rbac_context(task_client, test_database_url)

    admin_workspace_response = task_client.patch(
        f"/api/v1/workspaces/{context.workspace_id}",
        headers=context.admin_headers,
        json={"name": "Admin renamed workspace"},
    )
    owner_workspace_response = task_client.patch(
        f"/api/v1/workspaces/{context.workspace_id}",
        headers=context.owner_headers,
        json={"name": "Owner renamed workspace"},
    )
    editor_workspace_response = task_client.patch(
        f"/api/v1/workspaces/{context.workspace_id}",
        headers=context.editor_headers,
        json={"name": "Editor rename"},
    )

    assert admin_workspace_response.status_code == 200
    assert owner_workspace_response.status_code == 200
    assert editor_workspace_response.status_code == 403

    editor_project_response = task_client.post(
        f"/api/v1/workspaces/{context.workspace_id}/projects",
        headers=context.editor_headers,
        json={"name": "Editor project"},
    )
    editor_task_response = task_client.post(
        f"/api/v1/projects/{context.project_id}/tasks",
        headers=context.editor_headers,
        json={"title": "Editor task"},
    )
    editor_label_response = task_client.post(
        f"/api/v1/projects/{context.project_id}/labels",
        headers=context.editor_headers,
        json={"name": "EditorLabel", "color": "#112233"},
    )
    editor_comment_response = task_client.post(
        f"/api/v1/tasks/{context.task_id}/comments",
        headers=context.editor_headers,
        json={"content": "Editor writes comment"},
    )

    assert editor_project_response.status_code == 201
    assert editor_task_response.status_code == 201
    assert editor_label_response.status_code == 201
    assert editor_comment_response.status_code == 201

    viewer_workspace_response = task_client.get(
        f"/api/v1/workspaces/{context.workspace_id}",
        headers=context.viewer_headers,
    )
    viewer_project_response = task_client.get(
        f"/api/v1/projects/{context.project_id}",
        headers=context.viewer_headers,
    )
    viewer_task_response = task_client.get(
        f"/api/v1/tasks/{context.task_id}",
        headers=context.viewer_headers,
    )
    viewer_label_response = task_client.get(
        f"/api/v1/labels/{context.label_id}",
        headers=context.viewer_headers,
    )

    assert viewer_workspace_response.status_code == 200
    assert viewer_project_response.status_code == 200
    assert viewer_task_response.status_code == 200
    assert viewer_label_response.status_code == 200

    row_counts = {
        Project: asyncio.run(count_rows(test_database_url, Project)),
        Task: asyncio.run(count_rows(test_database_url, Task)),
        Label: asyncio.run(count_rows(test_database_url, Label)),
        Comment: asyncio.run(count_rows(test_database_url, Comment)),
    }
    viewer_project_create_response = task_client.post(
        f"/api/v1/workspaces/{context.workspace_id}/projects",
        headers=context.viewer_headers,
        json={"name": "Viewer project"},
    )
    viewer_task_create_response = task_client.post(
        f"/api/v1/projects/{context.project_id}/tasks",
        headers=context.viewer_headers,
        json={"title": "Viewer task"},
    )
    viewer_label_create_response = task_client.post(
        f"/api/v1/projects/{context.project_id}/labels",
        headers=context.viewer_headers,
        json={"name": "ViewerLabel", "color": "#445566"},
    )
    viewer_comment_create_response = task_client.post(
        f"/api/v1/tasks/{context.task_id}/comments",
        headers=context.viewer_headers,
        json={"content": "Viewer comment"},
    )

    assert viewer_project_create_response.status_code == 403
    assert viewer_task_create_response.status_code == 403
    assert viewer_label_create_response.status_code == 403
    assert viewer_comment_create_response.status_code == 403
    assert {
        Project: asyncio.run(count_rows(test_database_url, Project)),
        Task: asyncio.run(count_rows(test_database_url, Task)),
        Label: asyncio.run(count_rows(test_database_url, Label)),
        Comment: asyncio.run(count_rows(test_database_url, Comment)),
    } == row_counts

    outsider_workspace_response = task_client.get(
        f"/api/v1/workspaces/{context.workspace_id}",
        headers=context.outsider_headers,
    )
    outsider_project_response = task_client.get(
        f"/api/v1/projects/{context.project_id}",
        headers=context.outsider_headers,
    )
    outsider_task_response = task_client.get(
        f"/api/v1/tasks/{context.task_id}",
        headers=context.outsider_headers,
    )
    outsider_label_response = task_client.get(
        f"/api/v1/labels/{context.label_id}",
        headers=context.outsider_headers,
    )
    outsider_comment_delete_response = task_client.delete(
        f"/api/v1/comments/{context.owner_comment_id}",
        headers=context.outsider_headers,
    )

    assert outsider_workspace_response.status_code == 404
    assert outsider_project_response.status_code == 404
    assert outsider_task_response.status_code == 404
    assert outsider_label_response.status_code == 404
    assert outsider_comment_delete_response.status_code == 404


def test_comment_delete_combines_workspace_role_and_author_ownership(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    context = create_rbac_context(task_client, test_database_url)
    second_editor_comment_response = task_client.post(
        f"/api/v1/tasks/{context.task_id}/comments",
        headers=context.editor_headers,
        json={"content": "Second editor comment"},
    )
    assert second_editor_comment_response.status_code == 201

    editor_other_comment_response = task_client.delete(
        f"/api/v1/comments/{context.owner_comment_id}",
        headers=context.editor_headers,
    )
    viewer_comment_response = task_client.delete(
        f"/api/v1/comments/{context.owner_comment_id}",
        headers=context.viewer_headers,
    )
    editor_own_comment_response = task_client.delete(
        f"/api/v1/comments/{context.editor_comment_id}",
        headers=context.editor_headers,
    )
    admin_comment_response = task_client.post(
        f"/api/v1/tasks/{context.task_id}/comments",
        headers=context.admin_headers,
        json={"content": "Admin cleanup target"},
    )
    assert admin_comment_response.status_code == 201
    admin_delete_response = task_client.delete(
        f"/api/v1/comments/{admin_comment_response.json()['id']}",
        headers=context.admin_headers,
    )
    owner_delete_response = task_client.delete(
        f"/api/v1/comments/{second_editor_comment_response.json()['id']}",
        headers=context.owner_headers,
    )

    assert editor_other_comment_response.status_code == 403
    assert viewer_comment_response.status_code == 403
    assert editor_own_comment_response.status_code == 204
    assert admin_delete_response.status_code == 204
    assert owner_delete_response.status_code == 204
