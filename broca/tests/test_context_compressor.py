"""
ContextCompressor (SessionMemoryCompressor) 单元测试

覆盖：
- CompressionStats 类
- _estimate_context_tokens 估算
- check_and_compress 主流程
- force_compress 等价性
- keep_pivot 边界
- compressor_context_only (不传 agent)
- reset_session_memory
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from broca.context_compressor import (
    CompressionStats,
    SessionMemoryCompressor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cc_ctx(
    agent_id="agent-1",
    session_id="sess-1",
    provider="openai",
    model="gpt-4o",
    last_context_length=None,
    workspace="/tmp",
):
    """Build a minimal CompressorContext-compatible object."""
    compact_cfg = MagicMock()
    compact_cfg.session_trunc_threshold = 100000
    compact_cfg.session_trunc_percentage = 0.8
    compact_cfg.keep_steps = 5

    cc = MagicMock()
    cc.agent_id = agent_id
    cc.session_id = session_id
    cc.communicator = AsyncMock()
    cc.session_manager = AsyncMock()
    cc.compact_config = compact_cfg
    cc.provider = provider
    cc.model = model
    cc.workspace = workspace
    cc.last_context_length = last_context_length
    return cc


def _init_compressor(tmp_path, **kwargs):
    """Create and initialize a SessionMemoryCompressor for testing."""
    compressor = SessionMemoryCompressor()
    compressor._agent_id = kwargs.get("agent_id", "agent-1")
    compressor._session_id = kwargs.get("session_id", "sess-1")
    compressor._workspace = str(tmp_path)
    compressor._config = MagicMock()
    compressor._config.to_dict.return_value = {}
    compressor._initialized = True
    return compressor


# ---------------------------------------------------------------------------
# CompressionStats
# ---------------------------------------------------------------------------


class TestCompressionStats:
    def test_init(self):
        stats = CompressionStats()
        assert stats.truncated_count == 0
        assert stats.truncated_message_ids == []

    def test_reset(self):
        stats = CompressionStats(
            truncated_count=3,
            truncated_message_ids=["c"],
        )
        stats.reset()
        assert stats.truncated_count == 0
        assert stats.truncated_message_ids == []


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


class TestEstimateContextTokens:
    def test_empty_context(self):
        compressor = SessionMemoryCompressor()
        mock_context = MagicMock()
        mock_context.history = []
        result = compressor._estimate_context_tokens(mock_context)
        assert result == 0

    def test_simple_context(self):
        compressor = SessionMemoryCompressor()
        mock_context = MagicMock()
        mock_context.history = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello!"},
        ]
        result = compressor._estimate_context_tokens(mock_context)
        assert result > 0


# ---------------------------------------------------------------------------
# check_and_compress
# ---------------------------------------------------------------------------


class TestCheckAndCompress:
    @pytest.mark.asyncio
    async def test_check_and_compress_below_threshold(self, tmp_path):
        """Token count below threshold → no compression triggered."""
        compressor = _init_compressor(tmp_path)
        cc_ctx = _make_cc_ctx(last_context_length=100)

        mock_context = MagicMock()
        mock_context.history = [{"role": "user", "content": "hi"}]

        # session_manager mock for the pivot path (should not be reached)
        cc_ctx.session_manager.get_messages = AsyncMock(return_value=[])
        cc_ctx.session_manager.mark_messages_before_as_truncated = AsyncMock()

        stats = await compressor.check_and_compress(
            context=mock_context, compressor_context=cc_ctx
        )
        assert stats.truncated_count == 0

    @pytest.mark.asyncio
    async def test_check_and_compress_above_threshold(self, tmp_path):
        """Token count above threshold → compression pipeline triggered."""
        compressor = _init_compressor(tmp_path)

        # Set a very low threshold to trigger compression
        cc_ctx = _make_cc_ctx(last_context_length=200)
        cc_ctx.compact_config.session_trunc_threshold = 100
        cc_ctx.compact_config.session_trunc_percentage = 0.05

        mock_context = MagicMock()
        mock_context.history = [{"role": "user", "content": "hi" * 50}]
        mock_context.build_history_from_session = AsyncMock()

        # No messages in DB → pivot returns (None, None) → skip
        cc_ctx.session_manager.get_messages = AsyncMock(return_value=[])

        stats = await compressor.check_and_compress(
            context=mock_context, compressor_context=cc_ctx
        )
        # Pipeline entered but pivot returned None → no truncation
        assert stats.truncated_count == 0

    @pytest.mark.asyncio
    async def test_compressor_context_only(self, tmp_path):
        """Works with only CompressorContext (no Agent instance)."""
        compressor = _init_compressor(tmp_path)
        cc_ctx = _make_cc_ctx(last_context_length=50)

        mock_context = MagicMock()
        mock_context.history = []

        stats = await compressor.check_and_compress(
            context=mock_context, compressor_context=cc_ctx
        )
        assert stats.truncated_count == 0


# ---------------------------------------------------------------------------
# force_compress
# ---------------------------------------------------------------------------


class TestForceCompress:
    @pytest.mark.asyncio
    async def test_force_compress_equals_force_flag(self, tmp_path):
        """force_compress() and check_and_compress(force=True) are equivalent."""
        compressor1 = _init_compressor(tmp_path, agent_id="a1")
        compressor2 = _init_compressor(tmp_path, agent_id="a2")

        cc_ctx1 = _make_cc_ctx(last_context_length=50)
        cc_ctx1.session_manager.get_messages = AsyncMock(return_value=[])
        cc_ctx2 = _make_cc_ctx(last_context_length=50)
        cc_ctx2.session_manager.get_messages = AsyncMock(return_value=[])

        mock_context = MagicMock()
        mock_context.history = []

        stats1 = await compressor1.check_and_compress(
            context=mock_context, compressor_context=cc_ctx1, force=True
        )
        stats2 = await compressor2.force_compress(
            context=mock_context, compressor_context=cc_ctx2
        )
        assert stats1.truncated_count == stats2.truncated_count


# ---------------------------------------------------------------------------
# Keep pivot
# ---------------------------------------------------------------------------


class TestKeepPivot:
    @pytest.mark.asyncio
    async def test_keep_pivot_no_cross_turn(self, tmp_path):
        """Pivot never crosses into a previous turn."""
        from broca.session.models import MessageType

        compressor = _init_compressor(tmp_path)
        cc_ctx = _make_cc_ctx()

        # Messages: u1, a1, a2, a3 (prev turn), u2 (current turn start)
        messages = []
        for mid, mt in [
            ("u1", MessageType.USER_MESSAGE),
            ("a1", MessageType.AGENT_RESPONSE),
            ("a2", MessageType.AGENT_RESPONSE),
            ("a3", MessageType.AGENT_RESPONSE),
            ("u2", MessageType.USER_MESSAGE),
            ("a4", MessageType.AGENT_RESPONSE),
        ]:
            m = MagicMock()
            m.message_id = mid
            m.message_type = mt
            m.data = None
            messages.append(m)

        cc_ctx.session_manager.get_messages = AsyncMock(return_value=messages)
        mock_context = MagicMock()
        mock_context._message_db_ids = [None, "u1", "a1", "a2", "a3", "u2", "a4"]

        keep_from, keep_index = await compressor._compute_keep_pivot(
            mock_context, keep_steps=3, compressor_context=cc_ctx
        )
        # Current turn has 1 step (a4) ≤ keep_steps → keep entire current turn
        assert keep_from == "u2"
        assert keep_index == 5

    @pytest.mark.asyncio
    async def test_keep_pivot_within_keep_steps(self, tmp_path):
        """When steps > keep_steps, pivot at the keep_steps-th step back."""
        from broca.session.models import MessageType

        compressor = _init_compressor(tmp_path)
        cc_ctx = _make_cc_ctx()

        messages = []
        for mid, mt in [
            ("u1", MessageType.USER_MESSAGE),
            ("a1", MessageType.AGENT_RESPONSE),
            ("a2", MessageType.AGENT_RESPONSE),
            ("a3", MessageType.AGENT_RESPONSE),
            ("a4", MessageType.AGENT_RESPONSE),
        ]:
            m = MagicMock()
            m.message_id = mid
            m.message_type = mt
            m.data = None
            messages.append(m)

        cc_ctx.session_manager.get_messages = AsyncMock(return_value=messages)
        mock_context = MagicMock()
        mock_context._message_db_ids = [None, "u1", "a1", "a2", "a3", "a4"]

        keep_from, keep_index = await compressor._compute_keep_pivot(
            mock_context, keep_steps=2, compressor_context=cc_ctx
        )
        # keep_steps=2 → pivot at a3 (2 steps back from a4)
        assert keep_from == "a3"
        assert keep_index == 4


# ---------------------------------------------------------------------------
# reset_session_memory
# ---------------------------------------------------------------------------


class TestResetSessionMemory:
    def test_reset_session_memory(self, tmp_path):
        """reset_session_memory clears state and deletes files, then re-creates template."""
        compressor = _init_compressor(tmp_path)
        # Simulate existing files
        snapshot = Path(compressor.snapshot_memory_path)
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text("test content")

        compressor.reset_session_memory()

        # File should be re-created as template after deletion
        assert snapshot.exists()
        content = snapshot.read_text(encoding="utf-8")
        assert "# Session Title" in content  # default template marker

    def test_read_after_external_deletion(self, tmp_path):
        """Regression: _read_session_memory_content must not raise FileNotFoundError
        when the file was deleted externally (e.g. by old buggy reset or cleanup)."""
        compressor = _init_compressor(tmp_path)
        snapshot = Path(compressor.snapshot_memory_path)
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text("original")

        # Simulate external deletion (what the old buggy reset_session_memory did)
        snapshot.unlink()

        # Should re-create instead of raising
        content = compressor._read_session_memory_content()
        assert "# Session Title" in content
        assert Path(compressor.snapshot_memory_path).exists()


# ---------------------------------------------------------------------------
# Regression: sub-agent must be non-interactive (Bug: sub-agent events
# polluted main-agent turn cards in concise mode)
# ---------------------------------------------------------------------------


class TestSubAgentInteractiveDisabled:
    """Verify the session-memory sub-agent is created with interactive=False.

    Regression for: sub-agent's tool_call/agent_response events leaked to the
    frontend and appeared in the main agent's turn card.
    """

    @pytest.mark.asyncio
    async def test_new_sub_agent_config_has_interactive_false(self, tmp_path):
        """First-time creation sets interactive=False in agent_config."""
        compressor = _init_compressor(tmp_path)
        cc_ctx = _make_cc_ctx()

        # Mock: no existing agent config → triggers creation path
        cc_ctx.session_manager.get_agent_config = AsyncMock(return_value=None)

        # Mock the agent factory to capture the config
        mock_sub_agent = MagicMock()
        mock_sub_agent.running = True
        mock_sub_agent.config = MagicMock()
        mock_sub_agent.context = MagicMock()
        mock_sub_agent.run = AsyncMock()

        from unittest.mock import patch

        with patch(
            "broca.components.ComponentRegistry.get_instance"
        ) as mock_registry:
            mock_agent_factory = MagicMock()
            mock_agent_factory.create_agent = AsyncMock(return_value=mock_sub_agent)
            mock_registry.return_value.get.return_value = mock_agent_factory

            # Mock file I/O for _extract verification
            snapshot_path = Path(compressor.snapshot_memory_path)
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_path.write_text("original")

            # Make the sub-agent "modify" the file
            async def fake_run(msg, **kwargs):
                snapshot_path.write_text("updated content")
                from broca.loop_engine import ExecutionResult, ExecutionStatus
                return ExecutionResult(status=ExecutionStatus.COMPLETED)

            mock_sub_agent.run = AsyncMock(side_effect=fake_run)

            # Call _extract (the internal method that creates the sub-agent)
            old_history = [{"role": "user", "content": "test"}]
            result = await compressor._extract(old_history, cc_ctx)

        # Verify create_agent was called with interactive=False
        mock_agent_factory.create_agent.assert_called_once()
        call_kwargs = mock_agent_factory.create_agent.call_args.kwargs
        agent_config = call_kwargs["agent_config"]
        assert agent_config["interactive"] is False
        assert agent_config["role"] == "session_memory_manager"

    @pytest.mark.asyncio
    async def test_restored_sub_agent_gets_interactive_false(self, tmp_path):
        """Existing (restored) sub-agent also gets interactive=False override."""
        compressor = _init_compressor(tmp_path)
        cc_ctx = _make_cc_ctx()

        # Mock: existing agent config → triggers restore path
        existing_config = {
            "name": "session-memory-agent",
            "role": "session_memory_manager",
            "interactive": True,  # old config without the fix
        }
        cc_ctx.session_manager.get_agent_config = AsyncMock(
            return_value=existing_config
        )

        # Mock the restored sub-agent
        mock_sub_agent = MagicMock()
        mock_sub_agent.running = True
        mock_sub_agent.config = MagicMock()
        mock_sub_agent.config.interactive = True  # old value
        mock_sub_agent.context = MagicMock()

        from unittest.mock import patch

        with patch(
            "broca.components.ComponentRegistry.get_instance"
        ) as mock_registry:
            mock_agent_factory = MagicMock()
            mock_agent_factory.get_agent.return_value = mock_sub_agent
            mock_registry.return_value.get.return_value = mock_agent_factory

            snapshot_path = Path(compressor.snapshot_memory_path)
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_path.write_text("original")

            async def fake_run(msg, **kwargs):
                snapshot_path.write_text("updated")
                from broca.loop_engine import ExecutionResult, ExecutionStatus
                return ExecutionResult(status=ExecutionStatus.COMPLETED)

            mock_sub_agent.run = AsyncMock(side_effect=fake_run)

            old_history = [{"role": "user", "content": "test"}]
            await compressor._extract(old_history, cc_ctx)

        # The restored agent's config should be overridden to interactive=False
        assert mock_sub_agent.config.interactive is False


from pathlib import Path
