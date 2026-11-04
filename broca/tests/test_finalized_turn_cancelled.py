"""
Regression test: _finalize_turn is safe after CancelledError.

Before the fix, a CancelledError during _execute_round would cause
_finalize_turn to raise (since CancelledError is BaseException in 3.9+),
crashing the engine and losing the ABORTED status.
After the fix, _finalize_turn catches CancelledError internally and the
outer call site has a defensive try/except.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broca.loop_engine.engine import DefaultLoopEngine
from broca.components.loop_engine import ExecutionResult, ExecutionStatus
from broca.components.loop_hook import TurnContext
from broca.session.models import Message, MessageRole, MessageType


def _make_engine():
    """Create a minimal DefaultLoopEngine with mocked dependencies."""
    engine = DefaultLoopEngine.__new__(DefaultLoopEngine)
    engine.agent_id = "test-agent"
    engine.session_id = "test-session"
    engine.turn_id = "test-turn"
    engine.session_manager = MagicMock()
    engine.session_manager.save_turn_end = AsyncMock(return_value=True)
    engine.communicator = MagicMock()
    engine.context = None
    engine.hooks = []
    engine.strategies = {}
    engine.allowed_tools = None
    engine.namespace = None
    engine._chunk_flush_task = None
    engine._flushing = False
    return engine


def _make_turn_ctx():
    from broca.components.loop_hook import TurnContext
    ctx = TurnContext(
        turn_id="test-turn",
        agent_id="test-agent",
        session_id="test-session",
        user_message={},
        message_id="msg_001",
        data={},
    )
    ctx.data["turn_end_message"] = "Turn ended"
    ctx.data["turn_end_message_id"] = "msg_test"
    return ctx


@pytest.mark.asyncio
async def test_finalize_turn_survives_cancelled_error():
    """_finalize_turn catches CancelledError and returns False."""
    engine = _make_engine()
    turn_ctx = _make_turn_ctx()
    result = ExecutionResult(status=ExecutionStatus.ABORTED)

    # Mock save_turn_end to raise CancelledError (simulating loop teardown)
    engine.session_manager.save_turn_end = AsyncMock(
        side_effect=asyncio.CancelledError()
    )

    saved = await engine._finalize_turn(turn_ctx, result)
    assert saved is False  # Should not raise, should return False


@pytest.mark.asyncio
async def test_finalize_turn_survives_runtime_error():
    """_finalize_turn catches RuntimeError (e.g., 'Event loop is closed')."""
    engine = _make_engine()
    turn_ctx = _make_turn_ctx()
    result = ExecutionResult(status=ExecutionStatus.ABORTED)

    engine.session_manager.save_turn_end = AsyncMock(
        side_effect=RuntimeError("Event loop is closed")
    )

    saved = await engine._finalize_turn(turn_ctx, result)
    assert saved is False


@pytest.mark.asyncio
async def test_execute_returns_aborted_after_cancelled_error():
    """execute() returns ABORTED result even when _execute_round raises CancelledError."""
    engine = _make_engine()

    # Mock _setup_turn to succeed
    from broca.components.loop_hook import TurnContext
    turn_ctx = TurnContext(turn_id="test-turn", agent_id="test-agent", session_id="test-session", user_message={}, message_id="msg_001", data={})
    turn_ctx.data["turn_end_message"] = "Turn ended"
    turn_ctx.data["turn_end_message_id"] = "msg_test"

    engine._setup_turn = AsyncMock(return_value=turn_ctx)
    engine._dispatch = AsyncMock()
    engine._execute_round = AsyncMock(side_effect=asyncio.CancelledError())
    engine._ensure_strategies = AsyncMock()
    engine._finalize_turn = AsyncMock(return_value=True)
    engine._send_execution_error = AsyncMock()
    engine._make_error_result = MagicMock()

    message = Message(
        message_type=MessageType.USER_MESSAGE,
        role=MessageRole.USER,
        sender_id="user",
        data={"content": "hello"},
    )

    result = await engine.execute(message)
    assert result.status == ExecutionStatus.ABORTED
    # _finalize_turn should still be called
    engine._finalize_turn.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_finalize_turn_exception_defensive():
    """Even if _finalize_turn raises (unexpected), execute() doesn't crash."""
    engine = _make_engine()

    from broca.components.loop_hook import TurnContext
    turn_ctx = TurnContext(turn_id="test-turn", agent_id="test-agent", session_id="test-session", user_message={}, message_id="msg_001", data={})
    turn_ctx.data["turn_end_message"] = "Turn ended"
    turn_ctx.data["turn_end_message_id"] = "msg_test"

    engine._setup_turn = AsyncMock(return_value=turn_ctx)
    engine._dispatch = AsyncMock()
    engine._execute_round = AsyncMock(
        return_value=ExecutionResult(status=ExecutionStatus.COMPLETED)
    )
    engine._ensure_strategies = AsyncMock()
    # Make _finalize_turn raise unexpectedly
    engine._finalize_turn = AsyncMock(side_effect=RuntimeError("unexpected"))
    engine._send_execution_error = AsyncMock()
    engine._make_error_result = MagicMock()

    message = Message(
        message_type=MessageType.USER_MESSAGE,
        role=MessageRole.USER,
        sender_id="user",
        data={"content": "hello"},
    )

    result = await engine.execute(message)
    # Should still return a result, not crash
    assert result is not None
    assert result.status == ExecutionStatus.COMPLETED
