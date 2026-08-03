from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import UserRepository
from app.schemas.user import UserRegister
from app.services.auth import AuthService, DuplicateEmailError

TEST_JWT_SECRET_KEY = "test-secret-key-with-at-least-32-characters"


class RaceUserRepository:
    """Repository double that simulates a unique-email insert race."""

    async def get_by_email(self, email: str) -> None:
        return None

    async def create(self, entity: object) -> object:
        raise IntegrityError(
            "INSERT INTO users",
            {},
            Exception("duplicate key value violates unique constraint uq_users_email"),
        )


class UnusedRefreshTokenRepository:
    """Repository double unused by registration tests."""


@pytest.mark.asyncio
async def test_register_maps_unique_email_race_and_rolls_back() -> None:
    session = AsyncMock(spec=AsyncSession)
    service = AuthService(
        cast(UserRepository, RaceUserRepository()),
        cast(RefreshTokenRepository, UnusedRefreshTokenRepository()),
        cast(AsyncSession, session),
        jwt_secret_key=TEST_JWT_SECRET_KEY,
        jwt_algorithm="HS256",
    )
    request = UserRegister(
        email="race@example.com",
        full_name="Race User",
        password="ValidPass123!",
    )

    with pytest.raises(DuplicateEmailError):
        await service.register(request)

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
