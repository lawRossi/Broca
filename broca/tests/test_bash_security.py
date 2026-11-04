"""
Regression tests: bash tool background commands now go through security checks.

Fix: pre_execute_check no longer skips validation for background=true
or shell `&` commands.
"""

from unittest.mock import MagicMock, patch

import pytest


def _make_context():
    context = MagicMock()
    context.session_id = "session-1"
    context.workspace = "/tmp"
    context.agent = MagicMock()
    context.agent.agent_id = "agent-1"
    return context


class TestBashPreExecuteCheckBackground:
    """Verify pre_execute_check validates background commands uniformly."""

    def setup_method(self):
        self.tool = __import__("broca.tools.bash", fromlist=["Bash"]).Bash()
        self.context = _make_context()

    def test_dangerous_foreground_still_caught(self):
        """AC: rm -rf / (foreground) → returns permission message."""
        args = '{"code": "rm -rf /"}'
        result = self.tool.pre_execute_check(args, self.context)
        assert result is not None
        assert "rm" in result.lower() or "dangerous" in result.lower()

    def test_dangerous_background_caught(self):
        """AC: rm -rf / with background=True → returns permission message."""
        args = '{"code": "rm -rf /", "background": true}'
        result = self.tool.pre_execute_check(args, self.context)
        assert result is not None
        assert "rm" in result.lower() or "dangerous" in result.lower()

    def test_dangerous_shell_ampersand_caught(self):
        """AC: rm -rf / & → returns permission message (shell bg operator)."""
        args = '{"code": "rm -rf / &"}'
        result = self.tool.pre_execute_check(args, self.context)
        assert result is not None
        assert "rm" in result.lower() or "dangerous" in result.lower()

    def test_safe_foreground_passes(self):
        """AC: echo hello → returns None (safe)."""
        args = '{"code": "echo hello"}'
        result = self.tool.pre_execute_check(args, self.context)
        assert result is None

    def test_safe_background_passes(self):
        """AC: npm run dev with background=True → returns None (safe)."""
        args = '{"code": "npm run dev", "background": true}'
        result = self.tool.pre_execute_check(args, self.context)
        assert result is None

    def test_safe_shell_ampersand_passes(self):
        """AC: python server.py & → returns None (safe)."""
        args = '{"code": "python -m http.server 8080 &"}'
        result = self.tool.pre_execute_check(args, self.context)
        assert result is None

    def test_sudo_background_caught(self):
        """AC: sudo reboot with background=True → returns permission message."""
        args = '{"code": "sudo reboot", "background": true}'
        result = self.tool.pre_execute_check(args, self.context)
        assert result is not None

    def test_missing_code_returns_none(self):
        """AC: empty code → returns None (no validation needed)."""
        args = '{"code": ""}'
        result = self.tool.pre_execute_check(args, self.context)
        assert result is None
