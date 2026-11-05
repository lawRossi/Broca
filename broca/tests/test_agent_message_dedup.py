"""
Regression tests: Agent._receive_message 消息去重。

验证 SocketIO 重连/retry 导致的重复 message_id 不会二次入队。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broca.session.models import Message, MessageRole, MessageType


def _make_agent():
    """创建一个最小 Agent 实例（跳过 create()，不连接 SocketIO）。"""
    from broca.agent import Agent

    agent = Agent.__new__(Agent)
    agent.config = MagicMock()
    agent.llm_client = MagicMock()
    agent.session_manager = MagicMock()
    agent.session_manager.session_id = "sess-test"
    agent.agent_id = "agent-test"
    agent.name = "test-agent"
    agent.role = "assistant"
    agent.status = Agent.STATUS_IDLE
    agent.session_id = "sess-test"
    agent.turn_id = None
    agent.total_input_tokens = 0
    agent.total_output_tokens = 0
    agent.total_llm_calls = 0
    agent.last_context_length = None
    agent.message_queue = asyncio.Queue(maxsize=100)
    agent._abort_task = None
    agent.running = False
    agent._run_lock = asyncio.Lock()
    agent.context_compressor = None
    agent.persistent_memory_manager = None
    agent._seen_message_ids = set()
    agent._DEDUP_MAX_SIZE = 2000
    return agent


def _make_message(msg_id: str) -> Message:
    """构造一个最小 Message 对象。"""
    msg = MagicMock(spec=Message)
    msg.message_id = msg_id
    msg.message_type = MessageType.USER_MESSAGE
    msg.role = MessageRole.USER
    msg.content = f"content-{msg_id}"
    return msg


class TestReceiveMessageDedup:
    """Agent._receive_message: 重复 message_id 被去重。"""

    @pytest.mark.asyncio
    async def test_first_message_enters_queue(self):
        """首次收到的消息正常入队。"""
        agent = _make_agent()
        msg = _make_message("msg-001")

        await agent._receive_message(msg)

        assert agent.message_queue.qsize() == 1
        queued = await agent.message_queue.get()
        assert queued.message_id == "msg-001"

    @pytest.mark.asyncio
    async def test_duplicate_message_deduplicated(self):
        """重复 message_id 不入队。"""
        agent = _make_agent()
        msg = _make_message("msg-001")

        await agent._receive_message(msg)
        await agent.message_queue.get()  # 取出，保持 queue 空

        # 第二次发送相同 message_id
        await agent._receive_message(msg)

        assert agent.message_queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_different_ids_both_queued(self):
        """不同 message_id 均正常入队。"""
        agent = _make_agent()

        await agent._receive_message(_make_message("msg-A"))
        await agent._receive_message(_make_message("msg-B"))

        assert agent.message_queue.qsize() == 2

    @pytest.mark.asyncio
    async def test_seen_set_bounded(self):
        """_seen_message_ids 不会无限增长（有上限淘汰）。"""
        agent = _make_agent()
        agent._DEDUP_MAX_SIZE = 10  # 缩小上限便于测试

        # 发送 15 个不同消息
        for i in range(15):
            await agent._receive_message(_make_message(f"msg-{i:03d}"))
            await agent.message_queue.get()  # 取出来避免 queue full

        # seen set 大小应受限于上限
        assert len(agent._seen_message_ids) <= 10
