from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app

VALID_TEST_DATABASE_URL = (
    "postgresql+asyncpg://taskhub:password@localhost:5432/taskhub_test"
)


@pytest.fixture
def configured_database_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Generator[None, None, None]:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", VALID_TEST_DATABASE_URL)
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


@pytest.fixture
def client(configured_database_url: None) -> Generator[TestClient, None, None]:
    with TestClient(create_app()) as test_client:
        yield test_client
