from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    ACCESS_TOKEN_EXPIRES_IN_SECONDS,
    TokenValidationError,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    digests_match,
    hash_password,
    normalize_email,
    refresh_token_digest,
    utc_now,
    verify_dummy_password,
    verify_password,
)
from app.models.enums import UserRole
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import UserRepository
from app.schemas.auth import TokenResponse
from app.schemas.user import UserRead, UserRegister


class DuplicateEmailError(Exception):
    """Raised when a normalized email is already registered."""


class InvalidCredentialsError(Exception):
    """Raised when login credentials are invalid."""


class InactiveUserError(Exception):
    """Raised when an inactive user attempts an active-only operation."""


class InvalidRefreshTokenError(Exception):
    """Raised when a refresh token cannot be used."""


class InvalidAccessTokenError(Exception):
    """Raised when an access token cannot resolve a current user."""


class AuthService:
    """Coordinate authentication business rules and transactions."""

    def __init__(
        self,
        user_repository: UserRepository,
        refresh_token_repository: RefreshTokenRepository,
        session: AsyncSession,
        *,
        jwt_secret_key: str,
        jwt_algorithm: str,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._user_repository = user_repository
        self._refresh_token_repository = refresh_token_repository
        self._session = session
        self._jwt_secret_key = jwt_secret_key
        self._jwt_algorithm = jwt_algorithm
        self._now = now

    async def register(self, request: UserRegister) -> UserRead:
        email = normalize_email(request.email)
        existing_user = await self._user_repository.get_by_email(email)
        if existing_user is not None:
            raise DuplicateEmailError

        user = User(
            email=email,
            full_name=request.full_name,
            hashed_password=hash_password(request.password),
            role=UserRole.MEMBER,
            is_active=True,
        )
        try:
            created_user = await self._user_repository.create(user)
            await self._commit()
        except IntegrityError as exc:
            await self._session.rollback()
            if _is_unique_email_violation(exc):
                raise DuplicateEmailError from exc
            raise

        return UserRead.model_validate(created_user)

    async def login(self, email: str, password: str) -> TokenResponse:
        normalized_email = normalize_email(email)
        user = await self._user_repository.get_by_email(normalized_email)
        if user is None:
            verify_dummy_password(password)
            raise InvalidCredentialsError

        if not verify_password(password, user.hashed_password):
            raise InvalidCredentialsError

        if not user.is_active:
            raise InactiveUserError

        access_token, refresh_token, refresh_token_id, refresh_expires_at = (
            self._issue_tokens(user.id)
        )
        refresh_token_model = RefreshToken(
            id=refresh_token_id,
            user_id=user.id,
            token_hash=refresh_token_digest(
                refresh_token,
                secret_key=self._jwt_secret_key,
            ),
            expires_at=refresh_expires_at,
        )
        await self._refresh_token_repository.create(refresh_token_model)
        await self._commit()
        return _token_response(access_token, refresh_token)

    async def refresh(self, raw_refresh_token: str) -> TokenResponse:
        user_id, token_id = self._decode_refresh(raw_refresh_token)
        refresh_token = await self._validate_refresh_row(
            raw_refresh_token,
            user_id=user_id,
            token_id=token_id,
        )
        user = await self._user_repository.get_by_id(user_id)
        if user is None:
            raise InvalidRefreshTokenError
        if not user.is_active:
            raise InactiveUserError

        now = self._now()
        refresh_token.revoked_at = now

        access_token, replacement_token, replacement_id, replacement_expires_at = (
            self._issue_tokens(user.id, now=now)
        )
        replacement_model = RefreshToken(
            id=replacement_id,
            user_id=user.id,
            token_hash=refresh_token_digest(
                replacement_token,
                secret_key=self._jwt_secret_key,
            ),
            expires_at=replacement_expires_at,
        )
        await self._refresh_token_repository.create(replacement_model)
        await self._commit()
        return _token_response(access_token, replacement_token)

    async def logout(self, raw_refresh_token: str) -> None:
        user_id, token_id = self._decode_refresh(raw_refresh_token)
        refresh_token = await self._validate_refresh_row(
            raw_refresh_token,
            user_id=user_id,
            token_id=token_id,
        )
        refresh_token.revoked_at = self._now()
        await self._session.flush()
        await self._commit()

    async def get_current_user(self, raw_access_token: str) -> User:
        try:
            user_id = decode_access_token(
                raw_access_token,
                secret_key=self._jwt_secret_key,
                algorithm=self._jwt_algorithm,
            )
        except TokenValidationError as exc:
            raise InvalidAccessTokenError from exc

        user = await self._user_repository.get_by_id(user_id)
        if user is None:
            raise InvalidAccessTokenError
        if not user.is_active:
            raise InactiveUserError
        return user

    async def _validate_refresh_row(
        self,
        raw_refresh_token: str,
        *,
        user_id: UUID,
        token_id: UUID,
    ) -> RefreshToken:
        refresh_token = await self._refresh_token_repository.get_for_update(token_id)
        if refresh_token is None:
            raise InvalidRefreshTokenError
        if refresh_token.user_id != user_id:
            raise InvalidRefreshTokenError
        if refresh_token.revoked_at is not None:
            raise InvalidRefreshTokenError
        if _as_utc(refresh_token.expires_at) <= self._now():
            raise InvalidRefreshTokenError

        actual_digest = refresh_token_digest(
            raw_refresh_token,
            secret_key=self._jwt_secret_key,
        )
        if not digests_match(actual_digest, refresh_token.token_hash):
            raise InvalidRefreshTokenError

        return refresh_token

    def _decode_refresh(self, raw_refresh_token: str) -> tuple[UUID, UUID]:
        try:
            return decode_refresh_token(
                raw_refresh_token,
                secret_key=self._jwt_secret_key,
                algorithm=self._jwt_algorithm,
            )
        except TokenValidationError as exc:
            raise InvalidRefreshTokenError from exc

    def _issue_tokens(
        self,
        user_id: UUID,
        *,
        now: datetime | None = None,
    ) -> tuple[str, str, UUID, datetime]:
        issued_at = now or self._now()
        access_token, _ = create_access_token(
            user_id=user_id,
            secret_key=self._jwt_secret_key,
            algorithm=self._jwt_algorithm,
            now=issued_at,
        )
        refresh_token, refresh_token_id, refresh_expires_at = create_refresh_token(
            user_id=user_id,
            token_id=uuid4(),
            secret_key=self._jwt_secret_key,
            algorithm=self._jwt_algorithm,
            now=issued_at,
        )
        return access_token, refresh_token, refresh_token_id, refresh_expires_at

    async def _commit(self) -> None:
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise


def _token_response(access_token: str, refresh_token: str) -> TokenResponse:
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRES_IN_SECONDS,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_unique_email_violation(exc: IntegrityError) -> bool:
    original = getattr(exc, "orig", None)
    constraint_name = getattr(original, "constraint_name", None)
    if constraint_name == "uq_users_email":
        return True

    diagnostic = getattr(original, "diag", None)
    if getattr(diagnostic, "constraint_name", None) == "uq_users_email":
        return True

    return "uq_users_email" in str(exc)
