import asyncio
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.core.security import verify_password
from tests.test_auth_api import (
    AUTH_USER_FIELDS,
    assert_bearer_401,
    decode_claims,
    get_refresh_token,
    get_user_by_email,
    login_user,
    register_user,
    set_user_active,
)


def auth_headers(
    client: TestClient,
    *,
    email: str = "auth.user@example.com",
    password: str = "ValidPass123!",
) -> dict[str, str]:
    tokens = login_user(client, email=email, password=password)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_get_me_returns_authenticated_public_profile(
    task_client: TestClient,
) -> None:
    registered = register_user(
        task_client,
        email="profile@example.com",
        full_name="Profile User",
    )
    headers = auth_headers(task_client, email="profile@example.com")

    response = task_client.get("/api/v1/users/me", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == AUTH_USER_FIELDS
    assert body == registered
    assert "hashed_password" not in body
    assert "password" not in body
    assert "refresh_token" not in body
    assert "token_hash" not in body


def test_get_me_rejects_missing_invalid_and_inactive_credentials(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    register_user(task_client)
    valid_headers = auth_headers(task_client)
    user = asyncio.run(get_user_by_email(test_database_url, "auth.user@example.com"))

    missing_response = task_client.get("/api/v1/users/me")
    invalid_response = task_client.get(
        "/api/v1/users/me",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    asyncio.run(set_user_active(test_database_url, user.id, False))
    inactive_response = task_client.get("/api/v1/users/me", headers=valid_headers)

    assert_bearer_401(missing_response, "Could not validate credentials")
    assert_bearer_401(invalid_response, "Could not validate credentials")
    assert inactive_response.status_code == 403
    assert inactive_response.json() == {"detail": "Inactive user"}


def test_patch_me_updates_trimmed_full_name_and_persists_to_later_get(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    register_user(task_client, email="patch@example.com", full_name="Original Name")
    headers = auth_headers(task_client, email="patch@example.com")

    patch_response = task_client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"full_name": "  Updated Name  "},
    )
    get_response = task_client.get("/api/v1/users/me", headers=headers)
    user = asyncio.run(get_user_by_email(test_database_url, "patch@example.com"))

    assert patch_response.status_code == 200
    assert patch_response.json()["full_name"] == "Updated Name"
    assert patch_response.json()["email"] == "patch@example.com"
    assert get_response.status_code == 200
    assert get_response.json()["full_name"] == "Updated Name"
    assert user.full_name == "Updated Name"


def test_patch_me_rejects_empty_body_without_changing_profile(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    register_user(task_client, email="empty-patch@example.com", full_name="Keep Name")
    headers = auth_headers(task_client, email="empty-patch@example.com")

    response = task_client.patch("/api/v1/users/me", headers=headers, json={})
    after = asyncio.run(get_user_by_email(test_database_url, "empty-patch@example.com"))

    assert response.status_code == 400
    assert response.json() == {"detail": "No profile changes provided"}
    assert after.full_name == "Keep Name"


@pytest.mark.parametrize(
    "payload",
    [
        {"full_name": None},
        {"full_name": ""},
        {"full_name": "   "},
        {"full_name": "A" * 256},
        {"id": "00000000-0000-4000-8000-000000000001"},
        {"email": "new@example.com"},
        {"role": "ADMIN"},
        {"is_active": False},
        {"created_at": "2026-08-03T00:00:00Z"},
        {"hashed_password": "hash"},
        {"unknown": "value"},
    ],
)
def test_patch_me_rejects_invalid_read_only_and_unknown_fields(
    task_client: TestClient,
    test_database_url: str,
    payload: dict[str, object],
) -> None:
    register_user(task_client, email="invalid-patch@example.com", full_name="Keep Name")
    headers = auth_headers(task_client, email="invalid-patch@example.com")

    response = task_client.patch("/api/v1/users/me", headers=headers, json=payload)
    after = asyncio.run(
        get_user_by_email(test_database_url, "invalid-patch@example.com")
    )

    assert response.status_code == 422
    assert after.full_name == "Keep Name"


def test_change_password_updates_hash_revokes_existing_refresh_and_allows_new_login(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    register_user(task_client, email="password@example.com")
    initial_tokens = login_user(task_client, email="password@example.com")
    refresh_claims = decode_claims(str(initial_tokens["refresh_token"]))
    refresh_token_id = UUID(str(refresh_claims["jti"]))
    before = asyncio.run(get_user_by_email(test_database_url, "password@example.com"))

    response = task_client.post(
        "/api/v1/users/me/password",
        headers={"Authorization": f"Bearer {initial_tokens['access_token']}"},
        json={
            "current_password": "ValidPass123!",
            "new_password": "NewValidPass123!",
        },
    )
    after = asyncio.run(get_user_by_email(test_database_url, "password@example.com"))
    revoked_refresh = asyncio.run(
        get_refresh_token(test_database_url, refresh_token_id)
    )
    old_login_response = task_client.post(
        "/api/v1/auth/login",
        data={"username": "password@example.com", "password": "ValidPass123!"},
    )
    new_login = login_user(
        task_client,
        email="password@example.com",
        password="NewValidPass123!",
    )
    old_refresh_response = task_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": initial_tokens["refresh_token"]},
    )
    new_refresh_response = task_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": new_login["refresh_token"]},
    )

    assert response.status_code == 204
    assert response.content == b""
    assert before.hashed_password != after.hashed_password
    assert after.hashed_password != "NewValidPass123!"
    assert verify_password("NewValidPass123!", after.hashed_password)
    assert revoked_refresh.revoked_at is not None
    assert_bearer_401(old_login_response, "Incorrect email or password")
    assert old_refresh_response.status_code == 401
    assert old_refresh_response.json() == {"detail": "Invalid refresh token"}
    assert new_refresh_response.status_code == 200
    assert "hashed_password" not in new_login
    assert "password" not in new_login


def test_change_password_rejects_incorrect_current_password_without_changes(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    register_user(task_client, email="wrong-current@example.com")
    tokens = login_user(task_client, email="wrong-current@example.com")
    before = asyncio.run(
        get_user_by_email(test_database_url, "wrong-current@example.com")
    )

    response = task_client.post(
        "/api/v1/users/me/password",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={
            "current_password": "WrongPass123!",
            "new_password": "NewValidPass123!",
        },
    )
    after = asyncio.run(
        get_user_by_email(test_database_url, "wrong-current@example.com")
    )
    old_login = login_user(task_client, email="wrong-current@example.com")

    assert response.status_code == 400
    assert response.json() == {"detail": "Incorrect current password"}
    assert after.hashed_password == before.hashed_password
    assert old_login["token_type"] == "bearer"


def test_change_password_rejects_same_password_without_changes(
    task_client: TestClient,
    test_database_url: str,
) -> None:
    register_user(task_client, email="same-password@example.com")
    tokens = login_user(task_client, email="same-password@example.com")
    before = asyncio.run(
        get_user_by_email(test_database_url, "same-password@example.com")
    )

    response = task_client.post(
        "/api/v1/users/me/password",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={
            "current_password": "ValidPass123!",
            "new_password": "ValidPass123!",
        },
    )
    after = asyncio.run(
        get_user_by_email(test_database_url, "same-password@example.com")
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "New password must be different from current password"
    }
    assert after.hashed_password == before.hashed_password


@pytest.mark.parametrize(
    "payload",
    [
        {"current_password": "short", "new_password": "NewValidPass123!"},
        {"current_password": "ValidPass123!", "new_password": "short"},
        {"current_password": "ValidPass123!", "new_password": "A" * 129},
        {
            "current_password": "ValidPass123!",
            "new_password": "NewValidPass123!",
            "unknown": "value",
        },
    ],
)
def test_change_password_rejects_invalid_request_bodies(
    task_client: TestClient,
    payload: dict[str, object],
) -> None:
    register_user(task_client, email="invalid-password-body@example.com")
    headers = auth_headers(task_client, email="invalid-password-body@example.com")

    response = task_client.post(
        "/api/v1/users/me/password",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 422
