from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

TaskTitle = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]


class TaskCreate(BaseModel):
    """Request body for creating a sample task."""

    title: TaskTitle
    description: str | None = Field(default=None, max_length=1000)

    model_config = ConfigDict(extra="forbid")


class TaskUpdate(BaseModel):
    """Request body for partial sample task updates."""

    title: TaskTitle | None = None
    description: str | None = Field(default=None, max_length=1000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("title", mode="before")
    @classmethod
    def reject_null_title(cls, value: object) -> object:
        if value is None:
            raise ValueError("Title cannot be null.")
        return value


class TaskRead(BaseModel):
    """Response body for a sample task."""

    id: UUID
    title: str
    description: str | None = None

    model_config = ConfigDict(from_attributes=True)
