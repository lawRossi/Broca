"""
SessionMemoryManager 保留边界 pivot 单元测试

覆盖：
- _compute_keep_pivot：保留最近 N 步、不跨 turn 的边界逻辑
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from broca.session.models import MessageType
from broca.session_memory.memory_manager import SessionMemoryManager


def make_msg(mid: str, mtype: MessageType, seq: int):
    m = MagicMock()
    m.message_id = mid
    m.message_type = mtype
    m.sequence_number = seq
    return m


def make_manager(tmp_path, messages):
    manager = SessionMemoryManager.__new__(SessionMemoryManager)
    manager.workspace = str(tmp_path)
    agent = MagicMock()
    agent.agent_id = "agent-1"
    agent.session_id = "session-1"
    agent.session_manager = MagicMock()
    agent.session_manager.get_messages = AsyncMock(return_value=messages)
    manager.agent = agent
    manager.config = MagicMock()
    manager.config.keep_steps = 5
    return manager


def make_context(db_ids):
    context = MagicMock()
    context._message_db_ids = db_ids
    return context


class TestComputeKeepPivot:
    @pytest.mark.asyncio
    async def test_truncate_earlier_steps_within_current_turn(self, tmp_path):
        """当前 turn 的 step 数 > keep_steps 时，保留最近 keep_steps 个 step"""
        messages = [
            make_msg("u1", MessageType.USER_MESSAGE, 0),
            make_msg("a1", MessageType.AGENT_RESPONSE, 1),
            make_msg("u2", MessageType.USER_MESSAGE, 2),  # current turn start
            make_msg("a2", MessageType.AGENT_RESPONSE, 3),
            make_msg("a3", MessageType.AGENT_RESPONSE, 4),
            make_msg("a4", MessageType.AGENT_RESPONSE, 5),
        ]
        manager = make_manager(tmp_path, messages)
        context = make_context(
            [None, "u1", "a1", "u2", "a2", "a3", "a4"]
        )

        keep_from, keep_index = await manager._compute_keep_pivot(context, keep_steps=2)
        # 保留最近 2 步：a3、a4；a2 及更早被截断
        assert keep_from == "a3"
        assert keep_index == 5

    @pytest.mark.asyncio
    async def test_keep_entire_current_turn(self, tmp_path):
        """当前 turn 的 step 数 ≤ keep_steps 时，保留整个当前 turn"""
        messages = [
            make_msg("u1", MessageType.USER_MESSAGE, 0),
            make_msg("a1", MessageType.AGENT_RESPONSE, 1),
            make_msg("u2", MessageType.USER_MESSAGE, 2),  # current turn start
            make_msg("a2", MessageType.AGENT_RESPONSE, 3),
        ]
        manager = make_manager(tmp_path, messages)
        context = make_context([None, "u1", "a1", "u2", "a2"])

        keep_from, keep_index = await manager._compute_keep_pivot(context, keep_steps=5)
        # 整体保留当前 turn，起点为用户消息 u2
        assert keep_from == "u2"
        assert keep_index == 3

    @pytest.mark.asyncio
    async def test_never_cross_turn(self, tmp_path):
        """即使上一轮 step 很多，也不跨 turn 截到上一轮"""
        messages = [make_msg("u1", MessageType.USER_MESSAGE, 0)]
        # 上一轮 5 个 step
        for i in range(5):
            messages.append(
                make_msg(f"a{i + 1}", MessageType.AGENT_RESPONSE, i + 1)
            )
        messages.append(make_msg("u2", MessageType.USER_MESSAGE, 6))  # current turn
        messages.append(make_msg("a6", MessageType.AGENT_RESPONSE, 7))

        manager = make_manager(tmp_path, messages)
        context = make_context(
            [None, "u1", "a1", "a2", "a3", "a4", "a5", "u2", "a6"]
        )

        keep_from, keep_index = await manager._compute_keep_pivot(context, keep_steps=3)
        # 当前 turn 只有 1 个 step，保留整个当前 turn（起点 u2），不跨到上一轮
        assert keep_from == "u2"
        assert keep_index == 7

    @pytest.mark.asyncio
    async def test_no_user_message_returns_none(self, tmp_path):
        """无 user message 时无法确定 turn 边界，返回 (None, None)"""
        messages = [
            make_msg("a1", MessageType.AGENT_RESPONSE, 0),
            make_msg("a2", MessageType.AGENT_RESPONSE, 1),
        ]
        manager = make_manager(tmp_path, messages)
        context = make_context([None, "a1", "a2"])

        keep_from, keep_index = await manager._compute_keep_pivot(context, keep_steps=2)
        assert keep_from is None
        assert keep_index is None

    @pytest.mark.asyncio
    async def test_unresolvable_context_index_returns_none(self, tmp_path):
        """无法在 context 中定位 pivot 消息时返回 (None, None)"""
        messages = [
            make_msg("u1", MessageType.USER_MESSAGE, 0),
            make_msg("a1", MessageType.AGENT_RESPONSE, 1),
            make_msg("a2", MessageType.AGENT_RESPONSE, 2),
        ]
        manager = make_manager(tmp_path, messages)
        # db_ids 中找不到 pivot 消息
        context = make_context([None, "u1", "a1"])

        keep_from, keep_index = await manager._compute_keep_pivot(context, keep_steps=1)
        assert keep_from is None
        assert keep_index is None
