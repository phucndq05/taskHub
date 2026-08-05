import asyncio
from dataclasses import dataclass
from uuid import UUID

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.comment import Comment
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
from app.repositories.comment import CommentRepository
from app.repositories.workspace import WorkspaceRepository
from app.schemas.comment import CommentCreate
from app.services.comment import (
    CommentNotFoundError,
    CommentService,
    CommentTaskNotFoundError,
)


@dataclass(frozen=True)
class CommentServiceContext:
    owner: User
    project_id: UUID
    task_id: UUID


class FakeIntegrityOriginal:
    """Expose a constraint name like asyncpg's original error."""

    def __init__(self, constraint_name: str) -> None:
        self.constraint_name = constraint_name


async def insert_comment_context(database_url: str) -> CommentServiceContext:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            owner = User(
                email="comment-service-owner@example.com",
                full_name="Comment Service Owner",
                hashed_password="hashed-password",
                role=UserRole.MEMBER,
                is_active=True,
            )
            session.add(owner)
            await session.flush()

            workspace = Workspace(name="Comment Service Workspace", owner_id=owner.id)
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
                name="Comment Service Project",
                description=None,
                status=ProjectStatus.ACTIVE,
            )
            session.add(project)
            await session.flush()

            task = Task(
                project_id=project.id,
                assignee_id=None,
                title="Comment Service Task",
                description=None,
                status=TaskStatus.TODO,
                priority=TaskPriority.MEDIUM,
                due_date=None,
                created_by=owner.id,
            )
            session.add(task)
            await session.commit()

            return CommentServiceContext(
                owner=owner,
                project_id=project.id,
                task_id=task.id,
            )
    finally:
        await engine.dispose()


async def run_create_comment(
    database_url: str,
    *,
    owner: User,
    task_id: UUID,
    content: str = "Service comment",
) -> None:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            service = CommentService(
                CommentRepository(session),
                WorkspaceRepository(session),
                session,
            )
            await service.create_comment(owner, task_id, CommentCreate(content=content))
    finally:
        await engine.dispose()


async def run_delete_comment(
    database_url: str,
    *,
    owner: User,
    comment_id: UUID,
) -> None:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            service = CommentService(
                CommentRepository(session),
                WorkspaceRepository(session),
                session,
            )
            await service.delete_comment(owner, comment_id)
    finally:
        await engine.dispose()


async def insert_comment(
    database_url: str,
    *,
    task_id: UUID,
    author_id: UUID,
    content: str = "Inserted service comment",
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


async def delete_comment_directly(database_url: str, comment_id: UUID) -> None:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            await session.execute(delete(Comment).where(Comment.id == comment_id))
            await session.commit()
    finally:
        await engine.dispose()


async def comment_count(
    database_url: str,
    *,
    comment_id: UUID | None = None,
    task_id: UUID | None = None,
    content: str | None = None,
) -> int:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            statement = select(func.count()).select_from(Comment)
            if comment_id is not None:
                statement = statement.where(Comment.id == comment_id)
            if task_id is not None:
                statement = statement.where(Comment.task_id == task_id)
            if content is not None:
                statement = statement.where(Comment.content == content)
            count = await session.scalar(statement)
            return int(count or 0)
    finally:
        await engine.dispose()


async def task_count(database_url: str, task_id: UUID) -> int:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            count = await session.scalar(
                select(func.count()).select_from(Task).where(Task.id == task_id)
            )
            return int(count or 0)
    finally:
        await engine.dispose()


async def delete_task_directly(database_url: str, task_id: UUID) -> None:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            await session.execute(delete(Task).where(Task.id == task_id))
            await session.commit()
    finally:
        await engine.dispose()


def test_create_comment_rolls_back_when_task_fk_race_occurs(
    test_database_url: str,
    clean_test_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run_test() -> None:
        context = await insert_comment_context(test_database_url)
        original_create = CommentRepository.create

        async def delete_task_before_create(
            self: CommentRepository,
            comment: Comment,
        ) -> Comment:
            await self._session.execute(delete(Task).where(Task.id == comment.task_id))
            await self._session.flush()
            return await original_create(self, comment)

        monkeypatch.setattr(CommentRepository, "create", delete_task_before_create)

        with pytest.raises(CommentTaskNotFoundError):
            await run_create_comment(
                test_database_url,
                owner=context.owner,
                task_id=context.task_id,
                content="FK race comment",
            )

        assert await comment_count(test_database_url, content="FK race comment") == 0
        assert await task_count(test_database_url, context.task_id) == 1

    asyncio.run(run_test())


def test_unrelated_integrity_errors_are_not_converted_to_task_not_found(
    test_database_url: str,
    clean_test_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run_test() -> None:
        context = await insert_comment_context(test_database_url)

        async def fail_create_with_unrelated_integrity_error(
            self: CommentRepository,
            comment: Comment,
        ) -> Comment:
            raise IntegrityError("statement", {}, FakeIntegrityOriginal("other"))

        monkeypatch.setattr(
            CommentRepository,
            "create",
            fail_create_with_unrelated_integrity_error,
        )

        with pytest.raises(IntegrityError):
            await run_create_comment(
                test_database_url,
                owner=context.owner,
                task_id=context.task_id,
                content="Unrelated integrity",
            )

        assert (
            await comment_count(test_database_url, content="Unrelated integrity") == 0
        )

    asyncio.run(run_test())


def test_concurrent_delete_after_authorization_returns_not_found(
    test_database_url: str,
    clean_test_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run_test() -> None:
        context = await insert_comment_context(test_database_url)
        comment_id = await insert_comment(
            test_database_url,
            task_id=context.task_id,
            author_id=context.owner.id,
        )
        original_delete_by_id = CommentRepository.delete_by_id

        async def delete_elsewhere_before_delete_by_id(
            self: CommentRepository,
            target_comment_id: UUID,
        ) -> bool:
            await delete_comment_directly(test_database_url, target_comment_id)
            return await original_delete_by_id(self, target_comment_id)

        monkeypatch.setattr(
            CommentRepository,
            "delete_by_id",
            delete_elsewhere_before_delete_by_id,
        )

        with pytest.raises(CommentNotFoundError):
            await run_delete_comment(
                test_database_url,
                owner=context.owner,
                comment_id=comment_id,
            )

        assert await comment_count(test_database_url, comment_id=comment_id) == 0

    asyncio.run(run_test())


def test_task_deletion_cascades_comments(
    test_database_url: str,
    clean_test_database: None,
) -> None:
    async def run_test() -> None:
        context = await insert_comment_context(test_database_url)
        await insert_comment(
            test_database_url,
            task_id=context.task_id,
            author_id=context.owner.id,
        )

        await delete_task_directly(test_database_url, context.task_id)

        assert await comment_count(test_database_url, task_id=context.task_id) == 0

    asyncio.run(run_test())
