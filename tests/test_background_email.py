import asyncio
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.dependencies import get_email_sender
from app.integrations.email import (
    AssignmentEmailPayload,
    EmailSender,
    build_assignment_email_message,
)
from app.models.task import Task
from app.models.user import User
from app.services.task import TaskService
from tests.test_tasks_api import (
    TaskApiContext,
    bearer_headers,
    count_tasks,
    insert_task,
    seed_task_context,
)


class CommitFailure(Exception):
    """Raised by tests to simulate a failed task transaction."""


@dataclass
class RecordingEmailSender:
    payloads: list[AssignmentEmailPayload] = field(default_factory=list)

    def send_assignment_email(self, payload: AssignmentEmailPayload) -> None:
        self.payloads.append(payload)


@dataclass
class FailingEmailSender:
    payloads: list[AssignmentEmailPayload] = field(default_factory=list)

    def send_assignment_email(self, payload: AssignmentEmailPayload) -> None:
        self.payloads.append(payload)
        raise RuntimeError("SMTP delivery failed")


@pytest.fixture
def task_api_context(
    test_database_url: str,
    clean_test_database: None,
) -> TaskApiContext:
    return asyncio.run(seed_task_context(test_database_url))


@pytest.fixture
def override_email_sender(
    task_client: TestClient,
) -> Generator[Callable[[EmailSender], None], None, None]:
    def override(sender: EmailSender) -> None:
        task_client.app.dependency_overrides[get_email_sender] = lambda: sender

    try:
        yield override
    finally:
        task_client.app.dependency_overrides.pop(get_email_sender, None)


async def get_user_email(database_url: str, user_id: UUID) -> str:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            email = await session.scalar(select(User.email).where(User.id == user_id))
            assert email is not None
            return email
    finally:
        await engine.dispose()


async def get_task_assignee_id(database_url: str, task_id: UUID) -> UUID | None:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            return await session.scalar(
                select(Task.assignee_id).where(Task.id == task_id)
            )
    finally:
        await engine.dispose()


def post_task(
    task_client: TestClient,
    task_api_context: TaskApiContext,
    payload: dict[str, object],
) -> dict[str, object]:
    response = task_client.post(
        f"/api/v1/projects/{task_api_context.project_id}/tasks",
        headers=bearer_headers(task_api_context.owner_id),
        json=payload,
    )
    assert response.status_code == 201
    return response.json()


def test_create_without_assignee_records_zero_sends(
    task_client: TestClient,
    task_api_context: TaskApiContext,
    override_email_sender: Callable[[EmailSender], None],
) -> None:
    sender = RecordingEmailSender()
    override_email_sender(sender)

    body = post_task(
        task_client,
        task_api_context,
        {"title": "No assignment email", "assignee_id": None},
    )

    assert body["assignee_id"] is None
    assert sender.payloads == []


def test_create_with_assignee_records_one_payload(
    task_client: TestClient,
    task_api_context: TaskApiContext,
    test_database_url: str,
    override_email_sender: Callable[[EmailSender], None],
) -> None:
    sender = RecordingEmailSender()
    override_email_sender(sender)
    expected_email = asyncio.run(
        get_user_email(test_database_url, task_api_context.assignee_id)
    )

    body = post_task(
        task_client,
        task_api_context,
        {
            "title": "Assigned create",
            "assignee_id": str(task_api_context.assignee_id),
        },
    )

    assert len(sender.payloads) == 1
    payload = sender.payloads[0]
    assert payload.recipient_email == expected_email
    assert payload.recipient_name == "Workspace Assignee"
    assert payload.task_id == body["id"]
    assert payload.task_title == "Assigned create"
    assert payload.project_name == "Task API"
    assert payload.assigner_name == "Workspace Owner"


