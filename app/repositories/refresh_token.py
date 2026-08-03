from typing import cast
from uuid import UUID

from sqlalchemy import select
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
