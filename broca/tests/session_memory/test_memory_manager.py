"""
SessionMemory 保留边界 pivot 单元测试

Phase 3: pivot 逻辑已迁入 SessionMemoryCompressor。
本文件测试 SessionMemoryCompressor._compute_keep_pivot()。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from broca.context_compressor import SessionMemoryCompressor
from broca.session.models import MessageType


def make_msg(mid: str, mtype: MessageType, seq: int):
    m = MagicMock()
    m.message_id = mid
    m.message_type = mtype
    m.sequence_number = seq
    m.data = None
    return m


def make_compressor(tmp_path, messages):
    """Create an initialized SessionMemoryCompressor with mocked session_manager."""
    compressor = SessionMemoryCompressor()
    compressor._agent_id = "agent-1"
    compressor._session_id = "session-1"
    compressor._workspace = str(tmp_path)
    compressor._config = MagicMock()
    compressor._config.to_dict.return_value = {}
    compressor._initialized = True

    cc_ctx = MagicMock()
    cc_ctx.session_manager = MagicMock()
    cc_ctx.session_manager.get_messages = AsyncMock(return_value=messages)
    cc_ctx.session_manager.session_id = "session-1"
    return compressor, cc_ctx


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
        compressor, cc_ctx = make_compressor(tmp_path, messages)
        context = make_context(
            [None, "u1", "a1", "u2", "a2", "a3", "a4"]
        )

        keep_from, keep_index = await compressor._compute_keep_pivot(
            context, keep_steps=2, compressor_context=cc_ctx
        )
        assert keep_from == "a3"
        assert keep_index == 5

    @pytest.mark.asyncio
    async def test_keep_entire_current_turn(self, tmp_path):
        """当前 turn 的 step 数 ≤ keep_steps 时，保留整个当前 turn"""
        messages = [
            make_msg("u1", MessageType.USER_MESSAGE, 0),
            make_msg("a1", MessageType.AGENT_RESPONSE, 1),
            make_msg("u2", MessageType.USER_MESSAGE, 2),
            make_msg("a2", MessageType.AGENT_RESPONSE, 3),
        ]
        compressor, cc_ctx = make_compressor(tmp_path, messages)
        context = make_context([None, "u1", "a1", "u2", "a2"])

        keep_from, keep_index = await compressor._compute_keep_pivot(
            context, keep_steps=5, compressor_context=cc_ctx
        )
        assert keep_from == "u2"
        assert keep_index == 3

    @pytest.mark.asyncio
    async def test_never_cross_turn(self, tmp_path):
        """即使上一轮 step 很多，也不跨 turn 截到上一轮"""
        messages = [make_msg("u1", MessageType.USER_MESSAGE, 0)]
        for i in range(5):
            messages.append(
                make_msg(f"a{i + 1}", MessageType.AGENT_RESPONSE, i + 1)
            )
        messages.append(make_msg("u2", MessageType.USER_MESSAGE, 6))
        messages.append(make_msg("a6", MessageType.AGENT_RESPONSE, 7))

        compressor, cc_ctx = make_compressor(tmp_path, messages)
        context = make_context(
            [None, "u1", "a1", "a2", "a3", "a4", "a5", "u2", "a6"]
        )

        keep_from, keep_index = await compressor._compute_keep_pivot(
            context, keep_steps=3, compressor_context=cc_ctx
        )
        assert keep_from == "u2"
        assert keep_index == 7

    @pytest.mark.asyncio
    async def test_no_user_message_returns_none(self, tmp_path):
        """无 user message 时返回 (None, None)"""
        messages = [
            make_msg("a1", MessageType.AGENT_RESPONSE, 0),
            make_msg("a2", MessageType.AGENT_RESPONSE, 1),
        ]
        compressor, cc_ctx = make_compressor(tmp_path, messages)
        context = make_context([None, "a1", "a2"])

        keep_from, keep_index = await compressor._compute_keep_pivot(
            context, keep_steps=2, compressor_context=cc_ctx
        )
        assert keep_from is None
        assert keep_index is None

    @pytest.mark.asyncio
    async def test_pivot_not_in_context_resolved_by_order(self, tmp_path):
        """pivot 消息不在 context 中时，按 DB 顺序定位"""
        messages = [
            make_msg("u1", MessageType.USER_MESSAGE, 0),
            make_msg("a1", MessageType.AGENT_RESPONSE, 1),
            make_msg("a2", MessageType.AGENT_RESPONSE, 2),
        ]
        compressor, cc_ctx = make_compressor(tmp_path, messages)
        context = make_context([None, "u1", "a1"])

        keep_from, keep_index = await compressor._compute_keep_pivot(
            context, keep_steps=1, compressor_context=cc_ctx
        )
        assert keep_from == "a2"
        assert keep_index == 3

    @pytest.mark.asyncio
    async def test_no_db_ids_returns_none(self, tmp_path):
        """context 无 _message_db_ids 时返回 (None, None)"""
        messages = [
            make_msg("u1", MessageType.USER_MESSAGE, 0),
            make_msg("a1", MessageType.AGENT_RESPONSE, 1),
        ]
        compressor, cc_ctx = make_compressor(tmp_path, messages)
        context = make_context(None)

        keep_from, keep_index = await compressor._compute_keep_pivot(
            context, keep_steps=1, compressor_context=cc_ctx
        )
        assert keep_from is None
        assert keep_index is None

    @pytest.mark.asyncio
    async def test_turn_end_compresses_entire_turn(self, tmp_path):
        """最后一条是 TURN_END 时，整个 turn 全部送入压缩"""
        messages = [
            make_msg("u1", MessageType.USER_MESSAGE, 0),
            make_msg("a1", MessageType.AGENT_RESPONSE, 1),
            make_msg("a2", MessageType.AGENT_RESPONSE, 2),
            make_msg("t1", MessageType.TURN_END, 3),
        ]
        compressor, cc_ctx = make_compressor(tmp_path, messages)
        context = make_context([None, "u1", "a1", "a2"])

        keep_from, keep_index = await compressor._compute_keep_pivot(
            context, keep_steps=5, compressor_context=cc_ctx
        )
        assert keep_from == "t1"
        assert keep_index == 4
