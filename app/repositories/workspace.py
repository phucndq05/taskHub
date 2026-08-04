from typing import cast
from uuid import UUID

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember
from app.repositories.base import BaseRepository


class WorkspaceRepository(BaseRepository[Workspace]):
    """Persist and load workspaces and memberships."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Workspace)

    async def list_all(self) -> list[Workspace]:
        statement = select(Workspace).order_by(
            Workspace.created_at.desc(),
            Workspace.id.desc(),
        )
        result = await self._session.scalars(statement)
        return list(result.all())

    async def list_for_member(self, user_id: UUID) -> list[Workspace]:
        statement = (
            select(Workspace)
            .join(WorkspaceMember)
            .where(WorkspaceMember.user_id == user_id)
            .order_by(Workspace.created_at.desc(), Workspace.id.desc())
        )
        result = await self._session.scalars(statement)
        return list(result.all())

    async def get_by_id(self, workspace_id: UUID) -> Workspace | None:
        return await self.get(workspace_id)

    async def create_member(self, member: WorkspaceMember) -> WorkspaceMember:
        self._session.add(member)
        await self._session.flush()
        await self._session.refresh(member)
        return member

    async def get_member(
        self,
        workspace_id: UUID,
        user_id: UUID,
    ) -> WorkspaceMember | None:
        statement = select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
        return cast(WorkspaceMember | None, await self._session.scalar(statement))

    async def list_members_with_users(
        self,
        workspace_id: UUID,
    ) -> list[tuple[WorkspaceMember, User]]:
        statement = (
            select(WorkspaceMember, User)
            .join(User, User.id == WorkspaceMember.user_id)
            .where(WorkspaceMember.workspace_id == workspace_id)
            .order_by(WorkspaceMember.joined_at.asc(), WorkspaceMember.user_id.asc())
        )
        result = await self._session.execute(statement)
        return [(member, user) for member, user in result.all()]

    async def get_member_with_user(
        self,
        workspace_id: UUID,
        user_id: UUID,
    ) -> tuple[WorkspaceMember, User] | None:
        statement = (
            select(WorkspaceMember, User)
            .join(User, User.id == WorkspaceMember.user_id)
            .where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )
        row = (await self._session.execute(statement)).one_or_none()
        if row is None:
            return None
        member, user = row
        return member, user

    async def update_member(self, member: WorkspaceMember) -> WorkspaceMember:
        await self._session.flush()
        await self._session.refresh(member)
        return member

    async def delete_member(self, member: WorkspaceMember) -> None:
        await self._session.delete(member)
        await self._session.flush()

    async def has_projects(self, workspace_id: UUID) -> bool:
        statement = select(exists().where(Project.workspace_id == workspace_id))
        return bool(await self._session.scalar(statement))

    async def delete_workspace_by_id(self, workspace_id: UUID) -> None:
        await self._session.execute(
            delete(Workspace).where(Workspace.id == workspace_id)
        )
        await self._session.flush()
