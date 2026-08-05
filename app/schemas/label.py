from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

LabelName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
LabelColor = Annotated[
    str,
    StringConstraints(pattern=r"^#[0-9A-F]{6}$"),
]


class LabelCreate(BaseModel):
    """Request body for creating a project label."""

    name: LabelName
    color: LabelColor

    model_config = ConfigDict(extra="forbid")


class LabelUpdate(BaseModel):
    """Request body for partially updating a label."""

    name: LabelName | None = None
    color: LabelColor | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("name", "color", mode="before")
    @classmethod
    def reject_null_fields(cls, value: object) -> object:
        if value is None:
            raise ValueError("Field cannot be null.")
        return value


class LabelRead(BaseModel):
    """Response body for a label."""

    id: UUID
    project_id: UUID
    name: str
    color: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
