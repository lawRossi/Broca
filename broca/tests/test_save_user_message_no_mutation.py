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


@pytest.mark.asyncio
async def test_task_complete_from_agent_false_still_marks_from_agent():
    """TASK_COMPLETE with from_agent=False still gets from_agent=True in saved data
    and a new message_id (cross-agent PK collision guard)."""
    engine = _make_engine()
    message = Message(
        message_type=MessageType.TASK_COMPLETE,
        role=MessageRole.AGENT,
        data={"task_id": "t-1", "result": "done"},
    )
    message.message_id = "msg_sender_original"

    user_msg = {"role": "user", "content": "done", "raw_input": "done"}
    result = await engine._save_user_message(user_msg, message, "turn-1", from_agent=False)

    call_kwargs = engine.session_manager.save_message.call_args[1]
    # from_agent should be True (cross-agent task type)
    assert call_kwargs["data"]["from_agent"] is True
    # New message_id generated to avoid PK collision
    assert call_kwargs["message_id"] != "msg_sender_original"
    assert call_kwargs["message_id"].startswith("msg_")
    assert result == call_kwargs["message_id"]


@pytest.mark.asyncio
async def test_task_error_from_agent_false_still_marks_from_agent():
    """TASK_ERROR with from_agent=False still gets from_agent=True in saved data
    and a new message_id."""
    engine = _make_engine()
    message = Message(
        message_type=MessageType.TASK_ERROR,
        role=MessageRole.AGENT,
        data={"task_id": "t-2", "error_code": "E1"},
    )
    message.message_id = "msg_sender_original"

    user_msg = {"role": "user", "content": "E1", "raw_input": "E1"}
    result = await engine._save_user_message(user_msg, message, "turn-1", from_agent=False)

    call_kwargs = engine.session_manager.save_message.call_args[1]
    assert call_kwargs["data"]["from_agent"] is True
    assert call_kwargs["message_id"] != "msg_sender_original"
    assert call_kwargs["message_id"].startswith("msg_")
    assert result == call_kwargs["message_id"]


@pytest.mark.asyncio
async def test_user_message_from_agent_false_keeps_original_id():
    """USER_MESSAGE with from_agent=False keeps original message_id and from_agent=False."""
    engine = _make_engine()
    message = _make_message(data={"content": "hi"})
    message.message_id = "msg_user_abc"

    user_msg = {"role": "user", "content": "hi", "raw_input": "hi"}
    result = await engine._save_user_message(user_msg, message, "turn-1", from_agent=False)

    call_kwargs = engine.session_manager.save_message.call_args[1]
    assert call_kwargs["data"]["from_agent"] is False
    assert call_kwargs["message_id"] == "msg_user_abc"
    assert result == "msg_user_abc"
