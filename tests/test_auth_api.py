import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.security import (
    create_refresh_token,
    refresh_token_digest,
    verify_password,
)
from app.main import create_app
from app.models.enums import UserRole
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.repositories.refresh_token import RefreshTokenRepository

TEST_JWT_SECRET_KEY = "test-secret-key-with-at-least-32-characters"
AUTH_USER_FIELDS = {"id", "email", "full_name", "role", "is_active", "created_at"}
TOKEN_FIELDS = {"access_token", "refresh_token", "token_type", "expires_in"}


@dataclass(frozen=True)
class UserSnapshot:
    id: UUID
    email: str
    full_name: str
    hashed_password: str
    role: UserRole
    is_active: bool


@dataclass(frozen=True)
class RefreshTokenSnapshot:
    id: UUID
    user_id: UUID
    token_hash: str
    expires_at: datetime
    revoked_at: datetime | None


class RefreshCreateFailure(Exception):
    """Raised by tests to exercise transaction rollback."""


def register_user(
    client: TestClient,
    *,
    email: str = "Auth.User@example.com",
    password: str = "ValidPass123!",
    full_name: str = "Auth User",
) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "full_name": full_name, "password": password},
    )
    assert response.status_code == 201
    return response.json()


def login_user(
    client: TestClient,
    *,
    email: str = "auth.user@example.com",
    password: str = "ValidPass123!",
) -> dict[str, str | int]:
    response = client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},
    )
    assert response.status_code == 200
    return response.json()


def assert_bearer_401(response: object, detail: str) -> None:
    assert response.status_code == 401
    assert response.json() == {"detail": detail}
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def get_user_by_email(database_url: str, email: str) -> UserSnapshot:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            user = await session.scalar(select(User).where(User.email == email))
            assert user is not None
            return UserSnapshot(
                id=user.id,
                email=user.email,
                full_name=user.full_name,
                hashed_password=user.hashed_password,
                role=user.role,
                is_active=user.is_active,
            )
    finally:
        await engine.dispose()


async def set_user_active(database_url: str, user_id: UUID, is_active: bool) -> None:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            await session.execute(
                update(User).where(User.id == user_id).values(is_active=is_active)
            )
            await session.commit()
    finally:
        await engine.dispose()


async def get_refresh_token(
    database_url: str,
    token_id: UUID,
) -> RefreshTokenSnapshot:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            token = await session.get(RefreshToken, token_id)
            assert token is not None
            return RefreshTokenSnapshot(
                id=token.id,
                user_id=token.user_id,
                token_hash=token.token_hash,
                expires_at=token.expires_at,
                revoked_at=token.revoked_at,
            )
    finally:
        await engine.dispose()


async def count_refresh_tokens(database_url: str) -> int:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            count = await session.scalar(select(func.count()).select_from(RefreshToken))
            return int(count or 0)
    finally:
        await engine.dispose()


async def update_refresh_token_hash(
    database_url: str,
    token_id: UUID,
    token_hash: str,
) -> None:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            await session.execute(
                update(RefreshToken)
                .where(RefreshToken.id == token_id)
                .values(token_hash=token_hash)
            )
            await session.commit()
    finally:
        await engine.dispose()


