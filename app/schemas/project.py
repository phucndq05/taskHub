from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.models.enums import ProjectStatus

PROJECT_NAME_MAX_LENGTH = 255
PROJECT_DESCRIPTION_MAX_LENGTH = 1000

ProjectName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=PROJECT_NAME_MAX_LENGTH,
    ),
]


class ProjectCreate(BaseModel):
    """Request body for creating a project."""

    name: ProjectName
    description: str | None = Field(
        default=None, max_length=PROJECT_DESCRIPTION_MAX_LENGTH
    )

    model_config = ConfigDict(extra="forbid")


class ProjectUpdate(BaseModel):
    """Request body for updating a project."""

    name: ProjectName | None = None
    description: str | None = Field(
        default=None, max_length=PROJECT_DESCRIPTION_MAX_LENGTH
    )

    model_config = ConfigDict(extra="forbid")

    @field_validator("name", mode="before")
    @classmethod
    def reject_null_name(cls, value: object) -> object:
        if value is None:
            raise ValueError("name cannot be null.")
        return value


class ProjectRead(BaseModel):
    """Response body for a project."""

    id: UUID
    workspace_id: UUID
    name: str
    description: str | None = None
    status: ProjectStatus
    created_by: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
