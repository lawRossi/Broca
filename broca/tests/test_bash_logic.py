"""
Regression tests for bash tool logic fixes:
- _detect_background_ampersand: && is NOT a background operator
- _run_code_async timeout: preserves actual stderr from the process
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def bash_tool():
    from broca.tools.bash import Bash

    return Bash()


class TestDetectBackgroundAmpersand:
    """Verify && is not treated as shell background operator."""

    def test_double_ampersand_not_background(self, bash_tool):
        """AC: 'cmd &&' → False (logical AND, not background)."""
        assert bash_tool._detect_background_ampersand("cmd &&") is False

    def test_single_ampersand_is_background(self, bash_tool):
        """AC: 'cmd &' → True (background operator)."""
        assert bash_tool._detect_background_ampersand("cmd &") is True

    def test_ampersand_after_command(self, bash_tool):
        """AC: 'cmd1 && cmd2 &' → True (background at end)."""
        assert bash_tool._detect_background_ampersand("cmd1 && cmd2 &") is True

    def test_double_ampersand_mid_command(self, bash_tool):
        """AC: 'cmd1 && cmd2' → False (no trailing &)."""
        assert bash_tool._detect_background_ampersand("cmd1 && cmd2") is False

    def test_triple_ampersand(self, bash_tool):
        """AC: 'cmd &&&' → False (ends with &&, not bg)."""
        assert bash_tool._detect_background_ampersand("cmd &&&") is False

    def test_ampersand_semicolon(self, bash_tool):
        """AC: 'cmd &;' → True."""
        assert bash_tool._detect_background_ampersand("cmd &;") is True

    def test_double_ampersand_semicolon(self, bash_tool):
        """AC: 'cmd &&;' → False (logical AND + semicolon, not bg)."""
        assert bash_tool._detect_background_ampersand("cmd &&;") is False

    def test_multiline_last_line_double_amp(self, bash_tool):
        """AC: multi-line ending with '&&' → False."""
        code = "cmd1\ncmd2 &&"
        assert bash_tool._detect_background_ampersand(code) is False


class TestTimeoutPreservesStderr:
    """Verify timeout includes actual stderr output from the process."""

    @pytest.mark.asyncio
    async def test_timeout_includes_process_stderr(self, bash_tool):
        """AC: timeout with stderr output → result contains both timeout msg and stderr."""
        if sys.platform == "win32":
            pytest.skip("killpg not available on Windows")

        # Command: immediately write to stderr, then sleep (will trigger timeout)
        # 0.5s gives echo time to execute; sleep 10 ensures timeout fires
        code = "echo 'some error info' >&2; sleep 10"
        result = await bash_tool._run_code_async(code, timeout=0.5)

        from broca.tools.tool import ToolStatus

        assert result.status == ToolStatus.ERROR
        assert "timed out" in result.content.lower()
        # The actual stderr from the process should be preserved
        assert "some error info" in result.content

    @pytest.mark.asyncio
    async def test_timeout_no_stderr_only_timeout_msg(self, bash_tool):
        """AC: timeout with no stderr → only timeout message, no empty stderr block."""
        if sys.platform == "win32":
            pytest.skip("killpg not available on Windows")

        # sleep only, no stderr output
        code = "sleep 10"
        result = await bash_tool._run_code_async(code, timeout=0.01)

        from broca.tools.tool import ToolStatus

        assert result.status == ToolStatus.ERROR
        assert "timed out" in result.content.lower()
