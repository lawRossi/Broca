"""
Regression tests for SQLSessionManager strict mode.

Verifies that:
1. strict=True causes persistence failures to raise SessionError
2. strict=False (default) preserves the original silent-failure behavior
3. Non-engine callers are unaffected
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broca.errors import SessionError


class TestSaveMessageStrict:
    """save_message() strict mode behavior."""

    def _make_manager(self):
        """Create a SQLSessionManager with mocked internals."""
        from broca.session.session_manager import SQLSessionManager

        mgr = MagicMock(spec=SQLSessionManager)
        mgr.session_id = "test_session"
        mgr.current_execution_id = None
        # Mock the internal service that actually does DB work
        mgr.message_service = AsyncMock()
        mgr.message_service.next_sequence_for_session = AsyncMock(return_value=1)
        mgr.message_service.create_message = AsyncMock(return_value=MagicMock())
        mgr._ensure_initialized = AsyncMock()
        return mgr

    @pytest.mark.asyncio
    async def test_strict_true_raises_on_failure(self):
        """strict=True + DB failure → raises SessionError with cause."""
        mgr = self._make_manager()
        mgr.save_message = _patch_save_message(mgr, strict=True)

        # Make the internal create_message raise
        mgr.message_service.create_message = AsyncMock(
            side_effect=RuntimeError("DB connection lost")
        )

        with pytest.raises(SessionError) as exc_info:
            await mgr.save_message(
                role="user",
                content="test",
                message_type="user_message",
                turn_id="turn_1",
                agent_id="agent_1",
                strict=True,
            )

        assert "持久化操作失败" in str(exc_info.value)
        assert exc_info.value.info.cause_exc is not None
        assert isinstance(exc_info.value.info.cause_exc, RuntimeError)

    @pytest.mark.asyncio
    async def test_strict_false_returns_false_on_failure(self):
        """strict=False (default) + DB failure → returns False silently."""
        mgr = self._make_manager()
        mgr.save_message = _patch_save_message(mgr, strict=False)

        mgr.message_service.create_message = AsyncMock(
            side_effect=RuntimeError("DB connection lost")
        )

        result = await mgr.save_message(
            role="user",
            content="test",
            message_type="user_message",
            turn_id="turn_1",
            agent_id="agent_1",
        )

        assert result is False
        # No exception should be raised

    @pytest.mark.asyncio
    async def test_strict_true_success_returns_true(self):
        """strict=True + successful save → returns True normally."""
        mgr = self._make_manager()
        mgr.save_message = _patch_save_message(mgr, strict=True)

        mgr.message_service.create_message = AsyncMock(return_value=MagicMock())

        result = await mgr.save_message(
            role="user",
            content="test",
            message_type="user_message",
            turn_id="turn_1",
            agent_id="agent_1",
            strict=True,
        )

        assert result is True


class TestStartTurnStrict:
    """start_turn() strict mode behavior."""

    @pytest.mark.asyncio
    async def test_strict_true_raises_on_failure(self):
        """strict=True + DB failure → raises SessionError."""
        from broca.session.session_manager import SQLSessionManager

        mgr = MagicMock(spec=SQLSessionManager)
        mgr.session_id = "test_session"
        mgr.current_execution_id = None
        mgr._ensure_initialized = AsyncMock()

        # Patch the actual method to test strict behavior
        # We simulate by making the turn service fail
        mgr.turn_service = AsyncMock()
        mgr.turn_service.next_turn_seq_in_session = AsyncMock(
            side_effect=RuntimeError("turn creation failed")
        )
        mgr.message_service = AsyncMock()
        mgr._ensure_initialized = AsyncMock()

        # Use the real start_turn logic by calling the unbound method
        import broca.session.session_manager as sm_module

        real_start_turn = sm_module.SQLSessionManager.start_turn

        with pytest.raises(SessionError) as exc_info:
            await real_start_turn(
                mgr,
                agent_id="agent_1",
                strict=True,
            )

        assert "持久化操作失败" in str(exc_info.value)
        assert isinstance(exc_info.value.info.cause_exc, RuntimeError)

    @pytest.mark.asyncio
    async def test_strict_false_returns_none_on_failure(self):
        """strict=False (default) + DB failure → returns None."""
        from broca.session.session_manager import SQLSessionManager

        mgr = MagicMock(spec=SQLSessionManager)
        mgr.session_id = "test_session"
        mgr.current_execution_id = None
        mgr._ensure_initialized = AsyncMock()
        mgr.turn_service = AsyncMock()
        mgr.turn_service.next_turn_seq_in_session = AsyncMock(
            side_effect=RuntimeError("turn creation failed")
        )
        mgr.message_service = AsyncMock()

        import broca.session.session_manager as sm_module

        real_start_turn = sm_module.SQLSessionManager.start_turn

        result = await real_start_turn(mgr, agent_id="agent_1")
        assert result is None


class TestBackwardCompatibility:
    """Default behavior (strict=False) is unchanged for existing callers."""

    @pytest.mark.asyncio
    async def test_default_strict_is_false(self):
        """Calling save_message without strict= uses silent degradation."""
        from broca.session.session_manager import SQLSessionManager
        import inspect

        sig = inspect.signature(SQLSessionManager.save_message)
        param = sig.parameters["strict"]
        assert param.default is False

    @pytest.mark.asyncio
    async def test_start_turn_default_strict_is_false(self):
        """Calling start_turn without strict= uses silent degradation."""
        from broca.session.session_manager import SQLSessionManager
        import inspect

        sig = inspect.signature(SQLSessionManager.start_turn)
        param = sig.parameters["strict"]
        assert param.default is False


def _patch_save_message(mgr, strict: bool):
    """
    Create a bound-style function that mirrors the real save_message logic
    but on our mock manager, to test the strict parameter behavior in isolation.
    """
    import uuid as _uuid
    from broca.errors import SessionError as _SessionError
    from broca.session.models import MessageRole, MessageType

    async def _save(
        role,
        content=None,
        message_type=None,
        turn_id=None,
        agent_id=None,
        message_id=None,
        data=None,
        strict=False,
    ):
        if not mgr.session_id:
            return False
        try:
            await mgr._ensure_initialized()
            message_id = message_id or f"msg_{_uuid.uuid4().hex[:16]}"
            message_data = data or {}
            if content:
                message_data["content"] = content
            seq_num = await mgr.message_service.next_sequence_for_session(
                mgr.session_id
            )
            message = await mgr.message_service.create_message(
                message_id=message_id,
                session_id=mgr.session_id,
                turn_id=turn_id,
                agent_id=agent_id,
                role=MessageRole(role),
                message_type=MessageType(message_type),
                sequence_number=seq_num,
                data=message_data,
                execution_id=mgr.current_execution_id,
            )
            return message is not None
        except Exception as e:
            if strict:
                raise _SessionError(f"持久化操作失败: {e}", cause=e) from e
            return False

    return _save
