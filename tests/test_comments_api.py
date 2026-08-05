import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.comment import Comment
from app.models.enums import UserRole
from app.models.user import User
from tests.test_auth_api import (
    assert_bearer_401,
    login_user,
    register_user,
    set_user_active,
)

COMMENT_FIELDS = {"id", "task_id", "author_id", "content", "created_at"}


@dataclass(frozen=True)
class CommentApiContext:
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
class CommentSnapshot:
    id: UUID
    task_id: UUID
    author_id: UUID
    content: str


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


def create_comment(
    client: TestClient,
    headers: dict[str, str],
    task_id: UUID,
    *,
    content: str = "Comment content",
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/tasks/{task_id}/comments",
        headers=headers,
        json={"content": content},
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


async def insert_comment(
    database_url: str,
    *,
    task_id: UUID,
    author_id: UUID,
    content: str = "Inserted comment",
) -> UUID:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            comment = Comment(task_id=task_id, author_id=author_id, content=content)
            session.add(comment)
            await session.commit()
            return comment.id
    finally:
        await engine.dispose()


async def get_comment(
    database_url: str,
    comment_id: UUID,
) -> CommentSnapshot | None:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            comment = await session.get(Comment, comment_id)
            if comment is None:
                return None
            return CommentSnapshot(
                id=comment.id,
                task_id=comment.task_id,
                author_id=comment.author_id,
                content=comment.content,
            )
    finally:
        await engine.dispose()


async def count_comments(
    database_url: str,
    *,
    task_id: UUID | None = None,
    author_id: UUID | None = None,
) -> int:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            statement = select(func.count()).select_from(Comment)
            if task_id is not None:
                statement = statement.where(Comment.task_id == task_id)
            if author_id is not None:
                statement = statement.where(Comment.author_id == author_id)
            count = await session.scalar(statement)
            return int(count or 0)
    finally:
        await engine.dispose()


def register_comment_context(
    client: TestClient,
    database_url: str,
) -> CommentApiContext:
    owner = register_user(client, email="comment-owner@example.com")
    editor = register_user(client, email="comment-editor@example.com")
    viewer = register_user(client, email="comment-viewer@example.com")
    outsider = register_user(client, email="comment-outsider@example.com")
    admin = register_user(client, email="comment-admin@example.com")
    asyncio.run(set_user_role(database_url, UUID(str(admin["id"])), UserRole.ADMIN))

    owner_headers = auth_headers(client, email="comment-owner@example.com")
    editor_headers = auth_headers(client, email="comment-editor@example.com")
    viewer_headers = auth_headers(client, email="comment-viewer@example.com")
    outsider_headers = auth_headers(client, email="comment-outsider@example.com")
    admin_headers = auth_headers(client, email="comment-admin@example.com")

    workspace = create_workspace(
        client,
        owner_headers,
        name="Comment Workspace",
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
        name="Comment Project",
    )
    project_id = UUID(str(project["id"]))
    task = create_task(
        client,
        owner_headers,
        project_id,
        title="Comment Task",
    )

    other_workspace = create_workspace(
        client,
        outsider_headers,
        name="Other Comment Workspace",
    )
    other_workspace_id = UUID(str(other_workspace["id"]))
    other_project = create_project(
        client,
        outsider_headers,
        other_workspace_id,
        name="Other Comment Project",
    )
    other_project_id = UUID(str(other_project["id"]))
    other_task = create_task(
        client,
        outsider_headers,
        other_project_id,
        title="Other Comment Task",
    )

    return CommentApiContext(
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


def test_comment_routes_require_auth_and_active_current_user(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    context = register_comment_context(task_client, test_database_url)
    comment = create_comment(task_client, context.owner_headers, context.task_id)
    inactive_headers = auth_headers(task_client, email="comment-owner@example.com")
    asyncio.run(
        set_user_active(test_database_url, UUID(str(context.owner["id"])), False)
    )

    missing_response = task_client.post(
        f"/api/v1/tasks/{context.task_id}/comments",
        json={"content": "Missing auth"},
    )
    invalid_response = task_client.delete(
        f"/api/v1/comments/{comment['id']}",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    inactive_response = task_client.post(
        f"/api/v1/tasks/{context.task_id}/comments",
        headers=inactive_headers,
        json={"content": "Inactive user"},
    )

    assert_bearer_401(missing_response, "Could not validate credentials")
    assert_bearer_401(invalid_response, "Could not validate credentials")
    assert inactive_response.status_code == 403
    assert inactive_response.json() == {"detail": "Inactive user"}


def test_create_comment_permissions_author_and_trimmed_content(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    context = register_comment_context(task_client, test_database_url)

    owner_comment = create_comment(
        task_client,
        context.owner_headers,
        context.task_id,
        content="  Owner content  ",
    )
    editor_comment = create_comment(
        task_client,
        context.editor_headers,
        context.task_id,
        content="Editor content",
    )
    admin_comment = create_comment(
        task_client,
        context.admin_headers,
        context.task_id,
        content="Admin content",
    )
    viewer_response = task_client.post(
        f"/api/v1/tasks/{context.task_id}/comments",
        headers=context.viewer_headers,
        json={"content": "Viewer content"},
    )
    outsider_response = task_client.post(
        f"/api/v1/tasks/{context.task_id}/comments",
        headers=context.outsider_headers,
        json={"content": "Outsider content"},
    )

    assert set(owner_comment) == COMMENT_FIELDS
    assert owner_comment["task_id"] == str(context.task_id)
    assert owner_comment["author_id"] == context.owner["id"]
    assert owner_comment["content"] == "Owner content"
    assert UUID(str(owner_comment["id"])).version == 4
    assert datetime.fromisoformat(str(owner_comment["created_at"])).tzinfo is not None
    assert editor_comment["author_id"] == context.editor["id"]
    assert admin_comment["author_id"] == context.admin["id"]
    assert viewer_response.status_code == 403
    assert viewer_response.json() == {"detail": "Not enough comment permissions"}
    assert outsider_response.status_code == 404
    assert outsider_response.json() == {"detail": "Task not found"}
    assert asyncio.run(count_comments(test_database_url, task_id=context.task_id)) == 3


def test_create_comment_allows_archived_project(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    context = register_comment_context(task_client, test_database_url)

    archive_response = task_client.patch(
        f"/api/v1/projects/{context.project_id}/archive",
        headers=context.owner_headers,
    )
    create_response = task_client.post(
        f"/api/v1/tasks/{context.task_id}/comments",
        headers=context.editor_headers,
        json={"content": "Comment after archive"},
    )

    assert archive_response.status_code == 200
    assert create_response.status_code == 201
    assert create_response.json()["content"] == "Comment after archive"


def test_create_comment_rejects_invalid_unknown_and_read_only_fields(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    context = register_comment_context(task_client, test_database_url)
    invalid_payloads: list[dict[str, object]] = [
        {},
        {"content": None},
        {"content": ""},
        {"content": "   "},
        {"content": "Valid", "id": str(uuid4())},
        {"content": "Valid", "task_id": str(context.task_id)},
        {"content": "Valid", "author_id": context.owner["id"]},
        {
            "content": "Valid",
            "created_at": datetime.now(UTC).isoformat(),
        },
        {"content": "Valid", "unknown": "value"},
    ]

    for payload in invalid_payloads:
        response = task_client.post(
            f"/api/v1/tasks/{context.task_id}/comments",
            headers=context.owner_headers,
            json=payload,
        )
        assert response.status_code == 422

    assert asyncio.run(count_comments(test_database_url, task_id=context.task_id)) == 0


def test_create_comment_missing_and_hidden_task(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    context = register_comment_context(task_client, test_database_url)

    missing_task = task_client.post(
        f"/api/v1/tasks/{uuid4()}/comments",
        headers=context.owner_headers,
        json={"content": "Missing task"},
    )
    hidden_task = task_client.post(
        f"/api/v1/tasks/{context.other_task_id}/comments",
        headers=context.owner_headers,
        json={"content": "Hidden task"},
    )
    hidden_from_nonmember = task_client.post(
        f"/api/v1/tasks/{context.task_id}/comments",
        headers=context.outsider_headers,
        json={"content": "Hidden from nonmember"},
    )

    assert missing_task.status_code == 404
    assert missing_task.json() == {"detail": "Task not found"}
    assert hidden_task.status_code == 404
    assert hidden_task.json() == {"detail": "Task not found"}
    assert hidden_from_nonmember.status_code == 404
    assert hidden_from_nonmember.json() == {"detail": "Task not found"}


def test_delete_comment_role_and_ownership_rules(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    context = register_comment_context(task_client, test_database_url)

    editor_own = create_comment(
        task_client,
        context.editor_headers,
        context.task_id,
        content="Editor own",
    )
    editor_own_delete = task_client.delete(
        f"/api/v1/comments/{editor_own['id']}",
        headers=context.editor_headers,
    )

    editor_comment = create_comment(
        task_client,
        context.editor_headers,
        context.task_id,
        content="Owner may delete editor comment",
    )
    owner_deletes_other = task_client.delete(
        f"/api/v1/comments/{editor_comment['id']}",
        headers=context.owner_headers,
    )

    owner_comment = create_comment(
        task_client,
        context.owner_headers,
        context.task_id,
        content="Admin may delete owner comment",
    )
    admin_deletes_other = task_client.delete(
        f"/api/v1/comments/{owner_comment['id']}",
        headers=context.admin_headers,
    )

    owner_for_editor_denial = create_comment(
        task_client,
        context.owner_headers,
        context.task_id,
        content="Editor cannot delete another user comment",
    )
    editor_deletes_other = task_client.delete(
        f"/api/v1/comments/{owner_for_editor_denial['id']}",
        headers=context.editor_headers,
    )

    viewer_comment_id = asyncio.run(
        insert_comment(
            test_database_url,
            task_id=context.task_id,
            author_id=UUID(str(context.viewer["id"])),
            content="Viewer own direct insert",
        )
    )
    viewer_deletes_own = task_client.delete(
        f"/api/v1/comments/{viewer_comment_id}",
        headers=context.viewer_headers,
    )

    assert editor_own_delete.status_code == 204
    assert editor_own_delete.content == b""
    assert owner_deletes_other.status_code == 204
    assert owner_deletes_other.content == b""
    assert admin_deletes_other.status_code == 204
    assert admin_deletes_other.content == b""
    assert editor_deletes_other.status_code == 403
    assert editor_deletes_other.json() == {"detail": "Not enough comment permissions"}
    assert viewer_deletes_own.status_code == 403
    assert viewer_deletes_own.json() == {"detail": "Not enough comment permissions"}
    assert (
        asyncio.run(
            get_comment(test_database_url, UUID(str(owner_for_editor_denial["id"])))
        )
        is not None
    )
    assert asyncio.run(get_comment(test_database_url, viewer_comment_id)) is not None


def test_delete_comment_missing_hidden_and_already_deleted(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    context = register_comment_context(task_client, test_database_url)
    visible_comment = create_comment(
        task_client, context.owner_headers, context.task_id
    )
    hidden_comment = create_comment(
        task_client,
        context.outsider_headers,
        context.other_task_id,
        content="Hidden comment",
    )

    missing = task_client.delete(
        f"/api/v1/comments/{uuid4()}",
        headers=context.owner_headers,
    )
    nonmember_delete = task_client.delete(
        f"/api/v1/comments/{visible_comment['id']}",
        headers=context.outsider_headers,
    )
    hidden_delete = task_client.delete(
        f"/api/v1/comments/{hidden_comment['id']}",
        headers=context.owner_headers,
    )
    owner_delete = task_client.delete(
        f"/api/v1/comments/{visible_comment['id']}",
        headers=context.owner_headers,
    )
    already_deleted = task_client.delete(
        f"/api/v1/comments/{visible_comment['id']}",
        headers=context.owner_headers,
    )

    assert missing.status_code == 404
    assert missing.json() == {"detail": "Comment not found"}
    assert nonmember_delete.status_code == 404
    assert nonmember_delete.json() == {"detail": "Comment not found"}
    assert hidden_delete.status_code == 404
    assert hidden_delete.json() == {"detail": "Comment not found"}
    assert owner_delete.status_code == 204
    assert owner_delete.content == b""
    assert already_deleted.status_code == 404
    assert already_deleted.json() == {"detail": "Comment not found"}
