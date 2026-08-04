import asyncio
from dataclasses import dataclass
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

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
from app.repositories.project import ProjectRepository
from app.repositories.workspace import WorkspaceRepository
from app.schemas.project import ProjectCreate
from app.services.project import ProjectHasChildrenError, ProjectService


class ProjectCreateFailure(Exception):
    """Raised by tests to exercise project creation rollback."""


@dataclass(frozen=True)
class ProjectServiceContext:
    owner: User
    workspace_id: UUID
    project_id: UUID


class DeletePrecheckGate:
    """Block delete until a concurrent task insert commits after pre-check."""

    def __init__(self) -> None:
        self.precheck_complete = asyncio.Event()
        self.child_inserted = asyncio.Event()

    async def wait_for_child_insert(self) -> None:
        self.precheck_complete.set()
        await asyncio.wait_for(self.child_inserted.wait(), timeout=5)


async def insert_project_context(
    database_url: str,
    *,
    archived: bool = False,
) -> ProjectServiceContext:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            owner = User(
                email="project-service-owner@example.com",
                full_name="Project Service Owner",
                hashed_password="hashed-password",
                role=UserRole.MEMBER,
                is_active=True,
            )
            session.add(owner)
            await session.flush()

            workspace = Workspace(name="Project Service Workspace", owner_id=owner.id)
            session.add(workspace)
            await session.flush()

            session.add(
                WorkspaceMember(
                    workspace_id=workspace.id,
                    user_id=owner.id,
                    role=WorkspaceMemberRole.OWNER,
                )
            )
            project = Project(
                workspace_id=workspace.id,
                created_by=owner.id,
                name="Service Project",
                description=None,
                status=(ProjectStatus.ARCHIVED if archived else ProjectStatus.ACTIVE),
            )
            session.add(project)
            await session.commit()

            return ProjectServiceContext(
                owner=owner,
                workspace_id=workspace.id,
                project_id=project.id,
            )
    finally:
        await engine.dispose()


async def create_workspace_context(database_url: str) -> tuple[User, UUID]:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            owner = User(
                email="atomic-project-owner@example.com",
                full_name="Atomic Project Owner",
                hashed_password="hashed-password",
                role=UserRole.MEMBER,
                is_active=True,
            )
            session.add(owner)
            await session.flush()

            workspace = Workspace(name="Atomic Project Workspace", owner_id=owner.id)
            session.add(workspace)
            await session.flush()

            session.add(
                WorkspaceMember(
                    workspace_id=workspace.id,
                    user_id=owner.id,
                    role=WorkspaceMemberRole.OWNER,
                )
            )
            await session.commit()
            return owner, workspace.id
    finally:
        await engine.dispose()


async def project_count_by_name(database_url: str, name: str) -> int:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            count = await session.scalar(
                select(func.count()).select_from(Project).where(Project.name == name)
            )
            return int(count or 0)
    finally:
        await engine.dispose()


async def project_count(database_url: str, project_id: UUID) -> int:
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


async def task_count(database_url: str, project_id: UUID) -> int:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(Task)
                .where(Task.project_id == project_id)
            )
            return int(count or 0)
    finally:
        await engine.dispose()


async def run_create_project(
    database_url: str,
    *,
    owner: User,
    workspace_id: UUID,
) -> None:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            service = ProjectService(
                ProjectRepository(session),
                WorkspaceRepository(session),
                session,
            )
            await service.create_project(
                owner,
                workspace_id,
                ProjectCreate(name="Atomic Rollback Project"),
            )
    finally:
        await engine.dispose()


async def run_delete_project(
    database_url: str,
    *,
    owner: User,
    project_id: UUID,
) -> ProjectHasChildrenError | None:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            service = ProjectService(
                ProjectRepository(session),
                WorkspaceRepository(session),
                session,
            )
            try:
                await service.delete_project(owner, project_id)
            except ProjectHasChildrenError as exc:
                return exc
            return None
    finally:
        await engine.dispose()


async def insert_task_after_precheck(
    database_url: str,
    *,
    gate: DeletePrecheckGate,
    project_id: UUID,
    owner_id: UUID,
) -> None:
    await asyncio.wait_for(gate.precheck_complete.wait(), timeout=5)
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            session.add(
                Task(
                    project_id=project_id,
                    assignee_id=None,
                    title="Concurrent Child Task",
                    description=None,
                    status=TaskStatus.TODO,
                    priority=TaskPriority.MEDIUM,
                    due_date=None,
                    created_by=owner_id,
                )
            )
            await session.commit()
    finally:
        await engine.dispose()
        gate.child_inserted.set()


def constraint_name_from_integrity_error(exc: IntegrityError) -> str | None:
    original = getattr(exc, "orig", None)
    for candidate in (
        original,
        getattr(original, "__cause__", None),
        getattr(original, "__context__", None),
    ):
        constraint_name = getattr(candidate, "constraint_name", None)
        if isinstance(constraint_name, str):
            return constraint_name

        diagnostic = getattr(candidate, "diag", None)
        diagnostic_constraint_name = getattr(diagnostic, "constraint_name", None)
        if isinstance(diagnostic_constraint_name, str):
            return diagnostic_constraint_name

    return None


def test_create_project_rolls_back_after_real_insert_flush_failure(
    test_database_url: str,
    clean_test_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run_test() -> None:
        owner, workspace_id = await create_workspace_context(test_database_url)
        inserted_project_id: UUID | None = None
        original_create = ProjectRepository.create

        async def fail_create(
            self: ProjectRepository,
            project: Project,
        ) -> Project:
            nonlocal inserted_project_id
            created_project = await original_create(self, project)
            inserted_project_id = created_project.id
            assert await self.get_by_id(created_project.id) is not None
            raise ProjectCreateFailure

        monkeypatch.setattr(ProjectRepository, "create", fail_create)

        with pytest.raises(ProjectCreateFailure):
            await run_create_project(
                test_database_url,
                owner=owner,
                workspace_id=workspace_id,
            )

        assert inserted_project_id is not None
        assert (
            await project_count_by_name(test_database_url, "Atomic Rollback Project")
            == 0
        )
        assert await project_count(test_database_url, inserted_project_id) == 0

    asyncio.run(run_test())


def test_concurrent_child_insert_during_delete_uses_postgresql_fk_metadata(
    test_database_url: str,
    clean_test_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run_test() -> None:
        context = await insert_project_context(test_database_url, archived=True)
        gate = DeletePrecheckGate()
        original_has_tasks = ProjectRepository.has_tasks

        async def gated_has_tasks(
            self: ProjectRepository,
            project_id: UUID,
        ) -> bool:
            has_tasks = await original_has_tasks(self, project_id)
            if project_id == context.project_id:
                assert has_tasks is False
                await gate.wait_for_child_insert()
            return has_tasks

        monkeypatch.setattr(ProjectRepository, "has_tasks", gated_has_tasks)

        child_conflict, _ = await asyncio.gather(
            run_delete_project(
                test_database_url,
                owner=context.owner,
                project_id=context.project_id,
            ),
            insert_task_after_precheck(
                test_database_url,
                gate=gate,
                project_id=context.project_id,
                owner_id=context.owner.id,
            ),
        )

        assert child_conflict is not None
        assert isinstance(child_conflict.__cause__, IntegrityError)
        assert (
            constraint_name_from_integrity_error(child_conflict.__cause__)
            == "fk_tasks_project_id_projects"
        )
        assert await project_count(test_database_url, context.project_id) == 1
        assert await task_count(test_database_url, context.project_id) == 1

    asyncio.run(run_test())
