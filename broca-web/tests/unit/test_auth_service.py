"""Unit tests for app.services.auth_service module.

Tests AuthService: password hashing, JWT token handling, registration, login.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth_service import AuthError, AuthService


class TestAuthServicePassword:
    """Test password hashing and verification."""

    def test_hash_and_verify_password(self):
        """Hashed password should verify correctly."""
        password = "my-secure-password-123"
        hashed = AuthService.hash_password(password)
        assert hashed != password
        assert AuthService.verify_password(password, hashed) is True

    def test_verify_wrong_password(self):
        """Wrong password should not verify."""
        hashed = AuthService.hash_password("correct-password")
        assert AuthService.verify_password("wrong-password", hashed) is False

    def test_hash_is_different_each_time(self):
        """Each hash should be unique (different salt)."""
        password = "same-password"
        hash1 = AuthService.hash_password(password)
        hash2 = AuthService.hash_password(password)
        assert hash1 != hash2
        assert AuthService.verify_password(password, hash1) is True
        assert AuthService.verify_password(password, hash2) is True

    def test_empty_password_hash(self):
        """Empty password should still produce a hash."""
        hashed = AuthService.hash_password("")
        assert AuthService.verify_password("", hashed) is True

    def test_special_characters(self):
        """Passwords with special characters should work."""
        password = "!@#$%^&*()_+-=[]{}|;':\",./<>?`~ 你好"
        hashed = AuthService.hash_password(password)
        assert AuthService.verify_password(password, hashed) is True


class TestAuthServiceJWT:
    """Test JWT token creation, decoding, and expiration."""

    def test_create_and_decode_token(self):
        """Created token should decode correctly."""
        token = AuthService.create_access_token("user-123", "testuser")
        assert token is not None
        assert isinstance(token, str)

        payload = AuthService.decode_access_token(token)
        assert payload["sub"] == "user-123"
        assert payload["username"] == "testuser"
        assert "exp" in payload
        assert "iat" in payload

    def test_decode_invalid_token(self):
        """Invalid token should raise AuthError."""
        with pytest.raises(AuthError, match="Invalid or expired token"):
            AuthService.decode_access_token("invalid-token")

    def test_decode_tampered_token(self):
        """Tampered token should raise AuthError."""
        token = AuthService.create_access_token("user-123", "testuser")
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(AuthError):
            AuthService.decode_access_token(tampered)

    def test_token_contains_expected_claims(self):
        """Token should contain sub, username, exp, iat."""
        token = AuthService.create_access_token("user-456", "alice")
        payload = AuthService.decode_access_token(token)
        assert set(payload.keys()) >= {"sub", "username", "exp", "iat"}

    def test_token_expiration_time(self):
        """Token should have expiration in the future."""
        token = AuthService.create_access_token("user-789", "bob")
        payload = AuthService.decode_access_token(token)
        exp = payload["exp"]
        exp_dt = datetime.fromtimestamp(exp, tz=UTC)
        assert exp_dt > datetime.now(UTC)
        # Should be approximately jwt_expire_minutes (2880 = 48h)
        diff = (exp_dt - datetime.now(UTC)).total_seconds()
        assert 2875 * 60 < diff < 2885 * 60  # Allow small tolerance

    def test_is_token_expired_fresh_token(self):
        """Fresh token should not be expired."""
        token = AuthService.create_access_token("user-001", "fresh")
        assert AuthService.is_token_expired(token) is False

    def test_is_token_expired_expired_token(self):
        """Expired token should be detected."""
        # Manually create an expired token
        from app.core.config import settings

        expire = datetime.now(UTC) - timedelta(hours=1)
        payload = {"sub": "user-001", "username": "expired", "exp": expire.timestamp(), "iat": datetime.now(UTC)}
        expired_token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
        assert AuthService.is_token_expired(expired_token) is True

    def test_is_token_expired_invalid_token(self):
        """Invalid token should be considered expired."""
        assert AuthService.is_token_expired("clearly-invalid") is True


class TestAuthServiceRegister:
    """Test user registration."""

    @pytest.mark.asyncio
    async def test_register_success(self):
        """Successful registration should return user with hashed password."""
        # Setup mock session
        mock_session = AsyncMock()
        mock_session.scalar = AsyncMock(return_value=None)  # No existing user
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        auth_service = AuthService(mock_session)
        user = await auth_service.register("newuser", "password123")

        assert user is not None
        assert user.username == "newuser"
        assert user.hashed_password != "password123"  # Should be hashed
        assert AuthService.verify_password("password123", user.hashed_password)
        assert mock_session.add.called
        assert mock_session.commit.called
        assert mock_session.refresh.called

    @pytest.mark.asyncio
    async def test_register_duplicate_username(self):
        """Registering with existing username should raise AuthError."""
        mock_session = AsyncMock()
        # Simulate existing user
        existing_user = MagicMock()
        mock_session.scalar = AsyncMock(return_value=existing_user)

        auth_service = AuthService(mock_session)
        with pytest.raises(AuthError, match="用户名已被注册"):
            await auth_service.register("existing_user", "password123")

    @pytest.mark.asyncio
    async def test_register_short_username(self):
        """Username shorter than 2 chars should raise AuthError."""
        mock_session = AsyncMock()
        auth_service = AuthService(mock_session)
        with pytest.raises(AuthError, match="用户名至少需要2个字符"):
            await auth_service.register("a", "password123")

    @pytest.mark.asyncio
    async def test_register_empty_username(self):
        """Empty username should raise AuthError."""
        mock_session = AsyncMock()
        auth_service = AuthService(mock_session)
        with pytest.raises(AuthError, match="用户名至少需要2个字符"):
            await auth_service.register("  ", "password123")

    @pytest.mark.asyncio
    async def test_register_short_password(self):
        """Password shorter than 6 chars should raise AuthError."""
        mock_session = AsyncMock()
        auth_service = AuthService(mock_session)
        with pytest.raises(AuthError, match="密码至少需要6个字符"):
            await auth_service.register("validuser", "12345")


class TestAuthServiceLogin:
    """Test user login."""

    @pytest.mark.asyncio
    async def test_login_success(self):
        """Successful login should return user and token."""
        mock_session = AsyncMock()
        hashed = AuthService.hash_password("correct-password")

        mock_user = MagicMock()
        mock_user.id = "user-001"
        mock_user.username = "testuser"
        mock_user.hashed_password = hashed
        mock_user.last_login_at = None

        mock_session.scalar = AsyncMock(return_value=mock_user)
        mock_session.commit = AsyncMock()

        auth_service = AuthService(mock_session)
        user, token = await auth_service.login("testuser", "correct-password")

        assert user.id == "user-001"
        assert user.username == "testuser"
        assert token is not None

        # Token should contain user info
        payload = AuthService.decode_access_token(token)
        assert payload["sub"] == "user-001"
        assert payload["username"] == "testuser"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self):
        """Wrong password should raise AuthError."""
        mock_session = AsyncMock()
        hashed = AuthService.hash_password("correct-password")

        mock_user = MagicMock()
        mock_user.hashed_password = hashed

        mock_session.scalar = AsyncMock(return_value=mock_user)

        auth_service = AuthService(mock_session)
        with pytest.raises(AuthError, match="用户名或密码错误"):
            await auth_service.login("testuser", "wrong-password")

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self):
        """Non-existent username should raise AuthError."""
        mock_session = AsyncMock()
        mock_session.scalar = AsyncMock(return_value=None)

        auth_service = AuthService(mock_session)
        with pytest.raises(AuthError, match="用户名或密码错误"):
            await auth_service.login("nonexistent", "password123")

    @pytest.mark.asyncio
    async def test_login_updates_last_login(self):
        """Last login time should be updated on successful login."""
        mock_session = AsyncMock()
        mock_user = MagicMock()
        mock_user.hashed_password = AuthService.hash_password("password")
        mock_user.id = "user-002"
        mock_user.username = "testuser2"
        mock_user.last_login_at = None

        mock_session.scalar = AsyncMock(return_value=mock_user)
        mock_session.commit = AsyncMock()

        auth_service = AuthService(mock_session)
        await auth_service.login("testuser2", "password")

        # last_login_at should be set
        assert mock_user.last_login_at is not None
        assert mock_session.commit.called


class TestAuthServiceGetUser:
    """Test get_user_by_id method."""

    @pytest.mark.asyncio
    async def test_get_user_found(self):
        """Existing user should be returned."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_user = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_session.execute.return_value = mock_result

        auth_service = AuthService(mock_session)
        result = await auth_service.get_user_by_id("user-001")
        assert result is mock_user

    @pytest.mark.asyncio
    async def test_get_user_not_found(self):
        """Non-existent user should return None."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        auth_service = AuthService(mock_session)
        result = await auth_service.get_user_by_id("nonexistent")
        assert result is None
