"""AgentReferenceAdapter.__getattr__ warning behavior tests.

Previously this file also carried one-off "Task 5.1" source-text guards
(typo/dead-code/annotation string checks) that pinned a completed cleanup.
They were removed in the 2026-11 test-suite audit: they tested source strings
rather than behavior, some were silently skipped via ``if file.exists()``,
and they could never catch a real regression.  The behavior tests below are
kept.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# AgentReferenceAdapter.__getattr__ warning behavior
# ---------------------------------------------------------------------------


class TestAgentReferenceAdapterGetattr:
    """AgentReferenceAdapter.__getattr__ logs debug for unknown attrs only."""

    @staticmethod
    def _make_adapter():
        """Create a minimal AgentReferenceAdapter with a mock agent."""
        from broca.agent_reference import AgentReferenceAdapter

        mock_agent = MagicMock()
        mock_agent.agent_id = "agent-123"
        mock_agent.name = "test-agent"
        mock_agent.config = MagicMock()
        mock_agent.session_id = "sess-001"
        mock_agent.turn_id = None
        mock_agent.last_context_length = None
        mock_agent.some_very_unknown_attr = "unknown_value"
        return AgentReferenceAdapter(mock_agent), mock_agent

    def test_known_attr_no_debug_log(self) -> None:
        """Accessing a known attribute (e.g. 'name') should NOT log debug."""
        adapter, mock_agent = self._make_adapter()

        with patch(
            "broca.agent_reference.logger"
        ) as mock_logger:
            result = adapter.name
            assert result == "test-agent"
            # No debug log for known attrs
            mock_logger.debug.assert_not_called()

    def test_known_attr_config(self) -> None:
        """Accessing 'config' (in _KNOWN_AGENT_ATTRS) → no debug log."""
        adapter, mock_agent = self._make_adapter()

        with patch("broca.agent_reference.logger") as mock_logger:
            result = adapter.config
            assert result is mock_agent.config
            mock_logger.debug.assert_not_called()

    def test_unknown_attr_debug_log(self) -> None:
        """Accessing an unknown attribute SHOULD log debug."""
        adapter, mock_agent = self._make_adapter()

        with patch("broca.agent_reference.logger") as mock_logger:
            result = adapter.some_very_unknown_attr
            assert result == "unknown_value"
            mock_logger.debug.assert_called_once()
            # logger.debug(format_string, name) — the attr name is in call args
            call_args = mock_logger.debug.call_args
            all_args_str = str(call_args)
            assert "some_very_unknown_attr" in all_args_str

    def test_passthrough_behavior_preserved(self) -> None:
        """__getattr__ still proxies to the underlying agent."""
        adapter, mock_agent = self._make_adapter()

        # Known attrs go through __getattr__ or explicit properties
        assert adapter.agent_id == "agent-123"
        assert adapter.session_id == "sess-001"

    def test_repr(self) -> None:
        """__repr__ works without triggering __getattr__."""
        adapter, _ = self._make_adapter()
        assert "AgentReferenceAdapter" in repr(adapter)
        assert "agent-123" in repr(adapter)

    def test_known_attrs_frozenset_contents(self) -> None:
        """_KNOWN_AGENT_ATTRS contains the expected attributes."""
        from broca.agent_reference import AgentReferenceAdapter

        expected = {
            "name", "config", "agent_id", "session_id", "turn_id",
            "llm_client", "tool_mapping", "tools", "status",
            "context", "communicator", "session_manager",
        }
        assert expected.issubset(AgentReferenceAdapter._KNOWN_AGENT_ATTRS)
