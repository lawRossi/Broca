"""Tests for the SandboxToolExecutor example plugin."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from sandbox_executor import SandboxToolExecutor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def executor():
    """Create and initialize a SandboxToolExecutor."""
    ex = SandboxToolExecutor()

    class FakeTool:
        name = "test_tool"

        async def execute(self, arguments_dict, context):
            return "hello from sandbox"

    tool_mapping = {"test_tool": FakeTool()}

    perm = MagicMock()
    perm.get_permission = MagicMock(return_value="allow")

    comm = AsyncMock()
    comm.send_tool_call = AsyncMock(return_value="msg-1")

    async def _init():
        await ex.initialize(
            tool_mapping=tool_mapping,
            permission_provider=perm,
            config=MagicMock(),
            communicator=comm,
        )

    asyncio.run(_init())
    return ex


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSandboxToolExecutor:
    def test_initialize(self, executor):
        """executor is initialized with all deps."""
        assert executor._initialized is True
        assert "test_tool" in executor._tool_mapping

    def test_execute_success(self, executor):
        """Successful tool execution in sandbox."""
        from broca.tools.tool import ToolStatus, ToolCallContext

        ctx = ToolCallContext()
        ctx.agent_id = "test"
        ctx.turn_id = "turn-1"
        ctx.agent = None

        async def _run():
            return await executor.execute_tool(
                tool_name="test_tool",
                arguments="{}",
                tool_call_id="call-1",
                context=ctx,
                tool=None,
                allowed_tools=None,
            )

        outcome = asyncio.run(_run())
        assert outcome.result.status == ToolStatus.SUCCESS
        assert "sandbox" in outcome.result.content

    def test_execute_unknown_tool(self, executor):
        """Unknown tool returns error."""
        from broca.tools.tool import ToolStatus, ToolCallContext

        ctx = ToolCallContext()
        ctx.agent_id = "test"
        ctx.turn_id = "turn-1"
        ctx.agent = None

        async def _run():
            return await executor.execute_tool(
                tool_name="nonexistent",
                arguments="{}",
                tool_call_id="call-2",
                context=ctx,
                tool=None,
                allowed_tools=None,
            )

        outcome = asyncio.run(_run())
        assert outcome.result.status == ToolStatus.ERROR

    def test_execute_forbidden(self, executor):
        """Forbidden tool is blocked."""
        executor._permission_provider.get_permission = MagicMock(
            return_value="forbidden"
        )

        from broca.tools.tool import ToolStatus, ToolCallContext

        ctx = ToolCallContext()
        ctx.agent_id = "test"
        ctx.turn_id = "turn-1"
        ctx.agent = None

        async def _run():
            return await executor.execute_tool(
                tool_name="test_tool",
                arguments="{}",
                tool_call_id="call-3",
                context=ctx,
                tool=None,
                allowed_tools=None,
            )

        outcome = asyncio.run(_run())
        assert outcome.result.status == ToolStatus.ERROR
        assert "forbidden" in outcome.result.content

    def test_get_permission_delegates(self, executor):
        """get_permission delegates to permission_provider."""
        assert executor.get_permission("test_tool") == "allow"

    def test_is_readonly(self, executor):
        """Readonly tool detection."""
        assert executor.is_readonly_tool("read_file") is True
        assert executor.is_readonly_tool("bash") is False

    def test_shutdown(self, executor):
        """shutdown resets the executor."""
        asyncio.run(executor.shutdown())
        assert executor._initialized is False
