import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import create_app
from app.models.enums import ProjectStatus, UserRole, WorkspaceMemberRole
from app.models.project import Project
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember
from app.repositories.workspace import WorkspaceRepository
from tests.test_auth_api import (
    assert_bearer_401,
    login_user,
    register_user,
    set_user_active,
)

WORKSPACE_FIELDS = {"id", "name", "owner_id", "created_at", "updated_at"}
MEMBER_FIELDS = {
    "workspace_id",
    "user_id",
    "email",
    "full_name",
    "role",
    "joined_at",
}


@dataclass(frozen=True)
class WorkspaceSnapshot:
    id: UUID
    name: str
    owner_id: UUID


@dataclass(frozen=True)
class MemberSnapshot:
    workspace_id: UUID
    user_id: UUID
    role: WorkspaceMemberRole


class OwnerMemberCreateFailure(Exception):
    """Raised by tests to exercise transaction rollback."""


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
    name: str = "Workspace Alpha",
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


async def get_workspace(
    database_url: str,
    workspace_id: UUID,
) -> WorkspaceSnapshot | None:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            workspace = await session.get(Workspace, workspace_id)
            if workspace is None:
                return None
            return WorkspaceSnapshot(
                id=workspace.id,
                name=workspace.name,
                owner_id=workspace.owner_id,
            )
    finally:
        await engine.dispose()


async def list_members(
    database_url: str,
    workspace_id: UUID,
) -> list[MemberSnapshot]:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            result = await session.scalars(
                select(WorkspaceMember)
                .where(WorkspaceMember.workspace_id == workspace_id)
                .order_by(WorkspaceMember.joined_at.asc())
            )
            return [
                MemberSnapshot(
                    workspace_id=member.workspace_id,
                    user_id=member.user_id,
                    role=member.role,
                )
                for member in result.all()
            ]
    finally:
        await engine.dispose()


async def count_members(
    database_url: str,
    workspace_id: UUID,
) -> int:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(WorkspaceMember)
                .where(WorkspaceMember.workspace_id == workspace_id)
            )
            return int(count or 0)
    finally:
        await engine.dispose()


async def count_owner_members(
    database_url: str,
    workspace_id: UUID,
) -> int:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(WorkspaceMember)
                .where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.role == WorkspaceMemberRole.OWNER,
                )
            )
            return int(count or 0)
    finally:
        await engine.dispose()


async def count_workspaces(database_url: str) -> int:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            count = await session.scalar(select(func.count()).select_from(Workspace))
            return int(count or 0)
    finally:
        await engine.dispose()


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


async def insert_project(
    database_url: str,
    *,
    workspace_id: UUID,
    created_by: UUID,
) -> UUID:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            project = Project(
                workspace_id=workspace_id,
                created_by=created_by,
                name="Referenced Project",
                description=None,
                status=ProjectStatus.ACTIVE,
            )
            session.add(project)
            await session.commit()
            return project.id
    finally:
        await engine.dispose()


async def count_projects_for_workspace(
    database_url: str,
    workspace_id: UUID,
) -> int:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(Project)
                .where(Project.workspace_id == workspace_id)
            )
            return int(count or 0)
    finally:
        await engine.dispose()


def workspace_ids(response: object) -> list[str]:
    assert isinstance(response, list)
    return [str(item["id"]) for item in response]


