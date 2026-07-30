from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.task_label import TaskLabel


class Label(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Persist a project-scoped task label."""

    __tablename__ = "labels"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False)

    project: Mapped[Project] = relationship(
        "Project",
        back_populates="labels",
    )
    task_label_associations: Mapped[list[TaskLabel]] = relationship(
        "TaskLabel",
        back_populates="label",
        passive_deletes=True,
    )
