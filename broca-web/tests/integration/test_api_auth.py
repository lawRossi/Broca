"""Integration tests for auth API endpoints.

Tests /api/auth/login and /api/auth/local-login.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.services.auth_service import AuthService


class TestLoginAPI:
    """Test POST /api/auth/login."""

    @pytest.mark.asyncio
    async def test_login_success(self, async_client: AsyncClient):
        """Successful login should return token."""
        with patch("app.api.auth.AuthService") as mock_auth_service_cls:
            mock_service = AsyncMock()
            mock_user = MagicMock()
            mock_user.id = "user-001"
            mock_user.username = "testuser"
            mock_service.login = AsyncMock(return_value=(mock_user, "test-token-123"))
            mock_auth_service_cls.return_value = mock_service

            with patch("app.api.auth.get_db") as mock_get_db:
                mock_get_db.return_value = AsyncMock()

                response = await async_client.post(
                    "/api/auth/login",
                    json={"username": "testuser", "password": "password123"},
                )

                assert response.status_code == 200
                data = response.json()
                assert data["code"] == 200
                assert data["data"]["token"] == "test-token-123"
                assert data["data"]["user_id"] == "user-001"
                assert data["data"]["username"] == "testuser"

    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self, async_client: AsyncClient):
        """Invalid credentials should return 401."""
        with patch("app.api.auth.AuthService") as mock_auth_service_cls:
            mock_service = AsyncMock()
            from app.services.auth_service import AuthError

            mock_service.login = AsyncMock(side_effect=AuthError("用户名或密码错误"))
            mock_auth_service_cls.return_value = mock_service

            with patch("app.api.auth.get_db") as mock_get_db:
                mock_get_db.return_value = AsyncMock()

                response = await async_client.post(
                    "/api/auth/login",
                    json={"username": "wrong", "password": "wrong"},
                )

                assert response.status_code == 401
                data = response.json()
                assert data["code"] == 401

    @pytest.mark.asyncio
    async def test_login_internal_error(self, async_client: AsyncClient):
        """Internal server error should return 500."""
        with patch("app.api.auth.AuthService") as mock_auth_service_cls:
            mock_service = AsyncMock()
            mock_service.login = AsyncMock(side_effect=Exception("DB connection failed"))
            mock_auth_service_cls.return_value = mock_service

            with patch("app.api.auth.get_db") as mock_get_db:
                mock_get_db.return_value = AsyncMock()

                response = await async_client.post(
                    "/api/auth/login",
                    json={"username": "testuser", "password": "password123"},
                )

                assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_login_missing_fields(self, async_client: AsyncClient):
        """Missing fields should return 422."""
        response = await async_client.post("/api/auth/login", json={})
        assert response.status_code == 422


class TestLocalLoginAPI:
    """Test POST /api/auth/local-login."""

    @pytest.mark.asyncio
    async def test_local_login_from_localhost(self, async_client: AsyncClient):
        """Local login from localhost should return token."""
        response = await async_client.post(
            "/api/auth/local-login",
            headers={"X-Real-IP": "127.0.0.1"},
        )

        # Should succeed since verify_token skips auth for localhost
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 200
        assert data["data"]["user_id"] == "local"
        assert data["data"]["username"] == "Local User"
        assert "token" in data["data"]

    @pytest.mark.asyncio
    async def test_local_login_from_remote(self, async_client: AsyncClient):
        """Local login from remote IP should return 403."""
        response = await async_client.post(
            "/api/auth/local-login",
            headers={"X-Real-IP": "203.0.113.1"},
        )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_local_login_ipv6_loopback(self, async_client: AsyncClient):
        """IPv6 loopback address should be allowed."""
        response = await async_client.post(
            "/api/auth/local-login",
            headers={"X-Real-IP": "::1"},
        )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_local_login_ipv4_mapped_ipv6(self, async_client: AsyncClient):
        """IPv4-mapped IPv6 loopback should be allowed."""
        response = await async_client.post(
            "/api/auth/local-login",
            headers={"X-Real-IP": "::ffff:127.0.0.1"},
        )

        assert response.status_code == 200


class TestHealthEndpoint:
    """Test GET /api/health."""

    @pytest.mark.asyncio
    async def test_health_check(self, async_client: AsyncClient):
        """Health check should return healthy status."""
        response = await async_client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data


class TestAuthProtectedEndpoints:
    """Test authentication protection."""

    @pytest.mark.asyncio
    async def test_no_token_returns_401(self, async_client: AsyncClient):
        """Requests without token should return 401 for protected endpoints."""
        response = await async_client.get("/api/user/info")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self, async_client: AsyncClient):
        """Requests with invalid token should return 401."""
        response = await async_client.get(
            "/api/user/info",
            headers={"Authorization": "Bearer invalid-token-here"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_token_passes(self, async_client: AsyncClient, auth_headers: dict):
        """Requests with valid token should pass authentication."""
        response = await async_client.get("/api/user/info", headers=auth_headers)
        # User/info returns user data - even if no user found, it's still authenticated
        assert response.status_code != 401
