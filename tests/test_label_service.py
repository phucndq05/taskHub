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
from app.models.label import Label
from app.models.project import Project
from app.models.task import Task
from app.models.task_label import TaskLabel
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember
from app.repositories.label import LabelRepository
from app.repositories.workspace import WorkspaceRepository
from app.schemas.label import LabelCreate
from app.services.label import (
    DuplicateLabelNameError,
    LabelService,
    TaskLabelAlreadyExistsError,
)


class LabelCreateFailure(Exception):
    """Raised by tests to exercise label creation rollback."""


class TaskLabelCreateFailure(Exception):
    """Raised by tests to exercise task-label creation rollback."""


class DuplicatePrecheckGate:
    """Release concurrent calls only after each duplicate pre-check arrives."""

    def __init__(self, expected_count: int) -> None:
        self._expected_count = expected_count
        self._arrived = 0
        self._event = asyncio.Event()

    async def wait(self) -> None:
        self._arrived += 1
        if self._arrived == self._expected_count:
            self._event.set()
        await asyncio.wait_for(self._event.wait(), timeout=5)


@dataclass(frozen=True)
class LabelServiceContext:
    owner: User
    project_id: UUID
    task_id: UUID
    label_id: UUID


class FakeIntegrityOriginal:
    """Expose a non-label constraint name like asyncpg's original error."""

    constraint_name = "some_other_constraint"


async def insert_label_context(database_url: str) -> LabelServiceContext:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            owner = User(
                email="label-service-owner@example.com",
                full_name="Label Service Owner",
                hashed_password="hashed-password",
                role=UserRole.MEMBER,
                is_active=True,
            )
            session.add(owner)
            await session.flush()

            workspace = Workspace(name="Label Service Workspace", owner_id=owner.id)
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
                name="Label Service Project",
                description=None,
                status=ProjectStatus.ACTIVE,
            )
            session.add(project)
            await session.flush()

            task = Task(
                project_id=project.id,
                assignee_id=None,
                title="Label Service Task",
                description=None,
                status=TaskStatus.TODO,
                priority=TaskPriority.MEDIUM,
                due_date=None,
                created_by=owner.id,
            )
            label = Label(project_id=project.id, name="service", color="#3366FF")
            session.add_all([task, label])
            await session.commit()

            return LabelServiceContext(
                owner=owner,
                project_id=project.id,
                task_id=task.id,
                label_id=label.id,
            )
    finally:
        await engine.dispose()


async def run_create_label(
    database_url: str,
    *,
    owner: User,
    project_id: UUID,
    name: str = "Atomic Label",
) -> str:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            service = LabelService(
                LabelRepository(session),
                WorkspaceRepository(session),
                session,
            )
            try:
                await service.create_label(
                    owner,
                    project_id,
                    LabelCreate(name=name, color="#1122AA"),
                )
            except DuplicateLabelNameError:
                return "duplicate"
            return "success"
    finally:
        await engine.dispose()


async def run_attach_label(
    database_url: str,
    *,
    owner: User,
    task_id: UUID,
    label_id: UUID,
) -> str:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            service = LabelService(
                LabelRepository(session),
                WorkspaceRepository(session),
                session,
            )
            try:
                await service.attach_label(owner, task_id, label_id)
            except TaskLabelAlreadyExistsError:
                return "duplicate"
            return "success"
    finally:
        await engine.dispose()


