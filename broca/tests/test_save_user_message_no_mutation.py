"""
Regression test: _save_user_message does not mutate the input message.data.

Before the fix, the method directly set `message.data["from_agent"]` and
`message.data["raw_input"]`, mutating the caller's dict. After the fix,
a new dict is constructed.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from broca.session.models import Message, MessageRole, MessageType
from broca.loop_engine.engine import DefaultLoopEngine


def _make_engine():
    engine = DefaultLoopEngine.__new__(DefaultLoopEngine)
    engine.agent_id = "test-agent"
    engine.session_manager = MagicMock()
    engine.session_manager.save_message = AsyncMock(return_value=True)
    return engine


def _make_message(data=None):
    return Message(
        message_type=MessageType.USER_MESSAGE,
        role=MessageRole.USER,
        sender_id="user",
        data=data if data is not None else {},
    )


@pytest.mark.asyncio
async def test_message_data_not_mutated():
    """_save_user_message does not modify the original message.data dict."""
    engine = _make_engine()
    original_data = {"key1": "value1", "key2": "value2"}
    message = _make_message(data=original_data.copy())

    user_msg = {"content": "hello", "raw_input": "raw text"}
    await engine._save_user_message(user_msg, message, "turn-1", from_agent=False)

    # Original data dict should be unchanged
    assert message.data == original_data
    assert "from_agent" not in message.data
    assert "raw_input" not in message.data


@pytest.mark.asyncio
async def test_saved_data_includes_from_agent():
    """The saved data includes from_agent and raw_input."""
    engine = _make_engine()
    message = _make_message(data={"original": "data"})

    user_msg = {"content": "hello", "raw_input": "raw"}
    await engine._save_user_message(user_msg, message, "turn-1", from_agent=True)

    # Verify what was passed to save_message
    call_kwargs = engine.session_manager.save_message.call_args[1]
    assert call_kwargs["data"]["from_agent"] is True
    assert call_kwargs["data"]["raw_input"] == "raw"
    assert call_kwargs["data"]["original"] == "data"


@pytest.mark.asyncio
async def test_original_message_id_preserved_for_user():
    """User messages (from_agent=False) use their original message_id."""
    engine = _make_engine()
    message = _make_message(data={})
    message.message_id = "msg_original_123"

    user_msg = {"content": "hello"}
    result = await engine._save_user_message(user_msg, message, "turn-1", from_agent=False)

    assert result == "msg_original_123"
    call_kwargs = engine.session_manager.save_message.call_args[1]
    assert call_kwargs["message_id"] == "msg_original_123"


@pytest.mark.asyncio
async def test_agent_message_gets_new_id():
    """Agent-sourced messages (from_agent=True) get a new pre-generated id."""
    engine = _make_engine()
    message = _make_message(data={})
    message.message_id = "msg_original"

    user_msg = {"content": "hello"}
    result = await engine._save_user_message(user_msg, message, "turn-1", from_agent=True)

    # Should be a new generated id, not the original
    assert result != "msg_original"
    assert result.startswith("msg_")
    call_kwargs = engine.session_manager.save_message.call_args[1]
    assert call_kwargs["message_id"] == result


@pytest.mark.asyncio
async def test_empty_data_handled():
    """Works correctly when message.data is empty or None-like."""
    engine = _make_engine()
    message = _make_message(data={})

    user_msg = {"content": "hello", "raw_input": "text"}
    await engine._save_user_message(user_msg, message, "turn-1", from_agent=False)

    call_kwargs = engine.session_manager.save_message.call_args[1]
    assert call_kwargs["data"]["from_agent"] is False
    assert call_kwargs["data"]["raw_input"] == "text"
    # Original message.data unchanged
    assert message.data == {}