async def insert_refresh_token(
    database_url: str,
    *,
    token_id: UUID,
    user_id: UUID,
    token_hash: str,
    expires_at: datetime,
    revoked_at: datetime | None = None,
) -> None:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            session.add(
                RefreshToken(
                    id=token_id,
                    user_id=user_id,
                    token_hash=token_hash,
                    expires_at=expires_at,
                    revoked_at=revoked_at,
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


def decode_claims(token: str) -> dict[str, object]:
    return jwt.decode(token, TEST_JWT_SECRET_KEY, algorithms=["HS256"])


def test_register_normalizes_email_and_stores_password_hash(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    body = register_user(
        task_client,
        email="  Mixed.Email@Example.COM  ",
        full_name="  Mixed User  ",
    )

    assert set(body) == AUTH_USER_FIELDS
    assert UUID(str(body["id"])).version == 4
    assert body["email"] == "mixed.email@example.com"
    assert body["full_name"] == "Mixed User"
    assert body["role"] == "MEMBER"
    assert body["is_active"] is True

    user = asyncio.run(get_user_by_email(test_database_url, "mixed.email@example.com"))
    assert user.full_name == "Mixed User"
    assert user.role is UserRole.MEMBER
    assert user.is_active is True
    assert user.hashed_password != "ValidPass123!"
    assert verify_password("ValidPass123!", user.hashed_password)


def test_register_rejects_duplicate_email_and_client_controlled_fields(
    task_client: TestClient,
) -> None:
    register_user(task_client, email="duplicate@example.com")

    duplicate_response = task_client.post(
        "/api/v1/auth/register",
        json={
            "email": "  DUPLICATE@example.com ",
            "full_name": "Duplicate User",
            "password": "ValidPass123!",
        },
    )
    role_response = task_client.post(
        "/api/v1/auth/register",
        json={
            "email": "role@example.com",
            "full_name": "Role User",
            "password": "ValidPass123!",
            "role": "ADMIN",
        },
    )
    active_response = task_client.post(
        "/api/v1/auth/register",
        json={
            "email": "active@example.com",
            "full_name": "Active User",
            "password": "ValidPass123!",
            "is_active": False,
        },
    )
    short_password_response = task_client.post(
        "/api/v1/auth/register",
        json={
            "email": "short@example.com",
            "full_name": "Short Password",
            "password": "short",
        },
    )

    assert duplicate_response.status_code == 409
    assert duplicate_response.json() == {"detail": "Email already registered"}
    assert role_response.status_code == 422
    assert active_response.status_code == 422
    assert short_password_response.status_code == 422


def test_login_uses_oauth2_form_and_invalid_credentials_share_response(
    task_client: TestClient,
) -> None:
    register_user(task_client)

    success = task_client.post(
        "/api/v1/auth/login",
        data={"username": "AUTH.USER@example.com", "password": "ValidPass123!"},
    )
    json_login = task_client.post(
        "/api/v1/auth/login",
        json={"username": "auth.user@example.com", "password": "ValidPass123!"},
    )
    wrong_password = task_client.post(
        "/api/v1/auth/login",
        data={"username": "auth.user@example.com", "password": "WrongPass123!"},
    )
    unknown_email = task_client.post(
        "/api/v1/auth/login",
        data={"username": "missing@example.com", "password": "WrongPass123!"},
    )

    assert success.status_code == 200
    assert set(success.json()) == TOKEN_FIELDS
    assert success.json()["token_type"] == "bearer"
    assert success.json()["expires_in"] == 900
    assert json_login.status_code == 422
    assert_bearer_401(wrong_password, "Incorrect email or password")
    assert_bearer_401(unknown_email, "Incorrect email or password")
    assert wrong_password.json() == unknown_email.json()


def test_login_rejects_inactive_user(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    register_user(task_client)
    user = asyncio.run(get_user_by_email(test_database_url, "auth.user@example.com"))
    asyncio.run(set_user_active(test_database_url, user.id, False))

    response = task_client.post(
        "/api/v1/auth/login",
        data={"username": "auth.user@example.com", "password": "ValidPass123!"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Inactive user"}


def test_login_token_claims_lifetimes_and_persisted_digest(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    register_user(task_client)

    body = login_user(task_client)
    access_claims = decode_claims(str(body["access_token"]))
    refresh_claims = decode_claims(str(body["refresh_token"]))
    refresh_token_id = UUID(str(refresh_claims["jti"]))
    persisted = asyncio.run(get_refresh_token(test_database_url, refresh_token_id))

    assert access_claims["type"] == "access"
    assert refresh_claims["type"] == "refresh"
    assert UUID(str(access_claims["sub"])) == persisted.user_id
    assert UUID(str(refresh_claims["sub"])) == persisted.user_id
    assert int(access_claims["exp"]) - int(access_claims["iat"]) == 900
    assert int(refresh_claims["exp"]) - int(refresh_claims["iat"]) == 7 * 24 * 60 * 60
    assert persisted.token_hash != body["refresh_token"]
    assert persisted.token_hash == refresh_token_digest(
        str(body["refresh_token"]),
        secret_key=TEST_JWT_SECRET_KEY,
    )
    assert persisted.revoked_at is None


def test_refresh_rotates_rejects_old_and_accepts_replacement(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    register_user(task_client)
    initial_tokens = login_user(task_client)

    first_rotation = task_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": initial_tokens["refresh_token"]},
    )
    old_reuse = task_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": initial_tokens["refresh_token"]},
    )
    second_rotation = task_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": first_rotation.json()["refresh_token"]},
    )

    assert first_rotation.status_code == 200
    assert_bearer_401(old_reuse, "Invalid refresh token")
    assert second_rotation.status_code == 200
    assert asyncio.run(count_refresh_tokens(test_database_url)) == 3


def test_refresh_rejects_invalid_token_variants(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    register_user(task_client)
    tokens = login_user(task_client)
    user = asyncio.run(get_user_by_email(test_database_url, "auth.user@example.com"))

    access_token = str(tokens["access_token"])
    unknown_refresh, _, _ = create_refresh_token(
        user_id=user.id,
        token_id=uuid4(),
        secret_key=TEST_JWT_SECRET_KEY,
        algorithm="HS256",
        now=datetime.now(UTC) - timedelta(seconds=1),
    )
    unknown_refresh_claims = decode_claims(unknown_refresh)
    assert unknown_refresh_claims["type"] == "refresh"
    assert datetime.fromtimestamp(int(unknown_refresh_claims["exp"]), UTC) > (
        datetime.now(UTC)
    )
    forged_refresh, _, _ = create_refresh_token(
        user_id=user.id,
        token_id=uuid4(),
        secret_key="wrong-secret-key-with-at-least-32-chars",
        algorithm="HS256",
        now=datetime.now(UTC) - timedelta(seconds=1),
    )
    expired_refresh, expired_id, expired_at = create_refresh_token(
        user_id=user.id,
        token_id=uuid4(),
        secret_key=TEST_JWT_SECRET_KEY,
        algorithm="HS256",
        now=datetime.now(UTC) - timedelta(days=8),
    )
    asyncio.run(
        insert_refresh_token(
            test_database_url,
            token_id=expired_id,
            user_id=user.id,
            token_hash=refresh_token_digest(
                expired_refresh,
                secret_key=TEST_JWT_SECRET_KEY,
            ),
            expires_at=expired_at,
        )
    )

    digest_mismatch_tokens = login_user(task_client)
    mismatch_claims = decode_claims(str(digest_mismatch_tokens["refresh_token"]))
    mismatch_id = UUID(str(mismatch_claims["jti"]))
    asyncio.run(
        update_refresh_token_hash(
            test_database_url,
            mismatch_id,
            refresh_token_digest("different-token", secret_key=TEST_JWT_SECRET_KEY),
        )
    )

    revoked_tokens = login_user(task_client)
    logout_response = task_client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": revoked_tokens["refresh_token"]},
    )

    invalid_tokens = [
        "not-a-token",
        forged_refresh,
        access_token,
        unknown_refresh,
        expired_refresh,
        str(digest_mismatch_tokens["refresh_token"]),
        str(revoked_tokens["refresh_token"]),
    ]
    responses = [
        task_client.post("/api/v1/auth/refresh", json={"refresh_token": token})
        for token in invalid_tokens
    ]

    assert logout_response.status_code == 204
    for response in responses:
        assert_bearer_401(response, "Invalid refresh token")


def test_refresh_inactive_user_returns_403_and_logout_still_revokes(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    register_user(task_client)
    tokens = login_user(task_client)
    user = asyncio.run(get_user_by_email(test_database_url, "auth.user@example.com"))
    asyncio.run(set_user_active(test_database_url, user.id, False))

    refresh_response = task_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    logout_response = task_client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
    )
    refresh_after_logout = task_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )

    assert refresh_response.status_code == 403
    assert refresh_response.json() == {"detail": "Inactive user"}
    assert logout_response.status_code == 204
    assert logout_response.content == b""
    assert_bearer_401(refresh_after_logout, "Invalid refresh token")


def test_logout_returns_empty_204_and_prevents_refresh(
    task_client: TestClient,
) -> None:
    register_user(task_client)
    tokens = login_user(task_client)

    logout_response = task_client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
    )
    refresh_response = task_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )

    assert logout_response.status_code == 204
    assert logout_response.content == b""
    assert_bearer_401(refresh_response, "Invalid refresh token")


def test_concurrent_refresh_allows_at_most_one_success(
    task_client: TestClient,
) -> None:
    register_user(task_client)
    tokens = login_user(task_client)

    def rotate_once() -> int:
        with TestClient(create_app()) as client:
            response = client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": tokens["refresh_token"]},
            )
            return response.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(lambda _: rotate_once(), range(2)))

    assert statuses.count(200) == 1
    assert statuses.count(401) == 1


