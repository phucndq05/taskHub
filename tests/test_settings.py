import importlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings

VALID_DATABASE_URL = "postgresql+asyncpg://taskhub:password@localhost:5432/taskhub"
DOTENV_DATABASE_URL = "postgresql+asyncpg://taskhub:example@localhost:5432/taskhub"
VALID_JWT_SECRET_KEY = "test-secret-key-with-at-least-32-characters"
VALID_REDIS_URL = "redis://localhost:6379/0"


def test_config_import_does_not_require_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    config_module = importlib.import_module("app.core.config")
    reloaded_module = importlib.reload(config_module)

    assert hasattr(reloaded_module, "Settings")


def test_settings_reads_valid_database_url_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", f"  {VALID_DATABASE_URL}  ")
    monkeypatch.setenv("JWT_SECRET_KEY", VALID_JWT_SECRET_KEY)

    settings = Settings(_env_file=None)

    assert settings.database_url == VALID_DATABASE_URL
    assert settings.jwt_secret_key.get_secret_value() == VALID_JWT_SECRET_KEY
    assert settings.jwt_algorithm == "HS256"
    assert settings.redis_url == VALID_REDIS_URL
    assert settings.task_list_cache_ttl_seconds == 60
    assert settings.smtp_host is None
    assert settings.smtp_port == 1025
    assert settings.smtp_username is None
    assert settings.smtp_password is None
    assert str(settings.smtp_from_email) == "no-reply@example.com"
    assert settings.smtp_use_starttls is False
    assert settings.smtp_timeout_seconds == 10.0


def test_settings_reads_valid_redis_cache_settings_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_DATABASE_URL)
    monkeypatch.setenv("JWT_SECRET_KEY", VALID_JWT_SECRET_KEY)
    monkeypatch.setenv("REDIS_URL", "  redis://localhost:6379/15  ")
    monkeypatch.setenv("TASK_LIST_CACHE_TTL_SECONDS", "120")

    settings = Settings(_env_file=None)

    assert settings.redis_url == "redis://localhost:6379/15"
    assert settings.task_list_cache_ttl_seconds == 120


def test_settings_reads_valid_smtp_settings_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_DATABASE_URL)
    monkeypatch.setenv("JWT_SECRET_KEY", VALID_JWT_SECRET_KEY)
    monkeypatch.setenv("SMTP_HOST", "  smtp.example.test  ")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_USERNAME", "  smtp-user  ")
    monkeypatch.setenv("SMTP_PASSWORD", "  smtp-password  ")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "  taskhub@example.com  ")
    monkeypatch.setenv("SMTP_USE_STARTTLS", "true")
    monkeypatch.setenv("SMTP_TIMEOUT_SECONDS", "2.5")

    settings = Settings(_env_file=None)

    assert settings.smtp_host == "smtp.example.test"
    assert settings.smtp_port == 2525
    assert settings.smtp_username == "smtp-user"
    assert settings.smtp_password is not None
    assert settings.smtp_password.get_secret_value() == "smtp-password"
    assert str(settings.smtp_from_email) == "taskhub@example.com"
    assert settings.smtp_use_starttls is True
    assert settings.smtp_timeout_seconds == 2.5


def test_settings_normalizes_blank_optional_smtp_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_DATABASE_URL)
    monkeypatch.setenv("JWT_SECRET_KEY", VALID_JWT_SECRET_KEY)
    monkeypatch.setenv("SMTP_HOST", "   ")
    monkeypatch.setenv("SMTP_USERNAME", "")
    monkeypatch.setenv("SMTP_PASSWORD", "  ")

    settings = Settings(_env_file=None)

    assert settings.smtp_host is None
    assert settings.smtp_username is None
    assert settings.smtp_password is None


def test_settings_reads_dotenv_and_ignores_extra_variables(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "POSTGRES_DB=taskhub",
                "POSTGRES_USER=taskhub",
                "POSTGRES_PASSWORD=example",
                f"DATABASE_URL={DOTENV_DATABASE_URL}",
                f"JWT_SECRET_KEY={VALID_JWT_SECRET_KEY}",
                "JWT_ALGORITHM=HS256",
                "REDIS_URL=redis://localhost:6379/1",
                "TASK_LIST_CACHE_TTL_SECONDS=90",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.database_url == DOTENV_DATABASE_URL
    assert settings.jwt_secret_key.get_secret_value() == VALID_JWT_SECRET_KEY
    assert settings.jwt_algorithm == "HS256"
    assert settings.redis_url == "redis://localhost:6379/1"
    assert settings.task_list_cache_ttl_seconds == 90


def test_settings_requires_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("JWT_SECRET_KEY", VALID_JWT_SECRET_KEY)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert "database_url" in str(exc_info.value)


def test_settings_requires_jwt_secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.setenv("DATABASE_URL", VALID_DATABASE_URL)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert "jwt_secret_key" in str(exc_info.value)


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://taskhub:password@localhost:5432/taskhub",
        "postgresql+psycopg://taskhub:password@localhost:5432/taskhub",
        "sqlite:///taskhub.db",
    ],
)
def test_settings_rejects_wrong_database_driver(
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("JWT_SECRET_KEY", VALID_JWT_SECRET_KEY)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert "postgresql+asyncpg" in str(exc_info.value)


def test_settings_rejects_malformed_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "not a database url")
    monkeypatch.setenv("JWT_SECRET_KEY", VALID_JWT_SECRET_KEY)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert "valid SQLAlchemy database URL" in str(exc_info.value)