async def label_count(
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


async def task_label_count(
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


def test_create_label_rolls_back_after_real_insert_flush_failure(
    test_database_url: str,
    clean_test_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run_test() -> None:
        context = await insert_label_context(test_database_url)
        inserted_label_id: UUID | None = None
        original_create = LabelRepository.create

        async def fail_create(
            self: LabelRepository,
            label: Label,
        ) -> Label:
            nonlocal inserted_label_id
            created_label = await original_create(self, label)
            inserted_label_id = created_label.id
            assert await self.get_by_id(created_label.id) is not None
            raise LabelCreateFailure

        monkeypatch.setattr(LabelRepository, "create", fail_create)

        with pytest.raises(LabelCreateFailure):
            await run_create_label(
                test_database_url,
                owner=context.owner,
                project_id=context.project_id,
                name="Rollback Label",
            )

        assert inserted_label_id is not None
        assert (
            await label_count(
                test_database_url,
                project_id=context.project_id,
                name="Rollback Label",
            )
            == 0
        )
        assert await label_count(test_database_url, name="service") == 1

    asyncio.run(run_test())


def test_attach_label_rolls_back_after_real_task_label_flush_failure(
    test_database_url: str,
    clean_test_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run_test() -> None:
        context = await insert_label_context(test_database_url)
        original_create_task_label = LabelRepository.create_task_label

        async def fail_create_task_label(
            self: LabelRepository,
            task_label: TaskLabel,
        ) -> TaskLabel:
            created_task_label = await original_create_task_label(self, task_label)
            assert (
                await self.get_task_label(
                    created_task_label.task_id,
                    created_task_label.label_id,
                )
                is not None
            )
            raise TaskLabelCreateFailure

        monkeypatch.setattr(
            LabelRepository,
            "create_task_label",
            fail_create_task_label,
        )

        with pytest.raises(TaskLabelCreateFailure):
            await run_attach_label(
                test_database_url,
                owner=context.owner,
                task_id=context.task_id,
                label_id=context.label_id,
            )

        assert (
            await task_label_count(
                test_database_url,
                task_id=context.task_id,
                label_id=context.label_id,
            )
            == 0
        )

    asyncio.run(run_test())


def test_concurrent_duplicate_label_name_uses_postgresql_unique_constraint(
    test_database_url: str,
    clean_test_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run_test() -> None:
        context = await insert_label_context(test_database_url)
        gate = DuplicatePrecheckGate(expected_count=2)
        original_get_by_project_and_name = LabelRepository.get_by_project_and_name

        async def gated_get_by_project_and_name(
            self: LabelRepository,
            project_id: UUID,
            name: str,
        ) -> Label | None:
            if project_id == context.project_id and name == "Race Label":
                assert (
                    await original_get_by_project_and_name(self, project_id, name)
                    is None
                )
                await gate.wait()
                return None
            return await original_get_by_project_and_name(self, project_id, name)

        monkeypatch.setattr(
            LabelRepository,
            "get_by_project_and_name",
            gated_get_by_project_and_name,
        )

        results = await asyncio.gather(
            run_create_label(
                test_database_url,
                owner=context.owner,
                project_id=context.project_id,
                name="Race Label",
            ),
            run_create_label(
                test_database_url,
                owner=context.owner,
                project_id=context.project_id,
                name="Race Label",
            ),
        )

        assert sorted(results) == ["duplicate", "success"]
        assert (
            await label_count(
                test_database_url,
                project_id=context.project_id,
                name="Race Label",
            )
            == 1
        )

    asyncio.run(run_test())


def test_concurrent_duplicate_attach_uses_postgresql_composite_pk(
    test_database_url: str,
    clean_test_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run_test() -> None:
        context = await insert_label_context(test_database_url)
        gate = DuplicatePrecheckGate(expected_count=2)
        original_get_task_label = LabelRepository.get_task_label

        async def gated_get_task_label(
            self: LabelRepository,
            task_id: UUID,
            label_id: UUID,
        ) -> TaskLabel | None:
            if task_id == context.task_id and label_id == context.label_id:
                assert await original_get_task_label(self, task_id, label_id) is None
                await gate.wait()
                return None
            return await original_get_task_label(self, task_id, label_id)

        monkeypatch.setattr(LabelRepository, "get_task_label", gated_get_task_label)

        results = await asyncio.gather(
            run_attach_label(
                test_database_url,
                owner=context.owner,
                task_id=context.task_id,
                label_id=context.label_id,
            ),
            run_attach_label(
                test_database_url,
                owner=context.owner,
                task_id=context.task_id,
                label_id=context.label_id,
            ),
        )

        assert sorted(results) == ["duplicate", "success"]
        assert (
            await task_label_count(
                test_database_url,
                task_id=context.task_id,
                label_id=context.label_id,
            )
            == 1
        )

    asyncio.run(run_test())


def test_unrelated_integrity_errors_are_not_converted_to_label_conflicts(
    test_database_url: str,
    clean_test_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run_test() -> None:
        context = await insert_label_context(test_database_url)

        async def fail_create_with_unrelated_integrity_error(
            self: LabelRepository,
            label: Label,
        ) -> Label:
            raise IntegrityError("statement", {}, FakeIntegrityOriginal())

        monkeypatch.setattr(
            LabelRepository,
            "create",
            fail_create_with_unrelated_integrity_error,
        )

        with pytest.raises(IntegrityError):
            await run_create_label(
                test_database_url,
                owner=context.owner,
                project_id=context.project_id,
                name="Unrelated Integrity",
            )

        assert (
            await label_count(
                test_database_url,
                project_id=context.project_id,
                name="Unrelated Integrity",
            )
            == 0
        )

    asyncio.run(run_test())


def test_unrelated_integrity_errors_are_not_converted_to_attach_conflicts(
    test_database_url: str,
    clean_test_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run_test() -> None:
        context = await insert_label_context(test_database_url)

        async def fail_attach_with_unrelated_integrity_error(
            self: LabelRepository,
            task_label: TaskLabel,
        ) -> TaskLabel:
            raise IntegrityError("statement", {}, FakeIntegrityOriginal())

        monkeypatch.setattr(
            LabelRepository,
            "create_task_label",
            fail_attach_with_unrelated_integrity_error,
        )

        with pytest.raises(IntegrityError):
            await run_attach_label(
                test_database_url,
                owner=context.owner,
                task_id=context.task_id,
                label_id=context.label_id,
            )

        assert (
            await task_label_count(
                test_database_url,
                task_id=context.task_id,
                label_id=context.label_id,
            )
            == 0
        )

    asyncio.run(run_test())