def test_update_none_to_assignee_records_one_payload(
    task_client: TestClient,
    task_api_context: TaskApiContext,
    test_database_url: str,
    override_email_sender: Callable[[EmailSender], None],
) -> None:
    sender = RecordingEmailSender()
    override_email_sender(sender)
    task_id = asyncio.run(
        insert_task(
            test_database_url,
            project_id=task_api_context.project_id,
            actor_id=task_api_context.owner_id,
            title="Unassigned task",
            created_at=datetime.now(UTC),
        )
    )

    response = task_client.patch(
        f"/api/v1/tasks/{task_id}",
        headers=bearer_headers(task_api_context.owner_id),
        json={"assignee_id": str(task_api_context.assignee_id)},
    )

    assert response.status_code == 200
    assert response.json()["assignee_id"] == str(task_api_context.assignee_id)
    assert len(sender.payloads) == 1
    assert sender.payloads[0].task_id == str(task_id)
    assert sender.payloads[0].recipient_name == "Workspace Assignee"


def test_update_assignee_to_different_assignee_records_new_assignee_only(
    task_client: TestClient,
    task_api_context: TaskApiContext,
    test_database_url: str,
    override_email_sender: Callable[[EmailSender], None],
) -> None:
    sender = RecordingEmailSender()
    override_email_sender(sender)
    expected_email = asyncio.run(
        get_user_email(test_database_url, task_api_context.viewer_id)
    )
    task_id = asyncio.run(
        insert_task(
            test_database_url,
            project_id=task_api_context.project_id,
            actor_id=task_api_context.owner_id,
            title="Reassigned task",
            created_at=datetime.now(UTC),
            assignee_id=task_api_context.assignee_id,
        )
    )

    response = task_client.patch(
        f"/api/v1/tasks/{task_id}",
        headers=bearer_headers(task_api_context.owner_id),
        json={"assignee_id": str(task_api_context.viewer_id)},
    )

    assert response.status_code == 200
    assert response.json()["assignee_id"] == str(task_api_context.viewer_id)
    assert len(sender.payloads) == 1
    assert sender.payloads[0].recipient_email == expected_email
    assert sender.payloads[0].recipient_name == "Workspace Viewer"


def test_update_assignee_to_same_assignee_records_zero_sends(
    task_client: TestClient,
    task_api_context: TaskApiContext,
    test_database_url: str,
    override_email_sender: Callable[[EmailSender], None],
) -> None:
    sender = RecordingEmailSender()
    override_email_sender(sender)
    task_id = asyncio.run(
        insert_task(
            test_database_url,
            project_id=task_api_context.project_id,
            actor_id=task_api_context.owner_id,
            title="Same assignee task",
            created_at=datetime.now(UTC),
            assignee_id=task_api_context.assignee_id,
        )
    )

    response = task_client.patch(
        f"/api/v1/tasks/{task_id}",
        headers=bearer_headers(task_api_context.owner_id),
        json={"assignee_id": str(task_api_context.assignee_id)},
    )

    assert response.status_code == 200
    assert response.json()["assignee_id"] == str(task_api_context.assignee_id)
    assert sender.payloads == []


