from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, StringConstraints, field_validator

from app.core.security import normalize_email
from app.models.enums import UserRole

FULL_NAME_MAX_LENGTH = 255

FullName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=FULL_NAME_MAX_LENGTH
    ),
]

Password = Annotated[
    str,
    StringConstraints(min_length=8, max_length=128),
]


class UserRegister(BaseModel):
    """Request body for registering a user."""

    email: EmailStr
    full_name: FullName
    password: Password

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


class UserRead(BaseModel):
    """Response body for a user."""

    id: UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserProfileUpdate(BaseModel):
    """Request body for updating the current user's profile."""

    full_name: FullName | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("full_name", mode="before")
    @classmethod
    def reject_null_full_name(cls, value: object) -> object:
        if value is None:
            raise ValueError("full_name cannot be null.")
        return value


class PasswordChangeRequest(BaseModel):
    """Request body for changing the current user's password."""

    current_password: Password
    new_password: Password

    model_config = ConfigDict(extra="forbid")