def test_refresh_failure_rolls_back_without_partial_state(
    task_client: TestClient,
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register_user(task_client)
    tokens = login_user(task_client)
    refresh_claims = decode_claims(str(tokens["refresh_token"]))
    refresh_token_id = UUID(str(refresh_claims["jti"]))

    async def fail_create(
        self: RefreshTokenRepository,
        entity: RefreshToken,
    ) -> RefreshToken:
        raise RefreshCreateFailure("replacement refresh insert failed")

    monkeypatch.setattr(RefreshTokenRepository, "create", fail_create)

    with pytest.raises(RefreshCreateFailure):
        task_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )

    original = asyncio.run(get_refresh_token(test_database_url, refresh_token_id))
    assert original.revoked_at is None
    assert asyncio.run(count_refresh_tokens(test_database_url)) == 1


def test_get_current_user_accepts_access_tokens_only(
    task_client: TestClient,
) -> None:
    register_user(task_client)
    tokens = login_user(task_client)
    access_response = task_client.post(
        "/api/v1/projects/00000000-0000-4000-8000-000000000001/tasks",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={"title": "Protected route checks auth first"},
    )
    refresh_response = task_client.post(
        "/api/v1/projects/00000000-0000-4000-8000-000000000001/tasks",
        headers={"Authorization": f"Bearer {tokens['refresh_token']}"},
        json={"title": "Refresh token is not access"},
    )

    assert access_response.status_code == 404
    assert_bearer_401(refresh_response, "Could not validate credentials")


def test_inactive_user_cannot_resolve_current_user(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    register_user(task_client)
    tokens = login_user(task_client)
    user = asyncio.run(get_user_by_email(test_database_url, "auth.user@example.com"))
    asyncio.run(set_user_active(test_database_url, user.id, False))

    response = task_client.post(
        "/api/v1/projects/00000000-0000-4000-8000-000000000001/tasks",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={"title": "Inactive current user"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Inactive user"}
