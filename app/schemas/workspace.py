from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, StringConstraints, field_validator

from app.core.security import normalize_email
from app.models.enums import WorkspaceMemberRole

WORKSPACE_NAME_MAX_LENGTH = 255

WorkspaceName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=WORKSPACE_NAME_MAX_LENGTH,
    ),
]


class WorkspaceCreate(BaseModel):
    """Request body for creating a workspace."""

    name: WorkspaceName

    model_config = ConfigDict(extra="forbid")


class WorkspaceUpdate(BaseModel):
    """Request body for updating a workspace."""

    name: WorkspaceName | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("name", mode="before")
    @classmethod
    def reject_null_name(cls, value: object) -> object:
        if value is None:
            raise ValueError("name cannot be null.")
        return value


class WorkspaceRead(BaseModel):
    """Response body for a workspace."""

    id: UUID
    name: str
    owner_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WorkspaceMemberAdd(BaseModel):
    """Request body for adding an existing user to a workspace."""

    email: EmailStr
    role: WorkspaceMemberRole

    model_config = ConfigDict(extra="forbid")

    @field_validator("email", mode="before")
    @classmethod
    def strip_email(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return normalize_email(str(value))

    @field_validator("role")
    @classmethod
    def reject_owner_role(cls, value: WorkspaceMemberRole) -> WorkspaceMemberRole:
        if value is WorkspaceMemberRole.OWNER:
            raise ValueError("role must be EDITOR or VIEWER.")
        return value


class WorkspaceMemberRoleUpdate(BaseModel):
    """Request body for updating a workspace member role."""

    role: WorkspaceMemberRole

    model_config = ConfigDict(extra="forbid")

    @field_validator("role")
    @classmethod
    def reject_owner_role(cls, value: WorkspaceMemberRole) -> WorkspaceMemberRole:
        if value is WorkspaceMemberRole.OWNER:
            raise ValueError("role must be EDITOR or VIEWER.")
        return value


class WorkspaceMemberRead(BaseModel):
    """Response body for a workspace member."""

    workspace_id: UUID
    user_id: UUID
    email: str
    full_name: str
    role: WorkspaceMemberRole
    joined_at: datetime
