from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.models.enums import TaskPriority, TaskStatus

TaskTitle = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]


def _normalize_due_date(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("due_date must include timezone information.")
    return value.astimezone(UTC)


class TaskCreate(BaseModel):
    """Request body for creating a task."""

    title: TaskTitle
    description: str | None = Field(default=None, max_length=1000)
    assignee_id: UUID | None = None
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.MEDIUM
    due_date: datetime | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("due_date")
    @classmethod
    def normalize_due_date(cls, value: datetime | None) -> datetime | None:
        return _normalize_due_date(value)


class TaskUpdate(BaseModel):
    """Request body for partial task updates."""

    title: TaskTitle | None = None
    description: str | None = Field(default=None, max_length=1000)
    assignee_id: UUID | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    due_date: datetime | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("title", "status", "priority", mode="before")
    @classmethod
    def reject_non_nullable_nulls(cls, value: object) -> object:
        if value is None:
            raise ValueError("Field cannot be null.")
        return value

    @field_validator("due_date")
    @classmethod
    def normalize_due_date(cls, value: datetime | None) -> datetime | None:
        return _normalize_due_date(value)


class TaskRead(BaseModel):
    """Response body for a task."""

    id: UUID
    project_id: UUID
    assignee_id: UUID | None = None
    title: str
    description: str | None = None
    status: TaskStatus
    priority: TaskPriority
    due_date: datetime | None = None
    created_by: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
