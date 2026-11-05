"""
Regression tests: _inject_user_message 广播必须设置 subscription。

根因：_inject_user_message 广播消息时未设 subscription，
导致 SocketIO server 走 _broadcast（发给所有客户端），
agent 自身的 SocketIO client 收到回显 → 消息重新入队 →
下一次 drain() 再次持久化同一个 message_id → UNIQUE constraint violated。

修复：广播消息必须设置 subscription=session_id，
使 server 走 _send_to_subscription 路由，只有显式订阅了该 session
的前端客户端能收到，agent 自身不会收到。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broca.session.models import Message, MessageRole, MessageType


def _make_engine():
    """创建一个最小 DefaultLoopEngine 实例，仅测试 _inject_user_message 的广播行为。"""
    from broca.loop_engine.engine import DefaultLoopEngine

    engine = DefaultLoopEngine.__new__(DefaultLoopEngine)
    engine.config = MagicMock()
    engine.config.interactive = True
    engine.config.provider = "openai"
    engine.config.model = "gpt-4o"
    engine.agent_id = "agent-test"
    engine.session_id = "sess-test-123"
    engine.turn_id = "turn-test-456"
    engine.llm_client = MagicMock()
    # parse_message 返回解析后的 user_message dict
    engine.llm_client.parse_message = MagicMock(
        return_value={"content": "hello", "raw_input": "hello"}
    )
    engine.session_manager = MagicMock()
    engine.session_manager.save_message = AsyncMock(return_value="msg-001")
    engine.context = MagicMock()
    engine.context.add_message = AsyncMock()
    engine.communicator = MagicMock()
    engine.communicator.send_message = AsyncMock()
    engine.abort_event = asyncio.Event()
    return engine


class TestInjectUserMessageBroadcast:
    """_inject_user_message 广播消息必须带 subscription 防止自回显。"""

    @pytest.mark.asyncio
    async def test_broadcast_has_subscription(self):
        """广播消息的 subscription 必须等于 engine.session_id。"""
        engine = _make_engine()

        # 构造入队消息
        incoming = MagicMock(spec=Message)
        incoming.message_id = "msg-dup-001"
        incoming.message_type = MessageType.USER_MESSAGE
        incoming.data = {"content": "hello", "from_agent": False}

        await engine._inject_user_message(incoming)

        # 验证 communicator.send_message 被调用
        assert engine.communicator.send_message.called, (
            "Expected broadcast via communicator.send_message"
        )
        broadcast_msg: Message = engine.communicator.send_message.call_args[0][0]

        # 核心断言：subscription 必须设置
        assert broadcast_msg.subscription == "sess-test-123", (
            f"Broadcast must set subscription=session_id to prevent self-echo. "
            f"Got subscription={broadcast_msg.subscription!r}"
        )
        # 其他字段也应正确
        assert broadcast_msg.message_id == "msg-dup-001"
        assert broadcast_msg.message_type == MessageType.USER_MESSAGE
        assert broadcast_msg.role == MessageRole.USER

    @pytest.mark.asyncio
    async def test_broadcast_not_called_when_not_interactive(self):
        """config.interactive=False 时不做广播。"""
        engine = _make_engine()
        engine.config.interactive = False

        incoming = MagicMock(spec=Message)
        incoming.message_id = "msg-dup-002"
        incoming.message_type = MessageType.USER_MESSAGE
        incoming.data = {"content": "world", "from_agent": False}

        await engine._inject_user_message(incoming)

        engine.communicator.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_broadcast_exception_does_not_crash(self):
        """广播失败不应影响消息持久化。"""
        engine = _make_engine()
        engine.communicator.send_message = AsyncMock(
            side_effect=ConnectionError("socket closed")
        )

        incoming = MagicMock(spec=Message)
        incoming.message_id = "msg-dup-003"
        incoming.message_type = MessageType.USER_MESSAGE
        incoming.data = {"content": "safe", "from_agent": False}

        # 不应抛出异常
        await engine._inject_user_message(incoming)

        # 持久化仍然成功
        assert engine.session_manager.save_message.called
