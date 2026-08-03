from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refresh_token import RefreshToken
from app.repositories.base import BaseRepository


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    """Persist refresh-token revoke state."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, RefreshToken)

    async def get_for_update(self, token_id: UUID) -> RefreshToken | None:
        statement = (
            select(RefreshToken).where(RefreshToken.id == token_id).with_for_update()
        )
        return cast(RefreshToken | None, await self._session.scalar(statement))

    async def revoke_active_for_user(self, user_id: UUID, revoked_at: datetime) -> None:
        statement = (
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )
        await self._session.execute(statement)