def test_settings_rejects_database_url_without_database_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://taskhub:password@localhost:5432",
    )
    monkeypatch.setenv("JWT_SECRET_KEY", VALID_JWT_SECRET_KEY)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert "database name" in str(exc_info.value)


def test_settings_rejects_unsupported_jwt_algorithm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_DATABASE_URL)
    monkeypatch.setenv("JWT_SECRET_KEY", VALID_JWT_SECRET_KEY)
    monkeypatch.setenv("JWT_ALGORITHM", "none")

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert "JWT_ALGORITHM must be HS256" in str(exc_info.value)


@pytest.mark.parametrize(
    "redis_url",
    [
        "",
        "postgresql://localhost:6379/0",
        "redis:///0",
    ],
)
def test_settings_rejects_invalid_redis_url(
    monkeypatch: pytest.MonkeyPatch,
    redis_url: str,
) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_DATABASE_URL)
    monkeypatch.setenv("JWT_SECRET_KEY", VALID_JWT_SECRET_KEY)
    monkeypatch.setenv("REDIS_URL", redis_url)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert "REDIS_URL" in str(exc_info.value)


@pytest.mark.parametrize("ttl", ["0", "-1"])
def test_settings_rejects_non_positive_task_list_cache_ttl(
    monkeypatch: pytest.MonkeyPatch,
    ttl: str,
) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_DATABASE_URL)
    monkeypatch.setenv("JWT_SECRET_KEY", VALID_JWT_SECRET_KEY)
    monkeypatch.setenv("TASK_LIST_CACHE_TTL_SECONDS", ttl)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert "TASK_LIST_CACHE_TTL_SECONDS must be positive" in str(exc_info.value)


@pytest.mark.parametrize("smtp_port", ["0", "65536", "-1"])
def test_settings_rejects_invalid_smtp_port(
    monkeypatch: pytest.MonkeyPatch,
    smtp_port: str,
) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_DATABASE_URL)
    monkeypatch.setenv("JWT_SECRET_KEY", VALID_JWT_SECRET_KEY)
    monkeypatch.setenv("SMTP_PORT", smtp_port)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert "SMTP_PORT must be from 1 through 65535" in str(exc_info.value)


@pytest.mark.parametrize("timeout", ["0", "-0.1"])
def test_settings_rejects_non_positive_smtp_timeout(
    monkeypatch: pytest.MonkeyPatch,
    timeout: str,
) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_DATABASE_URL)
    monkeypatch.setenv("JWT_SECRET_KEY", VALID_JWT_SECRET_KEY)
    monkeypatch.setenv("SMTP_TIMEOUT_SECONDS", timeout)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert "SMTP_TIMEOUT_SECONDS must be greater than zero" in str(exc_info.value)


@pytest.mark.parametrize(
    ("smtp_username", "smtp_password"),
    [
        ("smtp-user", None),
        (None, "smtp-password"),
    ],
)
def test_settings_requires_smtp_username_password_pair(
    monkeypatch: pytest.MonkeyPatch,
    smtp_username: str | None,
    smtp_password: str | None,
) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_DATABASE_URL)
    monkeypatch.setenv("JWT_SECRET_KEY", VALID_JWT_SECRET_KEY)
    if smtp_username is not None:
        monkeypatch.setenv("SMTP_USERNAME", smtp_username)
    if smtp_password is not None:
        monkeypatch.setenv("SMTP_PASSWORD", smtp_password)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert "SMTP_USERNAME and SMTP_PASSWORD must be supplied together" in str(
        exc_info.value
    )


def test_settings_rejects_invalid_smtp_from_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_DATABASE_URL)
    monkeypatch.setenv("JWT_SECRET_KEY", VALID_JWT_SECRET_KEY)
    monkeypatch.setenv("SMTP_FROM_EMAIL", "not-an-email")

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert "smtp_from_email" in str(exc_info.value)


def test_get_settings_returns_cached_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", VALID_DATABASE_URL)
    monkeypatch.setenv("JWT_SECRET_KEY", VALID_JWT_SECRET_KEY)
    get_settings.cache_clear()

    try:
        first_settings = get_settings()
        second_settings = get_settings()

        assert first_settings is second_settings
    finally:
        get_settings.cache_clear()
