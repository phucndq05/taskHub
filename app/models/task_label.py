from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.label import Label
    from app.models.task import Task


class TaskLabel(Base):
    """Persist a task-to-label association."""

    __tablename__ = "task_labels"

    task_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    label_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("labels.id", ondelete="CASCADE"),
        primary_key=True,
    )

    task: Mapped[Task] = relationship(
        "Task",
        back_populates="task_label_associations",
    )
    label: Mapped[Label] = relationship(
        "Label",
        back_populates="task_label_associations",
    )