def test_update_unrelated_field_while_assigned_records_zero_sends(
    task_client: TestClient,
    task_api_context: TaskApiContext,
    test_database_url: str,
    override_email_sender: Callable[[EmailSender], None],
) -> None:
    sender = RecordingEmailSender()
    override_email_sender(sender)
    task_id = asyncio.run(
        insert_task(
            test_database_url,
            project_id=task_api_context.project_id,
            actor_id=task_api_context.owner_id,
            title="Original title",
            created_at=datetime.now(UTC),
            assignee_id=task_api_context.assignee_id,
        )
    )

    response = task_client.patch(
        f"/api/v1/tasks/{task_id}",
        headers=bearer_headers(task_api_context.owner_id),
        json={"title": "Updated title"},
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Updated title"
    assert response.json()["assignee_id"] == str(task_api_context.assignee_id)
    assert sender.payloads == []


def test_update_assignee_to_none_records_zero_sends(
    task_client: TestClient,
    task_api_context: TaskApiContext,
    test_database_url: str,
    override_email_sender: Callable[[EmailSender], None],
) -> None:
    sender = RecordingEmailSender()
    override_email_sender(sender)
    task_id = asyncio.run(
        insert_task(
            test_database_url,
            project_id=task_api_context.project_id,
            actor_id=task_api_context.owner_id,
            title="Clear assignee task",
            created_at=datetime.now(UTC),
            assignee_id=task_api_context.assignee_id,
        )
    )

    response = task_client.patch(
        f"/api/v1/tasks/{task_id}",
        headers=bearer_headers(task_api_context.owner_id),
        json={"assignee_id": None},
    )

    assert response.status_code == 200
    assert response.json()["assignee_id"] is None
    assert sender.payloads == []


def test_invalid_or_non_member_assignee_records_zero_sends(
    task_client: TestClient,
    task_api_context: TaskApiContext,
    override_email_sender: Callable[[EmailSender], None],
) -> None:
    sender = RecordingEmailSender()
    override_email_sender(sender)

    unknown_response = task_client.post(
        f"/api/v1/projects/{task_api_context.project_id}/tasks",
        headers=bearer_headers(task_api_context.owner_id),
        json={"title": "Unknown assignee", "assignee_id": str(uuid4())},
    )
    non_member_response = task_client.post(
        f"/api/v1/projects/{task_api_context.project_id}/tasks",
        headers=bearer_headers(task_api_context.owner_id),
        json={
            "title": "Non-member assignee",
            "assignee_id": str(task_api_context.non_member_id),
        },
    )

    assert unknown_response.status_code == 404
    assert non_member_response.status_code == 400
    assert sender.payloads == []


def test_unauthorized_write_records_zero_sends(
    task_client: TestClient,
    task_api_context: TaskApiContext,
    override_email_sender: Callable[[EmailSender], None],
) -> None:
    sender = RecordingEmailSender()
    override_email_sender(sender)

    response = task_client.post(
        f"/api/v1/projects/{task_api_context.project_id}/tasks",
        headers=bearer_headers(task_api_context.viewer_id),
        json={
            "title": "Viewer cannot assign",
            "assignee_id": str(task_api_context.assignee_id),
        },
    )

    assert response.status_code == 403
    assert sender.payloads == []


def test_simulated_commit_failure_records_zero_sends(
    task_client: TestClient,
    task_api_context: TaskApiContext,
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    override_email_sender: Callable[[EmailSender], None],
) -> None:
    sender = RecordingEmailSender()
    override_email_sender(sender)

    async def fail_commit(self: TaskService) -> None:
        raise CommitFailure

    monkeypatch.setattr(TaskService, "_commit", fail_commit)

    with pytest.raises(CommitFailure):
        task_client.post(
            f"/api/v1/projects/{task_api_context.project_id}/tasks",
            headers=bearer_headers(task_api_context.owner_id),
            json={
                "title": "Commit failure",
                "assignee_id": str(task_api_context.assignee_id),
            },
        )

    assert sender.payloads == []
    assert asyncio.run(count_tasks(test_database_url)) == 0


def test_failing_sender_does_not_change_successful_response_or_assignment(
    task_client: TestClient,
    task_api_context: TaskApiContext,
    test_database_url: str,
    override_email_sender: Callable[[EmailSender], None],
) -> None:
    sender = FailingEmailSender()
    override_email_sender(sender)

    response = task_client.post(
        f"/api/v1/projects/{task_api_context.project_id}/tasks",
        headers=bearer_headers(task_api_context.owner_id),
        json={
            "title": "Delivery can fail",
            "assignee_id": str(task_api_context.assignee_id),
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["assignee_id"] == str(task_api_context.assignee_id)
    assert len(sender.payloads) == 1
    assert (
        asyncio.run(get_task_assignee_id(test_database_url, UUID(body["id"])))
        == task_api_context.assignee_id
    )


def test_assignment_email_message_contains_expected_headers_and_body() -> None:
    payload = AssignmentEmailPayload(
        recipient_email="assignee@example.com",
        recipient_name="Workspace Assignee",
        task_id="task-123",
        task_title="Write notification tests",
        project_name="Task API",
        assigner_name="Workspace Owner",
    )

    message = build_assignment_email_message(
        payload,
        from_email="no-reply@example.com",
    )

    assert message["From"] == "TaskHub <no-reply@example.com>"
    assert message["To"] == "assignee@example.com"
    assert message["Subject"] == "Task assigned: Write notification tests"
    assert message.get_content() == (
        "Hello Workspace Assignee,\n\n"
        'Workspace Owner assigned you the task "Write notification tests" '
        'in project "Task API".\n\n'
        "Task ID: task-123\n"
    )
