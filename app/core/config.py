from functools import lru_cache
from urllib.parse import urlparse

from pydantic import SecretStr, field_validator
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
