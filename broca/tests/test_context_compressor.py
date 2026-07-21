"""
ContextCompressor 单元测试

覆盖：
- CompressionStats 类
- _estimate_context_tokens 估算
- _get_effective_threshold 计算
- _is_tool_result_cleared 判断
- stale tool result 清理逻辑
- session memory 截断逻辑
"""

from unittest.mock import MagicMock

import pytest

from broca.context_compressor import (
    CompressionStats,
    ContextCompressor,
)


class TestCompressionStats:
    """测试 CompressionStats 数据类"""

    def test_init(self):
        """测试初始化"""
        stats = CompressionStats()
        assert stats.expired_count == 0
        assert stats.truncated_count == 0
        assert stats.expired_message_ids == []
        assert stats.truncated_message_ids == []

    def test_reset(self):
        """测试重置"""
        stats = CompressionStats(
            expired_count=5,
            truncated_count=3,
            expired_message_ids=["a", "b"],
            truncated_message_ids=["c"],
        )
        stats.reset()
        assert stats.expired_count == 0
        assert stats.truncated_count == 0
        assert stats.expired_message_ids == []
        assert stats.truncated_message_ids == []


class TestEstimateContextTokens:
    """测试 token 估算"""

    def test_empty_context(self):
        """测试空上下文"""
        compressor = ContextCompressor()
        mock_context = MagicMock()
        mock_context.history = []
        result = compressor._estimate_context_tokens(mock_context)
        assert result == 0

    def test_simple_context(self):
        """测试简单上下文"""
        compressor = ContextCompressor()
        mock_context = MagicMock()
        mock_context.history = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello!"},
        ]
        # 约 35 字符 / 3 ≈ 11 tokens
        result = compressor._estimate_context_tokens(mock_context)
        assert result > 0

    def test_context_with_llm_message(self):
        """测试包含 LLM Message 对象的上下文"""
        compressor = ContextCompressor()
        mock_context = MagicMock()

        class MockContent:
            def __len__(self):
                return 30

        mock_msg = MagicMock()
        mock_msg.content = "Some long content here for testing"
        mock_context.history = [mock_msg]

        result = compressor._estimate_context_tokens(mock_context)
        assert result >= 10


class TestIsToolResultCleared:
    """测试工具结果清除判断"""

    def test_cleared(self):
        """测试已清除"""
        compressor = ContextCompressor()
        msg = {"content": "[Expired tool result has been cleared]"}
        assert compressor._is_tool_result_cleared(msg) is True

    def test_not_cleared(self):
        """测试未清除"""
        compressor = ContextCompressor()
        msg = {"content": "Some real result"}
        assert compressor._is_tool_result_cleared(msg) is False

    def test_empty_content(self):
        """测试空内容"""
        compressor = ContextCompressor()
        msg = {"content": ""}
        assert compressor._is_tool_result_cleared(msg) is False


class TestExclusiveTools:
    """测试 EXCLUSIVE_TOOLS 常量"""

    def test_exclusive_tools_list(self):
        """测试排他工具列表"""
        assert "load_skill" in ContextCompressor.EXCLUSIVE_TOOLS
        assert "write_file" in ContextCompressor.EXCLUSIVE_TOOLS
        assert "edit_file" in ContextCompressor.EXCLUSIVE_TOOLS
        assert "ask_user" in ContextCompressor.EXCLUSIVE_TOOLS


class TestGetExpiredIndices:
    """测试获取过期索引"""

    def test_no_tool_results(self):
        """测试没有工具结果"""
        compressor = ContextCompressor()
        mock_context = MagicMock()
        mock_context.history = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ]
        config = MagicMock()
        config.min_recent_tool_results_to_keep = 2
        config.min_stale_messages = 5

        # history 长度 < min_stale_messages，应无过期
        expired = compressor._get_expired_indices(mock_context, 0, config)
        # stop_index=0 时不会有任何工具结果
        assert expired == []


class TestCheckAndCompress:
    """测试 check_and_compress 主方法"""

    @pytest.mark.asyncio
    async def test_no_compression_needed(self):
        """测试不需要压缩时"""
        compressor = ContextCompressor()
        mock_context = MagicMock()
        mock_context.history = [
            {"role": "system", "content": "sys"}
        ]

        mock_engine = MagicMock()
        mock_agent = MagicMock()
        mock_agent.config.provider = "openai"
        mock_agent.config.model = "gpt-4o"

        # 设置 compact_config 禁用压缩
        mock_compact = MagicMock()
        mock_compact.enable_stale_tool_cleanup = False
        mock_compact.enable_session_memory_truncation = False
        mock_agent.config.compact_config = mock_compact

        # 即使 force=True，因为两个策略都被禁用，应无操作
        stats = await compressor.check_and_compress(
            context=mock_context,
            execution_engine=mock_engine,
            agent=mock_agent,
            force=True,
        )
        assert stats.expired_count == 0
        assert stats.truncated_count == 0
