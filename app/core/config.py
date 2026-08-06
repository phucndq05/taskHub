from functools import lru_cache
from urllib.parse import urlparse

from pydantic import EmailStr, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

SUPPORTED_JWT_ALGORITHMS = {"HS256"}
SUPPORTED_REDIS_SCHEMES = {"redis", "rediss"}


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    database_url: str
    jwt_secret_key: SecretStr
    jwt_algorithm: str = "HS256"
    redis_url: str = "redis://localhost:6379/0"
    task_list_cache_ttl_seconds: int = 60
    smtp_host: str | None = None
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from_email: EmailStr = "no-reply@example.com"
    smtp_use_starttls: bool = False
    smtp_timeout_seconds: float = 10.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def validate_database_url(cls, value: object) -> str:
        """Validate the database URL format without opening a connection."""
        if not isinstance(value, str):
            raise ValueError("DATABASE_URL must be a string.")

        database_url = value.strip()
        if not database_url:
            raise ValueError("DATABASE_URL must not be empty.")

        try:
            parsed_url = make_url(database_url)
        except ArgumentError as exc:
            raise ValueError(
                "DATABASE_URL must be a valid SQLAlchemy database URL."
            ) from exc

        if parsed_url.drivername != "postgresql+asyncpg":
            raise ValueError("DATABASE_URL must use the postgresql+asyncpg driver.")

        if parsed_url.database is None or parsed_url.database == "":
            raise ValueError("DATABASE_URL must include a database name.")

        return database_url

    @field_validator("jwt_algorithm", mode="before")
    @classmethod
    def validate_jwt_algorithm(cls, value: object) -> str:
        """Validate the configured JWT signing algorithm."""
        if not isinstance(value, str):
            raise ValueError("JWT_ALGORITHM must be a string.")

        algorithm = value.strip()
        if algorithm not in SUPPORTED_JWT_ALGORITHMS:
            raise ValueError("JWT_ALGORITHM must be HS256.")

        return algorithm

    @field_validator("redis_url", mode="before")
    @classmethod
    def validate_redis_url(cls, value: object) -> str:
        """Validate the Redis URL format without opening a connection."""
        if not isinstance(value, str):
            raise ValueError("REDIS_URL must be a string.")

        redis_url = value.strip()
        if not redis_url:
            raise ValueError("REDIS_URL must not be empty.")

        parsed_url = urlparse(redis_url)
        if parsed_url.scheme not in SUPPORTED_REDIS_SCHEMES:
            raise ValueError("REDIS_URL must use the redis or rediss scheme.")
        if not parsed_url.hostname:
            raise ValueError("REDIS_URL must include a host.")

        return redis_url

    @field_validator("task_list_cache_ttl_seconds")
    @classmethod
    def validate_task_list_cache_ttl_seconds(cls, value: int) -> int:
        """Validate the task-list cache TTL."""
        if value <= 0:
            raise ValueError("TASK_LIST_CACHE_TTL_SECONDS must be positive.")
        return value

    @field_validator("smtp_host", "smtp_username", mode="before")
    @classmethod
    def normalize_optional_smtp_string(cls, value: object) -> str | None:
        """Normalize optional SMTP string settings."""
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("SMTP optional string settings must be strings.")

        normalized = value.strip()
        return normalized or None

    @field_validator("smtp_password", mode="before")
    @classmethod
    def normalize_optional_smtp_password(cls, value: object) -> str | None:
        """Normalize optional SMTP password settings."""
        if value is None:
            return None
        if isinstance(value, SecretStr):
            normalized = value.get_secret_value().strip()
            return normalized or None
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        raise ValueError("SMTP_PASSWORD must be a string.")

    @field_validator("smtp_from_email", mode="before")
    @classmethod
    def normalize_smtp_from_email(cls, value: object) -> object:
        """Trim the SMTP sender address before EmailStr validation."""
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("smtp_port")
    @classmethod
    def validate_smtp_port(cls, value: int) -> int:
        """Validate the SMTP port range."""
        if value < 1 or value > 65535:
            raise ValueError("SMTP_PORT must be from 1 through 65535.")
        return value

    @field_validator("smtp_timeout_seconds")
    @classmethod
    def validate_smtp_timeout_seconds(cls, value: float) -> float:
        """Validate the SMTP connection timeout."""
        if value <= 0:
            raise ValueError("SMTP_TIMEOUT_SECONDS must be greater than zero.")
        return value

    @model_validator(mode="after")
    def validate_smtp_credentials(self) -> "Settings":
        """Require SMTP username and password to be configured together."""
        has_username = self.smtp_username is not None
        has_password = self.smtp_password is not None
        if has_username != has_password:
            raise ValueError(
                "SMTP_USERNAME and SMTP_PASSWORD must be supplied together."
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
