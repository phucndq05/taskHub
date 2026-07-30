from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, String, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import UserRole, enum_values

if TYPE_CHECKING:
    from app.models.comment import Comment
    from app.models.project import Project
    from app.models.refresh_token import RefreshToken
    from app.models.task import Task
    from app.models.workspace import Workspace
    from app.models.workspace_member import WorkspaceMember


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Persist an application user."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(
            UserRole,
            name="user_role",
            native_enum=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )

    owned_workspaces: Mapped[list[Workspace]] = relationship(
        "Workspace",
        back_populates="owner",
        foreign_keys="Workspace.owner_id",
    )
    memberships: Mapped[list[WorkspaceMember]] = relationship(
        "WorkspaceMember",
        back_populates="user",
        passive_deletes=True,
    )
    created_projects: Mapped[list[Project]] = relationship(
        "Project",
        back_populates="creator",
        foreign_keys="Project.created_by",
    )
    assigned_tasks: Mapped[list[Task]] = relationship(
        "Task",
        back_populates="assignee",
        foreign_keys="Task.assignee_id",
    )
    created_tasks: Mapped[list[Task]] = relationship(
        "Task",
        back_populates="creator",
        foreign_keys="Task.created_by",
    )
    comments: Mapped[list[Comment]] = relationship(
        "Comment",
        back_populates="author",
        foreign_keys="Comment.author_id",
    )
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        "RefreshToken",
        back_populates="user",
        passive_deletes=True,
    )
