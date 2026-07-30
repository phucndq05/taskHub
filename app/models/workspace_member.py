from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import utc_now
from app.models.enums import WorkspaceMemberRole, enum_values

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.workspace import Workspace


class WorkspaceMember(Base):
    """Persist a user's membership in a workspace."""

    __tablename__ = "workspace_members"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[WorkspaceMemberRole] = mapped_column(
        Enum(
            WorkspaceMemberRole,
            name="workspace_member_role",
            native_enum=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    workspace: Mapped[Workspace] = relationship(
        "Workspace",
        back_populates="memberships",
    )
    user: Mapped[User] = relationship(
        "User",
        back_populates="memberships",
    )


Index(
    "ix_workspace_members_one_owner_per_workspace",
    WorkspaceMember.workspace_id,
    unique=True,
    postgresql_where=WorkspaceMember.role == WorkspaceMemberRole.OWNER,
)
