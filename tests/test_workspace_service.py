import asyncio
from dataclasses import dataclass
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.enums import UserRole, WorkspaceMemberRole
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember
from app.repositories.user import UserRepository
from app.repositories.workspace import WorkspaceRepository
from app.schemas.workspace import WorkspaceCreate, WorkspaceMemberAdd
from app.services.workspace import (
    WorkspaceMemberAlreadyExistsError,
    WorkspaceService,
)


class OwnerMemberCreateFailure(Exception):
    """Raised by tests to exercise workspace creation rollback."""


@dataclass(frozen=True)
class WorkspaceServiceTestUsers:
    owner: User
    target: User


class DuplicatePrecheckGate:
    """Release two concurrent calls only after both pass the duplicate pre-check."""

    def __init__(self, expected_count: int) -> None:
        self._expected_count = expected_count
        self._arrived = 0
        self._event = asyncio.Event()

    async def wait(self) -> None:
        self._arrived += 1
        if self._arrived == self._expected_count:
            self._event.set()
        await asyncio.wait_for(self._event.wait(), timeout=5)


async def insert_user(
    database_url: str,
    *,
    email: str,
    full_name: str,
    role: UserRole = UserRole.MEMBER,
) -> User:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            user = User(
                email=email,
                full_name=full_name,
                hashed_password="hashed-password",
                role=role,
                is_active=True,
            )
            session.add(user)
            await session.commit()
            return user
    finally:
        await engine.dispose()


async def workspace_count_by_name(database_url: str, name: str) -> int:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(Workspace)
                .where(Workspace.name == name)
            )
            return int(count or 0)
    finally:
        await engine.dispose()


async def member_count(
    database_url: str,
    *,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
) -> int:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            statement = select(func.count()).select_from(WorkspaceMember)
            if workspace_id is not None:
                statement = statement.where(
                    WorkspaceMember.workspace_id == workspace_id
                )
            if user_id is not None:
                statement = statement.where(WorkspaceMember.user_id == user_id)
            count = await session.scalar(statement)
            return int(count or 0)
    finally:
        await engine.dispose()


async def create_workspace_with_service(
    database_url: str,
    owner: User,
    *,
    name: str,
) -> UUID:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            service = WorkspaceService(
                WorkspaceRepository(session),
                UserRepository(session),
                session,
            )
            workspace = await service.create_workspace(
                owner, WorkspaceCreate(name=name)
            )
            return workspace.id
    finally:
        await engine.dispose()


async def run_add_member(
    database_url: str,
    *,
    owner: User,
    workspace_id: UUID,
    target_email: str,
) -> str:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            service = WorkspaceService(
                WorkspaceRepository(session),
                UserRepository(session),
                session,
            )
            try:
                await service.add_member(
                    owner,
                    workspace_id,
                    WorkspaceMemberAdd(
                        email=target_email,
                        role=WorkspaceMemberRole.EDITOR,
                    ),
                )
            except WorkspaceMemberAlreadyExistsError:
                return "duplicate"
            return "success"
    finally:
        await engine.dispose()


async def create_duplicate_test_users(
    database_url: str,
) -> WorkspaceServiceTestUsers:
    owner = await insert_user(
        database_url,
        email="service-owner@example.com",
        full_name="Service Owner",
    )
    target = await insert_user(
        database_url,
        email="service-target@example.com",
        full_name="Service Target",
    )
    return WorkspaceServiceTestUsers(owner=owner, target=target)


def test_create_workspace_rolls_back_if_owner_membership_insert_fails(
    test_database_url: str,
    clean_test_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run_test() -> None:
        owner = await insert_user(
            test_database_url,
            email="atomic-owner@example.com",
            full_name="Atomic Owner",
        )
        inserted_workspace_id: UUID | None = None
        engine = create_async_engine(test_database_url)
        session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

        async def fail_create_member(
            self: WorkspaceRepository,
            member: WorkspaceMember,
        ) -> WorkspaceMember:
            nonlocal inserted_workspace_id
            inserted_workspace_id = member.workspace_id
            assert await self.get_by_id(member.workspace_id) is not None
            raise OwnerMemberCreateFailure

        monkeypatch.setattr(WorkspaceRepository, "create_member", fail_create_member)

        try:
            async with session_factory() as session:
                service = WorkspaceService(
                    WorkspaceRepository(session),
                    UserRepository(session),
                    session,
                )
                with pytest.raises(OwnerMemberCreateFailure):
                    await service.create_workspace(
                        owner,
                        WorkspaceCreate(name="Atomic Rollback Workspace"),
                    )
        finally:
            await engine.dispose()

        assert inserted_workspace_id is not None
        assert (
            await workspace_count_by_name(
                test_database_url,
                "Atomic Rollback Workspace",
            )
            == 0
        )
        assert (
            await member_count(
                test_database_url,
                workspace_id=inserted_workspace_id,
            )
            == 0
        )
        assert await member_count(test_database_url, user_id=owner.id) == 0

    asyncio.run(run_test())


def test_concurrent_duplicate_member_add_uses_postgresql_composite_pk(
    test_database_url: str,
    clean_test_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run_test() -> None:
        users = await create_duplicate_test_users(test_database_url)
        workspace_id = await create_workspace_with_service(
            test_database_url,
            users.owner,
            name="Service Race Workspace",
        )
        gate = DuplicatePrecheckGate(expected_count=2)
        original_get_member = WorkspaceRepository.get_member

        async def gated_get_member(
            self: WorkspaceRepository,
            member_workspace_id: UUID,
            user_id: UUID,
        ) -> WorkspaceMember | None:
            if member_workspace_id == workspace_id and user_id == users.target.id:
                assert (
                    await original_get_member(self, member_workspace_id, user_id)
                    is None
                )
                await gate.wait()
                return None
            return await original_get_member(self, member_workspace_id, user_id)

        monkeypatch.setattr(WorkspaceRepository, "get_member", gated_get_member)

        results = await asyncio.gather(
            run_add_member(
                test_database_url,
                owner=users.owner,
                workspace_id=workspace_id,
                target_email=users.target.email,
            ),
            run_add_member(
                test_database_url,
                owner=users.owner,
                workspace_id=workspace_id,
                target_email=users.target.email,
            ),
        )

        assert sorted(results) == ["duplicate", "success"]
        assert (
            await member_count(
                test_database_url,
                workspace_id=workspace_id,
                user_id=users.target.id,
            )
            == 1
        )

    asyncio.run(run_test())