def register_workspace_users(
    client: TestClient,
    database_url: str,
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
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
    return owner, editor, viewer, outsider, admin


def test_workspace_routes_require_auth_and_active_current_user(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    missing_response = task_client.get("/api/v1/workspaces")
    invalid_response = task_client.post(
        "/api/v1/workspaces",
        headers={"Authorization": "Bearer not-a-jwt"},
        json={"name": "Invalid Auth Workspace"},
    )
    inactive_user = register_user(
        task_client,
        email="inactive-current@example.com",
    )
    inactive_headers = auth_headers(task_client, email="inactive-current@example.com")
    asyncio.run(
        set_user_active(test_database_url, UUID(str(inactive_user["id"])), False)
    )
    inactive_response = task_client.get(
        "/api/v1/workspaces",
        headers=inactive_headers,
    )

    assert_bearer_401(missing_response, "Could not validate credentials")
    assert_bearer_401(invalid_response, "Could not validate credentials")
    assert inactive_response.status_code == 403
    assert inactive_response.json() == {"detail": "Inactive user"}


def test_create_workspace_returns_owner_and_persists_aligned_membership(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    owner = register_user(task_client, email="create-owner@example.com")
    owner_headers = auth_headers(task_client, email="create-owner@example.com")

    body = create_workspace(
        task_client,
        owner_headers,
        name="  Alpha Workspace  ",
    )
    workspace_id = UUID(str(body["id"]))

    assert set(body) == WORKSPACE_FIELDS
    assert body["name"] == "Alpha Workspace"
    assert body["owner_id"] == owner["id"]

    persisted = asyncio.run(get_workspace(test_database_url, workspace_id))
    members = asyncio.run(list_members(test_database_url, workspace_id))
    owner_members = asyncio.run(count_owner_members(test_database_url, workspace_id))

    assert persisted == WorkspaceSnapshot(
        id=workspace_id,
        name="Alpha Workspace",
        owner_id=UUID(str(owner["id"])),
    )
    assert members == [
        MemberSnapshot(
            workspace_id=workspace_id,
            user_id=UUID(str(owner["id"])),
            role=WorkspaceMemberRole.OWNER,
        )
    ]
    assert owner_members == 1
    assert persisted is not None
    assert persisted.owner_id == members[0].user_id

    with TestClient(create_app()) as second_client:
        persisted_response = second_client.get(
            f"/api/v1/workspaces/{workspace_id}",
            headers=owner_headers,
        )

    assert persisted_response.status_code == 200
    assert persisted_response.json()["name"] == "Alpha Workspace"


def test_create_workspace_rolls_back_when_owner_membership_creation_fails(
    task_client: TestClient,
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register_user(task_client, email="rollback-owner@example.com")
    owner_headers = auth_headers(task_client, email="rollback-owner@example.com")

    async def fail_create_member(
        self: WorkspaceRepository,
        member: WorkspaceMember,
    ) -> WorkspaceMember:
        raise OwnerMemberCreateFailure

    monkeypatch.setattr(WorkspaceRepository, "create_member", fail_create_member)

    with pytest.raises(OwnerMemberCreateFailure):
        task_client.post(
            "/api/v1/workspaces",
            headers=owner_headers,
            json={"name": "Rollback Workspace"},
        )

    assert asyncio.run(count_workspaces(test_database_url)) == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"name": None},
        {"name": ""},
        {"name": "   "},
        {"name": "A" * 256},
        {"name": "Valid", "owner_id": "00000000-0000-4000-8000-000000000001"},
        {"id": "00000000-0000-4000-8000-000000000001", "name": "Valid"},
        {"unknown": "value"},
    ],
)
def test_create_workspace_rejects_invalid_names_and_read_only_fields(
    task_client: TestClient,
    payload: dict[str, object],
) -> None:
    register_user(task_client, email="invalid-create-owner@example.com")
    headers = auth_headers(task_client, email="invalid-create-owner@example.com")

    response = task_client.post(
        "/api/v1/workspaces",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 422


def test_patch_workspace_validation_and_empty_body_do_not_change_workspace(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    owner = register_user(task_client, email="patch-owner@example.com")
    headers = auth_headers(task_client, email="patch-owner@example.com")
    workspace = create_workspace(task_client, headers, name="Patch Workspace")
    workspace_id = UUID(str(workspace["id"]))

    empty_response = task_client.patch(
        f"/api/v1/workspaces/{workspace_id}",
        headers=headers,
        json={},
    )

    assert empty_response.status_code == 400
    assert empty_response.json() == {"detail": "No workspace changes provided"}

    invalid_payloads: list[dict[str, object]] = [
        {"name": None},
        {"name": ""},
        {"name": "   "},
        {"name": "A" * 256},
        {"owner_id": owner["id"]},
        {"id": workspace["id"]},
        {"created_at": "2026-08-04T00:00:00Z"},
        {"updated_at": "2026-08-04T00:00:00Z"},
        {"unknown": "value"},
    ]
    for payload in invalid_payloads:
        response = task_client.patch(
            f"/api/v1/workspaces/{workspace_id}",
            headers=headers,
            json=payload,
        )
        assert response.status_code == 422

    persisted = asyncio.run(get_workspace(test_database_url, workspace_id))
    assert persisted is not None
    assert persisted.name == "Patch Workspace"


def test_empty_workspace_patch_checks_visibility_and_permission_first(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    _, editor, viewer, _, _ = register_workspace_users(task_client, test_database_url)
    owner_headers = auth_headers(task_client, email="owner@example.com")
    editor_headers = auth_headers(task_client, email="editor@example.com")
    viewer_headers = auth_headers(task_client, email="viewer@example.com")
    outsider_headers = auth_headers(task_client, email="outsider@example.com")
    admin_headers = auth_headers(task_client, email="admin@example.com")
    workspace = create_workspace(task_client, owner_headers, name="Empty Patch Authz")
    workspace_id = UUID(str(workspace["id"]))
    add_member(task_client, owner_headers, workspace_id, email=str(editor["email"]))
    add_member(
        task_client,
        owner_headers,
        workspace_id,
        email=str(viewer["email"]),
        role="VIEWER",
    )

    missing_workspace = task_client.patch(
        f"/api/v1/workspaces/{uuid4()}",
        headers=owner_headers,
        json={},
    )
    non_member = task_client.patch(
        f"/api/v1/workspaces/{workspace_id}",
        headers=outsider_headers,
        json={},
    )
    editor_member = task_client.patch(
        f"/api/v1/workspaces/{workspace_id}",
        headers=editor_headers,
        json={},
    )
    viewer_member = task_client.patch(
        f"/api/v1/workspaces/{workspace_id}",
        headers=viewer_headers,
        json={},
    )
    owner_member = task_client.patch(
        f"/api/v1/workspaces/{workspace_id}",
        headers=owner_headers,
        json={},
    )
    admin = task_client.patch(
        f"/api/v1/workspaces/{workspace_id}",
        headers=admin_headers,
        json={},
    )

    assert missing_workspace.status_code == 404
    assert missing_workspace.json() == {"detail": "Workspace not found"}
    assert non_member.status_code == 404
    assert non_member.json() == {"detail": "Workspace not found"}
    assert editor_member.status_code == 403
    assert editor_member.json() == {"detail": "Not enough workspace permissions"}
    assert viewer_member.status_code == 403
    assert viewer_member.json() == {"detail": "Not enough workspace permissions"}
    assert owner_member.status_code == 400
    assert owner_member.json() == {"detail": "No workspace changes provided"}
    assert admin.status_code == 400
    assert admin.json() == {"detail": "No workspace changes provided"}


def test_read_and_collection_visibility_by_role(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    owner, editor, viewer, _outsider, admin = register_workspace_users(
        task_client,
        test_database_url,
    )
    owner_headers = auth_headers(task_client, email="owner@example.com")
    editor_headers = auth_headers(task_client, email="editor@example.com")
    viewer_headers = auth_headers(task_client, email="viewer@example.com")
    outsider_headers = auth_headers(task_client, email="outsider@example.com")
    admin_headers = auth_headers(task_client, email="admin@example.com")
    workspace = create_workspace(task_client, owner_headers, name="Visible Workspace")
    workspace_id = UUID(str(workspace["id"]))
    add_member(task_client, owner_headers, workspace_id, email=str(editor["email"]))
    add_member(
        task_client,
        owner_headers,
        workspace_id,
        email=str(viewer["email"]),
        role="VIEWER",
    )

    visible_headers = [admin_headers, owner_headers, editor_headers, viewer_headers]
    for headers in visible_headers:
        read_response = task_client.get(
            f"/api/v1/workspaces/{workspace_id}",
            headers=headers,
        )
        list_response = task_client.get("/api/v1/workspaces", headers=headers)
        assert read_response.status_code == 200
        assert str(workspace_id) in workspace_ids(list_response.json())

    outsider_read = task_client.get(
        f"/api/v1/workspaces/{workspace_id}",
        headers=outsider_headers,
    )
    outsider_list = task_client.get("/api/v1/workspaces", headers=outsider_headers)

    assert outsider_read.status_code == 404
    assert outsider_read.json() == {"detail": "Workspace not found"}
    assert str(workspace_id) not in workspace_ids(outsider_list.json())
    assert UUID(str(owner["id"])) == UUID(str(workspace["owner_id"]))
    assert UUID(str(admin["id"])) != UUID(str(workspace["owner_id"]))


def test_workspace_update_permissions_and_admin_override(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    _, editor, viewer, _, _ = register_workspace_users(task_client, test_database_url)
    owner_headers = auth_headers(task_client, email="owner@example.com")
    editor_headers = auth_headers(task_client, email="editor@example.com")
    viewer_headers = auth_headers(task_client, email="viewer@example.com")
    outsider_headers = auth_headers(task_client, email="outsider@example.com")
    admin_headers = auth_headers(task_client, email="admin@example.com")
    workspace = create_workspace(task_client, owner_headers, name="Original Workspace")
    workspace_id = UUID(str(workspace["id"]))
    add_member(task_client, owner_headers, workspace_id, email=str(editor["email"]))
    add_member(
        task_client,
        owner_headers,
        workspace_id,
        email=str(viewer["email"]),
        role="VIEWER",
    )

    owner_update = task_client.patch(
        f"/api/v1/workspaces/{workspace_id}",
        headers=owner_headers,
        json={"name": "Owner Updated Workspace"},
    )
    editor_update = task_client.patch(
        f"/api/v1/workspaces/{workspace_id}",
        headers=editor_headers,
        json={"name": "Editor Attempt"},
    )
    viewer_update = task_client.patch(
        f"/api/v1/workspaces/{workspace_id}",
        headers=viewer_headers,
        json={"name": "Viewer Attempt"},
    )
    outsider_update = task_client.patch(
        f"/api/v1/workspaces/{workspace_id}",
        headers=outsider_headers,
        json={"name": "Outsider Attempt"},
    )
    admin_update = task_client.patch(
        f"/api/v1/workspaces/{workspace_id}",
        headers=admin_headers,
        json={"name": "Admin Updated Workspace"},
    )
    persisted = asyncio.run(get_workspace(test_database_url, workspace_id))

    assert owner_update.status_code == 200
    assert owner_update.json()["name"] == "Owner Updated Workspace"
    assert editor_update.status_code == 403
    assert viewer_update.status_code == 403
    assert outsider_update.status_code == 404
    assert admin_update.status_code == 200
    assert admin_update.json()["name"] == "Admin Updated Workspace"
    assert persisted is not None
    assert persisted.name == "Admin Updated Workspace"


def test_workspace_delete_handles_permissions_empty_workspace_and_project_conflict(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    owner, editor, _, _, _ = register_workspace_users(task_client, test_database_url)
    owner_headers = auth_headers(task_client, email="owner@example.com")
    editor_headers = auth_headers(task_client, email="editor@example.com")
    outsider_headers = auth_headers(task_client, email="outsider@example.com")
    workspace = create_workspace(task_client, owner_headers, name="Delete Workspace")
    workspace_id = UUID(str(workspace["id"]))
    add_member(task_client, owner_headers, workspace_id, email=str(editor["email"]))

    editor_delete = task_client.delete(
        f"/api/v1/workspaces/{workspace_id}",
        headers=editor_headers,
    )
    outsider_delete = task_client.delete(
        f"/api/v1/workspaces/{workspace_id}",
        headers=outsider_headers,
    )

    assert editor_delete.status_code == 403
    assert outsider_delete.status_code == 404

    owner_delete = task_client.delete(
        f"/api/v1/workspaces/{workspace_id}",
        headers=owner_headers,
    )

    assert owner_delete.status_code == 204
    assert owner_delete.content == b""
    assert asyncio.run(get_workspace(test_database_url, workspace_id)) is None
    assert asyncio.run(count_members(test_database_url, workspace_id)) == 0

    conflict_workspace = create_workspace(
        task_client,
        owner_headers,
        name="Project Conflict Workspace",
    )
    conflict_workspace_id = UUID(str(conflict_workspace["id"]))
    asyncio.run(
        insert_project(
            test_database_url,
            workspace_id=conflict_workspace_id,
            created_by=UUID(str(owner["id"])),
        )
    )

    conflict_response = task_client.delete(
        f"/api/v1/workspaces/{conflict_workspace_id}",
        headers=owner_headers,
    )

    assert conflict_response.status_code == 409
    assert conflict_response.json() == {"detail": "Workspace contains projects"}
    assert asyncio.run(get_workspace(test_database_url, conflict_workspace_id))
    assert (
        asyncio.run(
            count_projects_for_workspace(test_database_url, conflict_workspace_id)
        )
        == 1
    )


def test_member_list_and_add_member_by_normalized_email(
    task_client: TestClient,
) -> None:
    owner = register_user(task_client, email="member-owner@example.com")
    target = register_user(
        task_client,
        email="target.member@example.com",
        full_name="Target Member",
    )
    owner_headers = auth_headers(task_client, email="member-owner@example.com")
    workspace = create_workspace(task_client, owner_headers, name="Member Workspace")
    workspace_id = UUID(str(workspace["id"]))

    member = task_client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=owner_headers,
        json={"email": "  TARGET.MEMBER@example.com  ", "role": "VIEWER"},
    )
    member_list = task_client.get(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=owner_headers,
    )

    assert member.status_code == 201
    assert set(member.json()) == MEMBER_FIELDS
    assert member.json() == {
        "workspace_id": str(workspace_id),
        "user_id": target["id"],
        "email": "target.member@example.com",
        "full_name": "Target Member",
        "role": "VIEWER",
        "joined_at": member.json()["joined_at"],
    }
    assert member_list.status_code == 200
    assert [set(item) for item in member_list.json()] == [MEMBER_FIELDS, MEMBER_FIELDS]
    assert [item["user_id"] for item in member_list.json()] == [
        owner["id"],
        target["id"],
    ]
    for item in member_list.json():
        assert "system_role" not in item
        assert "is_active" not in item
        assert "hashed_password" not in item
        assert "created_at" not in item
        assert "updated_at" not in item


def test_add_member_rejects_unknown_inactive_duplicate_and_owner_role(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    target = register_user(task_client, email="duplicate-target@example.com")
    inactive = register_user(task_client, email="inactive-target@example.com")
    register_user(task_client, email="member-errors-owner@example.com")
    owner_headers = auth_headers(task_client, email="member-errors-owner@example.com")
    workspace = create_workspace(task_client, owner_headers, name="Member Errors")
    workspace_id = UUID(str(workspace["id"]))
    asyncio.run(set_user_active(test_database_url, UUID(str(inactive["id"])), False))

    owner_role = task_client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=owner_headers,
        json={"email": target["email"], "role": "OWNER"},
    )
    first_add = task_client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=owner_headers,
        json={"email": target["email"], "role": "EDITOR"},
    )
    duplicate = task_client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=owner_headers,
        json={"email": target["email"], "role": "VIEWER"},
    )
    unknown = task_client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=owner_headers,
        json={"email": "unknown@example.com", "role": "EDITOR"},
    )
    inactive_response = task_client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=owner_headers,
        json={"email": inactive["email"], "role": "EDITOR"},
    )

    assert owner_role.status_code == 422
    assert first_add.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "Workspace member already exists"}
    assert unknown.status_code == 404
    assert unknown.json() == {"detail": "User not found"}
    assert inactive_response.status_code == 409
    assert inactive_response.json() == {"detail": "Target user is inactive"}


def test_concurrent_duplicate_member_add_returns_one_conflict(
    task_client: TestClient,
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = register_user(task_client, email="race-target@example.com")
    register_user(task_client, email="race-owner@example.com")
    owner_headers = auth_headers(task_client, email="race-owner@example.com")
    workspace = create_workspace(task_client, owner_headers, name="Race Workspace")
    workspace_id = UUID(str(workspace["id"]))
    target_id = UUID(str(target["id"]))
    barrier = Barrier(2)
    original_get_member = WorkspaceRepository.get_member

    async def racing_get_member(
        self: WorkspaceRepository,
        member_workspace_id: UUID,
        user_id: UUID,
    ) -> WorkspaceMember | None:
        if member_workspace_id == workspace_id and user_id == target_id:
            await asyncio.to_thread(barrier.wait, 5)
            return None
        return await original_get_member(self, member_workspace_id, user_id)

    monkeypatch.setattr(WorkspaceRepository, "get_member", racing_get_member)

    def add_once() -> int:
        with TestClient(create_app()) as client:
            response = client.post(
                f"/api/v1/workspaces/{workspace_id}/members",
                headers=owner_headers,
                json={"email": "race-target@example.com", "role": "EDITOR"},
            )
            return response.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(lambda _: add_once(), range(2)))

    assert statuses.count(201) == 1
    assert statuses.count(409) == 1
    members = asyncio.run(list_members(test_database_url, workspace_id))
    assert [
        member
        for member in members
        if member.user_id == target_id and member.role is WorkspaceMemberRole.EDITOR
    ] == [
        MemberSnapshot(
            workspace_id=workspace_id,
            user_id=target_id,
            role=WorkspaceMemberRole.EDITOR,
        )
    ]


def test_member_role_update_and_removal_preserve_owner_invariant(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    owner = register_user(task_client, email="role-owner@example.com")
    target = register_user(task_client, email="role-target@example.com")
    owner_headers = auth_headers(task_client, email="role-owner@example.com")
    workspace = create_workspace(task_client, owner_headers, name="Role Workspace")
    workspace_id = UUID(str(workspace["id"]))
    target_id = UUID(str(target["id"]))
    add_member(task_client, owner_headers, workspace_id, email=str(target["email"]))

    owner_role_payload = task_client.patch(
        f"/api/v1/workspaces/{workspace_id}/members/{target_id}",
        headers=owner_headers,
        json={"role": "OWNER"},
    )
    update_to_viewer = task_client.patch(
        f"/api/v1/workspaces/{workspace_id}/members/{target_id}",
        headers=owner_headers,
        json={"role": "VIEWER"},
    )
    idempotent_update = task_client.patch(
        f"/api/v1/workspaces/{workspace_id}/members/{target_id}",
        headers=owner_headers,
        json={"role": "VIEWER"},
    )
    demote_owner = task_client.patch(
        f"/api/v1/workspaces/{workspace_id}/members/{owner['id']}",
        headers=owner_headers,
        json={"role": "VIEWER"},
    )
    remove_owner = task_client.delete(
        f"/api/v1/workspaces/{workspace_id}/members/{owner['id']}",
        headers=owner_headers,
    )
    remove_missing = task_client.delete(
        f"/api/v1/workspaces/{workspace_id}/members/{uuid4()}",
        headers=owner_headers,
    )
    remove_member_response = task_client.delete(
        f"/api/v1/workspaces/{workspace_id}/members/{target_id}",
        headers=owner_headers,
    )
    second_remove = task_client.delete(
        f"/api/v1/workspaces/{workspace_id}/members/{target_id}",
        headers=owner_headers,
    )
    members = asyncio.run(list_members(test_database_url, workspace_id))
    owner_members = asyncio.run(count_owner_members(test_database_url, workspace_id))

    assert owner_role_payload.status_code == 422
    assert update_to_viewer.status_code == 200
    assert update_to_viewer.json()["role"] == "VIEWER"
    assert idempotent_update.status_code == 200
    assert idempotent_update.json()["role"] == "VIEWER"
    assert demote_owner.status_code == 409
    assert demote_owner.json() == {
        "detail": "Workspace owner membership cannot be changed"
    }
    assert remove_owner.status_code == 409
    assert remove_owner.json() == {
        "detail": "Workspace owner membership cannot be changed"
    }
    assert remove_missing.status_code == 404
    assert remove_missing.json() == {"detail": "Workspace member not found"}
    assert remove_member_response.status_code == 204
    assert remove_member_response.content == b""
    assert second_remove.status_code == 404
    assert members == [
        MemberSnapshot(
            workspace_id=workspace_id,
            user_id=UUID(str(owner["id"])),
            role=WorkspaceMemberRole.OWNER,
        )
    ]
    assert owner_members == 1


def test_member_mutation_authorizes_before_target_lookup(
    task_client: TestClient,
) -> None:
    owner = register_user(task_client, email="authz-owner@example.com")
    editor = register_user(task_client, email="authz-editor@example.com")
    viewer = register_user(task_client, email="authz-viewer@example.com")
    register_user(task_client, email="authz-outsider@example.com")
    owner_headers = auth_headers(task_client, email="authz-owner@example.com")
    editor_headers = auth_headers(task_client, email="authz-editor@example.com")
    viewer_headers = auth_headers(task_client, email="authz-viewer@example.com")
    outsider_headers = auth_headers(task_client, email="authz-outsider@example.com")
    workspace = create_workspace(task_client, owner_headers, name="Authz Workspace")
    workspace_id = UUID(str(workspace["id"]))
    add_member(task_client, owner_headers, workspace_id, email=str(editor["email"]))
    add_member(
        task_client,
        owner_headers,
        workspace_id,
        email=str(viewer["email"]),
        role="VIEWER",
    )
    missing_target = uuid4()

    editor_add_unknown = task_client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=editor_headers,
        json={"email": "not-registered@example.com", "role": "EDITOR"},
    )
    viewer_remove_missing = task_client.delete(
        f"/api/v1/workspaces/{workspace_id}/members/{missing_target}",
        headers=viewer_headers,
    )
    outsider_add_unknown = task_client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=outsider_headers,
        json={"email": "not-registered@example.com", "role": "EDITOR"},
    )
    owner_remove_missing = task_client.delete(
        f"/api/v1/workspaces/{workspace_id}/members/{missing_target}",
        headers=owner_headers,
    )

    assert UUID(str(owner["id"])) == UUID(str(workspace["owner_id"]))
    assert editor_add_unknown.status_code == 403
    assert viewer_remove_missing.status_code == 403
    assert outsider_add_unknown.status_code == 404
    assert owner_remove_missing.status_code == 404
