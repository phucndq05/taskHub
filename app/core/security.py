import hmac
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, cast
from uuid import UUID, uuid4

import jwt
from jwt import InvalidTokenError
from passlib.context import CryptContext  # type: ignore[import-untyped]

ACCESS_TOKEN_EXPIRE_MINUTES = 15
ACCESS_TOKEN_EXPIRES_IN_SECONDS = ACCESS_TOKEN_EXPIRE_MINUTES * 60
REFRESH_TOKEN_EXPIRE_DAYS = 7

JWT_ACCESS_TYPE = "access"
JWT_REFRESH_TYPE = "refresh"

_password_context = CryptContext(schemes=["bcrypt_sha256"], deprecated="auto")
_DUMMY_PASSWORD_HASH = (
    "$bcrypt-sha256$v=2,t=2b,r=12$m5CPBDHfdzBgaeDma./V/u"
    "$YM5xcNWpCPUhVvd7RenEXVSe0yMM4ei"
)


class TokenValidationError(Exception):
    """Raised when a JWT is invalid for the requested token flow."""


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(UTC)


def normalize_email(email: str) -> str:
    """Normalize emails consistently before lookup and persistence."""
    return email.strip().lower()


def hash_password(password: str) -> str:
    """Return a salted password hash."""
    return cast(str, _password_context.hash(password))


def verify_password(password: str, hashed_password: str) -> bool:
    """Return whether a plaintext password matches a stored hash."""
    return cast(bool, _password_context.verify(password, hashed_password))


def verify_dummy_password(password: str) -> None:
    """Exercise password verification when no account exists."""
    _password_context.verify(password, _DUMMY_PASSWORD_HASH)


def create_access_token(
    *,
    user_id: UUID,
    secret_key: str,
    algorithm: str,
    now: datetime,
) -> tuple[str, datetime]:
    """Create a signed access JWT and return it with its expiry."""
    issued_at = _as_utc(now)
    expires_at = issued_at + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": JWT_ACCESS_TYPE,
        "iat": issued_at,
        "exp": expires_at,
    }
    return jwt.encode(payload, secret_key, algorithm=algorithm), expires_at


def create_refresh_token(
    *,
    user_id: UUID,
    token_id: UUID | None,
    secret_key: str,
    algorithm: str,
    now: datetime,
) -> tuple[str, UUID, datetime]:
    """Create a signed refresh JWT and return it with jti and expiry."""
    refresh_token_id = token_id or uuid4()
    issued_at = _as_utc(now)
    expires_at = issued_at + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": JWT_REFRESH_TYPE,
        "jti": str(refresh_token_id),
        "iat": issued_at,
        "exp": expires_at,
    }
    token = jwt.encode(payload, secret_key, algorithm=algorithm)
    return token, refresh_token_id, expires_at


def decode_access_token(
    token: str,
    *,
    secret_key: str,
    algorithm: str,
) -> UUID:
    """Decode and validate an access JWT."""
    payload = _decode_token(
        token,
        secret_key=secret_key,
        algorithm=algorithm,
        required_claims=("sub", "type", "iat", "exp"),
    )
    if payload.get("type") != JWT_ACCESS_TYPE:
        raise TokenValidationError
    return _parse_uuid_claim(payload, "sub")


def decode_refresh_token(
    token: str,
    *,
    secret_key: str,
    algorithm: str,
) -> tuple[UUID, UUID]:
    """Decode and validate a refresh JWT."""
    payload = _decode_token(
        token,
        secret_key=secret_key,
        algorithm=algorithm,
        required_claims=("sub", "type", "iat", "exp", "jti"),
    )
    if payload.get("type") != JWT_REFRESH_TYPE:
        raise TokenValidationError
    return _parse_uuid_claim(payload, "sub"), _parse_uuid_claim(payload, "jti")


def refresh_token_digest(token: str, *, secret_key: str) -> str:
    """Return a deterministic digest for a raw refresh JWT."""
    return hmac.new(
        secret_key.encode("utf-8"),
        token.encode("utf-8"),
        sha256,
    ).hexdigest()


def digests_match(actual_digest: str, expected_digest: str) -> bool:
    """Compare token digests without leaking timing information."""
    return hmac.compare_digest(actual_digest, expected_digest)


def _decode_token(
    token: str,
    *,
    secret_key: str,
    algorithm: str,
    required_claims: tuple[str, ...],
) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            secret_key,
            algorithms=[algorithm],
            options={"require": list(required_claims)},
        )
    except InvalidTokenError as exc:
        raise TokenValidationError from exc

    if not isinstance(payload, dict):
        raise TokenValidationError
    return payload


def _parse_uuid_claim(payload: dict[str, Any], claim_name: str) -> UUID:
    claim = payload.get(claim_name)
    if not isinstance(claim, str):
        raise TokenValidationError
    try:
        return UUID(claim)
    except ValueError as exc:
        raise TokenValidationError from exc


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Token timestamps must be timezone-aware.")
    return value.astimezone(UTC)
