"""Unit tests for app.core.config module.

Tests Settings model and property calculations.
"""

from __future__ import annotations

import os

import pytest

# Import after conftest patches
from app.core.config import Settings


class TestSettings:
    """Test the Settings model."""

    def test_default_values(self):
        """Default values should be set correctly."""
        s = Settings()
        assert s.database_type == "sqlite"
        assert s.host == "0.0.0.0"
        assert s.port == 8000
        assert s.jwt_algorithm == "HS256"
        assert s.jwt_expire_minutes == 2880

    def test_sqlite_async_url(self):
        """async_database_url for sqlite should use aiosqlite."""
        s = Settings(database_type="sqlite", sqlite_database_path="sqlite:///./dev.db")
        assert s.async_database_url == "sqlite+aiosqlite:///./dev.db"
        assert s.sync_database_url == "sqlite:///./dev.db"

    def test_sqlite_async_url_absolute_path(self):
        """async_database_url should handle absolute paths."""
        s = Settings(database_type="sqlite", sqlite_database_path="sqlite:////data/broca.db")
        assert s.async_database_url == "sqlite+aiosqlite:////data/broca.db"
        assert s.sync_database_url == "sqlite:////data/broca.db"

    def test_postgresql_url(self):
        """async_database_url for postgresql should return raw URL."""
        s = Settings(
            database_type="postgresql",
            database_url="postgresql+asyncpg://user:pass@localhost:5432/broca",
            database_url_sync="postgresql://user:pass@localhost:5432/broca",
        )
        assert s.async_database_url == "postgresql+asyncpg://user:pass@localhost:5432/broca"
        assert s.sync_database_url == "postgresql://user:pass@localhost:5432/broca"

    def test_jwt_secret_default(self):
        """JWT secret should be configurable via env var."""
        s = Settings()
        # Default value when JWT_SECRET env is not set
        # But our conftest sets it to test-secret-key-for-testing-only
        assert len(s.jwt_secret) > 0

    def test_port_from_int(self):
        """Port should be parsed from int."""
        s = Settings(port=3000)
        assert s.port == 3000

    @pytest.mark.parametrize(
        ("database_type", "expected_async"),
        [
            ("sqlite", "sqlite+aiosqlite:///./test.db"),
            ("postgresql", "postgresql+asyncpg://host/db"),
        ],
    )
    def test_database_types(self, database_type, expected_async):
        """Different database types should produce correct URLs."""
        s = Settings(
            database_type=database_type,
            sqlite_database_path="sqlite:///./test.db",
            database_url="postgresql+asyncpg://host/db",
        )
        assert s.async_database_url == expected_async

    def test_env_file_config(self):
        """Settings should have env_file configured."""
        assert Settings.model_config.get("env_file") is not None
        env_files = Settings.model_config["env_file"]
        assert ".env.local" in env_files
        assert ".env.production" in env_files
        assert ".env.development" in env_files
