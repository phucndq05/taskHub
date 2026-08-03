import importlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings

VALID_DATABASE_URL = "postgresql+asyncpg://taskhub:password@localhost:5432/taskhub"
DOTENV_DATABASE_URL = "postgresql+asyncpg://taskhub:example@localhost:5432/taskhub"
VALID_JWT_SECRET_KEY = "test-secret-key-with-at-least-32-characters"


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
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.database_url == DOTENV_DATABASE_URL
    assert settings.jwt_secret_key.get_secret_value() == VALID_JWT_SECRET_KEY
    assert settings.jwt_algorithm == "HS256"


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
