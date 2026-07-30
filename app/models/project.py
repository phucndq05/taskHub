from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ProjectStatus, enum_values

if TYPE_CHECKING:
    from app.models.label import Label
    from app.models.task import Task
    from app.models.user import User
    from app.models.workspace import Workspace


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Persist a project within a workspace."""

    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_workspace_id_status", "workspace_id", "status"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(
            ProjectStatus,
            name="project_status",
            native_enum=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    workspace: Mapped[Workspace] = relationship(
        "Workspace",
        back_populates="projects",
    )
    creator: Mapped[User] = relationship(
        "User",
        back_populates="created_projects",
        foreign_keys=[created_by],
    )
    tasks: Mapped[list[Task]] = relationship(
        "Task",
        back_populates="project",
    )
    labels: Mapped[list[Label]] = relationship(
        "Label",
        back_populates="project",
    )
