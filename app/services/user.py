from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, utc_now, verify_password
from app.models.user import User
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import UserRepository
from app.schemas.user import PasswordChangeRequest, UserProfileUpdate, UserRead


class NoProfileChangesError(Exception):
    """Raised when a profile PATCH request contains no editable changes."""


class IncorrectCurrentPasswordError(Exception):
    """Raised when the supplied current password is incorrect."""


class SamePasswordError(Exception):
    """Raised when the requested new password matches the current password."""


class UserService:
    """Coordinate current-user profile and password workflows."""

    def __init__(
        self,
        user_repository: UserRepository,
        refresh_token_repository: RefreshTokenRepository,
        session: AsyncSession,
    ) -> None:
        self._user_repository = user_repository
        self._refresh_token_repository = refresh_token_repository
        self._session = session

    async def update_profile(
        self,
        current_user: User,
        request: UserProfileUpdate,
    ) -> UserRead:
        if "full_name" not in request.model_fields_set:
            raise NoProfileChangesError

        assert request.full_name is not None
        current_user.full_name = request.full_name
        updated_user = await self._user_repository.update(current_user)
        await self._commit()
        return UserRead.model_validate(updated_user)

    async def change_password(
        self,
        current_user: User,
        request: PasswordChangeRequest,
    ) -> None:
        if not verify_password(request.current_password, current_user.hashed_password):
            raise IncorrectCurrentPasswordError

        if verify_password(request.new_password, current_user.hashed_password):
            raise SamePasswordError

        current_user.hashed_password = hash_password(request.new_password)
        await self._user_repository.update(current_user)
        await self._refresh_token_repository.revoke_active_for_user(
            current_user.id,
            utc_now(),
        )
        await self._commit()

    async def _commit(self) -> None:
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
