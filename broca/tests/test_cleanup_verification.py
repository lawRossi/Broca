"""Task 5.1 & 5.4: Cleanup verification tests.

Task 5.1 — typo / dead code / type annotation fixes:
  - No "memeory" typo remains in source
  - _check_write_ops removed from loop_engine (still in snapshot_hook)
  - send_tool_call arguments type is Optional[str]

Task 5.4 — AgentReferenceAdapter.__getattr__ warning:
  - Accessing known Agent attributes: no debug log
  - Accessing unknown attributes: debug log emitted
  - Passthrough behavior preserved
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Task 5.1: Typo / dead code verification
# ---------------------------------------------------------------------------


def _find_source_files(root: str) -> list[Path]:
    """Collect all .py files under root (excluding tests, venv, __pycache__)."""
    root_path = Path(root)
    skip_dirs = {"tests", "venv", "__pycache__", ".git", "node_modules", ".egg-info"}
    files = []
    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for fn in filenames:
            if fn.endswith(".py"):
                files.append(Path(dirpath) / fn)
    return files


class TestTask51TypoFix:
    """No 'memeory' typo remains in the broca source tree."""

    def test_no_memeory_typo(self) -> None:
        broca_dir = str(Path(__file__).resolve().parent.parent)
        for py_file in _find_source_files(broca_dir):
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            assert "memeory" not in content, (
                f"Typo 'memeory' found in {py_file}"
            )


class TestTask51DeadCode:
    """_check_write_ops removed from loop_engine (only in snapshot_hook)."""

    def test_check_write_ops_not_in_loop_engine(self) -> None:
        broca_dir = Path(__file__).resolve().parent.parent
        engine_file = broca_dir / "loop_engine" / "engine.py"
        if engine_file.exists():
            content = engine_file.read_text()
            # _check_write_ops should not be defined or called in engine.py
            assert "def _check_write_ops" not in content

    def test_check_write_ops_in_snapshot_hook(self) -> None:
        """_check_write_ops is a functional method in snapshot_hook (not dead)."""
        broca_dir = Path(__file__).resolve().parent.parent
        hook_file = broca_dir / "loop_engine" / "hooks" / "snapshot_hook.py"
        if hook_file.exists():
            content = hook_file.read_text()
            assert "_check_write_ops" in content


class TestTask51TypeAnnotation:
    """send_tool_call arguments is Optional[str]."""

    def test_send_tool_call_arguments_type(self) -> None:
        """Verify the source has `arguments: Optional[str]` for send_tool_call."""
        import broca.components.communicator as comm_module

        source = open(comm_module.__file__).read()
        # Find send_tool_call method and check its arguments parameter type
        assert "send_tool_call" in source, "send_tool_call not found in communicator"
        # Extract the method body (from def to next def or end of class)
        idx = source.index("send_tool_call")
        # Look within a reasonable window after the method name
        window = source[idx : idx + 500]
        assert "arguments" in window, (
            f"send_tool_call signature missing 'arguments': {window[:200]}"
        )
        assert "Optional[str]" in window or "str | None" in window, (
            f"send_tool_call arguments should be Optional[str]: {window[:200]}"
        )


# ---------------------------------------------------------------------------
# Task 5.4: AgentReferenceAdapter.__getattr__ warning behavior
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
