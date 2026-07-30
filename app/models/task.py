from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import TaskPriority, TaskStatus, enum_values

if TYPE_CHECKING:
    from app.models.comment import Comment
    from app.models.project import Project
    from app.models.task_label import TaskLabel
    from app.models.user import User


class Task(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Persist a task within a project."""

    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_project_id_status", "project_id", "status"),
        Index("ix_tasks_project_id_priority", "project_id", "priority"),
        Index("ix_tasks_project_id_assignee_id", "project_id", "assignee_id"),
        Index("ix_tasks_project_id_created_at", "project_id", "created_at"),
    )

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
    )
    assignee_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(
            TaskStatus,
            name="task_status",
            native_enum=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    priority: Mapped[TaskPriority] = mapped_column(
        Enum(
            TaskPriority,
            name="task_priority",
            native_enum=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    due_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    project: Mapped[Project] = relationship(
        "Project",
        back_populates="tasks",
    )
    assignee: Mapped[User | None] = relationship(
        "User",
        back_populates="assigned_tasks",
        foreign_keys=[assignee_id],
    )
    creator: Mapped[User] = relationship(
        "User",
        back_populates="created_tasks",
        foreign_keys=[created_by],
    )
    task_label_associations: Mapped[list[TaskLabel]] = relationship(
        "TaskLabel",
        back_populates="task",
        passive_deletes=True,
    )
    comments: Mapped[list[Comment]] = relationship(
        "Comment",
        back_populates="task",
        passive_deletes=True,
    )
