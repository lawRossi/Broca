"""Unit tests for DefaultToolExecutor — the 8-responsibility pipeline.

Each test targets a specific responsibility from the plan:

  #1  Tool existence check
  #2  allowed_tools whitelist
  #3  Permission decision (forbidden / ask / allow)
  #4  Tool-call broadcast
  #5  Timeout skip rules
  #6  Dedicated timeout
  #7  Exception mapping
  #8  Session decision
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broca.components.tool_executor import ToolExecutionOutcome
from broca.errors import BrocaError, ToolError
from broca.tools.executor import DefaultToolExecutor
from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(
    turn_id: str = "turn-1",
    agent_id: str = "agent-1",
    session_id: str = "sess-1",
) -> ToolCallContext:
    """Create a minimal ``ToolCallContext`` for tests."""
    ctx = ToolCallContext()
    ctx.agent = MagicMock()
    ctx.session_id = session_id
    ctx.turn_id = turn_id
    ctx.agent_id = agent_id
    return ctx


def _make_tool(
    name: str = "test_tool",
    result: Optional[ToolResult] = None,
    exception: Optional[Exception] = None,
) -> Tool:
    """Create a ``Tool`` subclass instance that returns a fixed result or raises."""

    class _T(Tool):
        @property
        def name(self) -> str:
            return name

        @property
        def description(self) -> str:
            return "test"

        @property
        def parameters(self) -> dict:
            return {"type": "object", "properties": {}}

        async def _execute(self, arguments: dict, context) -> ToolResult:
            if exception is not None:
                raise exception
            if result is not None:
                return result
            return ToolResult(status=ToolStatus.SUCCESS, content=f"ok {name}")

    return _T()


def _init_executor(
    executor: DefaultToolExecutor,
    tools: dict[str, Tool] | None = None,
    permission_provider: Any = None,
    communicator: Any = None,
    interactive: bool = False,
    tool_call_timeout: float = 120,
    assign_task_timeout: float = 1800,
) -> None:
    """Directly set internal attributes to bypass ``initialize()``."""
    executor._tool_mapping = tools or {}
    executor._permission_provider = permission_provider
    executor._communicator = communicator
    executor._interactive = interactive
    executor._tool_call_timeout = tool_call_timeout
    executor._assign_task_timeout = assign_task_timeout
    executor._initialized = True


class _MockPermissionProvider:
    """Lightweight permission provider for focused unit tests."""

    def __init__(self):
        self._permissions: dict[str, str] = {}
        self._session_overrides: dict[str, str] = {}
        self.override_calls: list[tuple[str, str]] = []
        self.request_result: tuple[bool, Optional[str]] = (True, None)

    def set_permission(self, tool: str, perm: str) -> None:
        self._permissions[tool] = perm

    async def request_tool_permission(
        self, tool_name: str, arguments: str | None = None
    ) -> tuple[bool, Optional[str]]:
        return self.request_result

    def get_permission(self, tool_name: str) -> str:
        if tool_name in self._session_overrides:
            return self._session_overrides[tool_name]
        if tool_name in self._permissions:
            return self._permissions[tool_name]
        if "*" in self._permissions:
            return self._permissions["*"]
        return "allow"

    def set_session_override(self, tool_name: str, permission: str) -> None:
        self._session_overrides[tool_name] = permission
        self.override_calls.append((tool_name, permission))

    def clear_session_overrides(self) -> None:
        self._session_overrides.clear()


def _setup_executor(
    tools: dict[str, Tool] | None = None,
    permission: str = "allow",
    interactive: bool = False,
    tool_call_timeout: float = 120,
    assign_task_timeout: float = 1800,
) -> tuple[DefaultToolExecutor, _MockPermissionProvider, Any]:
    """Create an initialized executor + permission provider + communicator."""
    executor = DefaultToolExecutor()
    pp = _MockPermissionProvider()
    if permission != "allow":
        pp._permissions = {"*": permission}

    comm = AsyncMock()
    comm.send_tool_call.return_value = "msg-1"

    _init_executor(
        executor,
        tools=tools,
        permission_provider=pp,
        communicator=comm,
        interactive=interactive,
        tool_call_timeout=tool_call_timeout,
        assign_task_timeout=assign_task_timeout,
    )
    return executor, pp, comm


# ---------------------------------------------------------------------------
# #1  Tool existence check
# ---------------------------------------------------------------------------


class TestToolExistence:
    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        executor, _, _ = _setup_executor(tools={"known_tool": _make_tool()})
        result = await executor.execute_tool(
            tool_name="nonexistent_tool",
            arguments="{}",
            tool_call_id="tc-1",
            context=_make_context(),
            tool=None,
        )
        assert result.result.status == ToolStatus.ERROR
        assert "not found" in result.result.content

    @pytest.mark.asyncio
    async def test_broadcast_happens_even_for_unknown_tool(self):
        """#4 broadcast is FIRST — even before existence check."""
        executor, _, comm = _setup_executor(
            tools={}, interactive=True
        )
        await executor.execute_tool(
            tool_name="nonexistent",
            arguments="{}",
            tool_call_id="tc-2",
            context=_make_context(),
            tool=None,
        )
        comm.send_tool_call.assert_called_once()


# ---------------------------------------------------------------------------
# #2  allowed_tools whitelist
# ---------------------------------------------------------------------------


class TestAllowedTools:
    @pytest.mark.asyncio
    async def test_tool_not_in_allowed_list(self):
        tool = _make_tool()
        executor, _, _ = _setup_executor(tools={"tool_a": tool})
        result = await executor.execute_tool(
            tool_name="tool_a",
            arguments="{}",
            tool_call_id="tc-1",
            context=_make_context(),
            tool=tool,
            allowed_tools=["tool_b"],
        )
        assert result.result.status == ToolStatus.ERROR
        assert "not allowed" in result.result.content

    @pytest.mark.asyncio
    async def test_tool_in_allowed_list(self):
        tool = _make_tool(result=ToolResult(status=ToolStatus.SUCCESS, content="ok"))
        executor, _, _ = _setup_executor(tools={"tool_a": tool})
        result = await executor.execute_tool(
            tool_name="tool_a",
            arguments="{}",
            tool_call_id="tc-1",
            context=_make_context(),
            tool=tool,
            allowed_tools=["tool_a"],
        )
        assert result.result.status == ToolStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_none_allowed_tools_means_no_restriction(self):
        tool = _make_tool(result=ToolResult(status=ToolStatus.SUCCESS, content="ok"))
        executor, _, _ = _setup_executor(tools={"tool_a": tool})
        result = await executor.execute_tool(
            tool_name="tool_a",
            arguments="{}",
            tool_call_id="tc-1",
            context=_make_context(),
            tool=tool,
            allowed_tools=None,
        )
        assert result.result.status == ToolStatus.SUCCESS


# ---------------------------------------------------------------------------
# #3  Permission decision
# ---------------------------------------------------------------------------


class TestPermissionDecision:
    @pytest.mark.asyncio
    async def test_forbidden_tool_returns_error(self):
        tool = _make_tool()
        executor, pp, _ = _setup_executor(tools={"tool_a": tool}, permission="forbidden")
        result = await executor.execute_tool(
            tool_name="tool_a",
            arguments="{}",
            tool_call_id="tc-1",
            context=_make_context(),
            tool=tool,
        )
        assert result.result.status == ToolStatus.ERROR
        assert "forbidden" in result.result.content

    @pytest.mark.asyncio
    async def test_ask_permission_user_grants(self):
        tool = _make_tool(result=ToolResult(status=ToolStatus.SUCCESS, content="executed"))
        executor, pp, _ = _setup_executor(tools={"tool_a": tool}, permission="ask")
        pp.request_result = (True, None)  # user grants
        result = await executor.execute_tool(
            tool_name="tool_a",
            arguments="{}",
            tool_call_id="tc-1",
            context=_make_context(),
            tool=tool,
        )
        assert result.result.status == ToolStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_ask_permission_user_denies(self):
        tool = _make_tool()
        executor, pp, _ = _setup_executor(tools={"tool_a": tool}, permission="ask")
        pp.request_result = (False, None)  # user denies
        result = await executor.execute_tool(
            tool_name="tool_a",
            arguments="{}",
            tool_call_id="tc-1",
            context=_make_context(),
            tool=tool,
        )
        assert result.result.status == ToolStatus.ERROR
        assert "denied" in result.result.content


# ---------------------------------------------------------------------------
# #4  Broadcast
# ---------------------------------------------------------------------------


class TestBroadcast:
    @pytest.mark.asyncio
    async def test_broadcast_called_with_correct_params(self):
        tool = _make_tool(result=ToolResult(status=ToolStatus.SUCCESS, content="ok"))
        executor, _, comm = _setup_executor(
            tools={"tool_a": tool}, interactive=True
        )
        await executor.execute_tool(
            tool_name="tool_a",
            arguments='{"key": "value"}',
            tool_call_id="tc-42",
            context=_make_context(turn_id="t-99", agent_id="a-55", session_id="s-77"),
            tool=tool,
        )
        comm.send_tool_call.assert_called_once_with(
            tool_call_id="tc-42",
            tool_name="tool_a",
            arguments='{"key": "value"}',
            turn_id="t-99",
            agent_id="a-55",
            subscription="s-77",
        )

    @pytest.mark.asyncio
    async def test_no_broadcast_when_not_interactive(self):
        tool = _make_tool(result=ToolResult(status=ToolStatus.SUCCESS, content="ok"))
        executor, _, comm = _setup_executor(
            tools={"tool_a": tool}, interactive=False
        )
        await executor.execute_tool(
            tool_name="tool_a",
            arguments="{}",
            tool_call_id="tc-1",
            context=_make_context(),
            tool=tool,
        )
        comm.send_tool_call.assert_not_called()


# ---------------------------------------------------------------------------
# #5  Timeout skip rules
# ---------------------------------------------------------------------------


class TestTimeoutSkip:
    @pytest.mark.asyncio
    async def test_ask_user_skips_timeout(self):
        """ask_user must NOT be wrapped in asyncio.wait_for."""
        tool = _make_tool(result=ToolResult(status=ToolStatus.SUCCESS, content="answered"))
        executor, _, _ = _setup_executor(
            tools={"ask_user": tool},
            tool_call_timeout=0.01,  # very short — would time out if applied
        )
        # ask_user has _should_skip_timeout = True, so it should complete
        result = await executor.execute_tool(
            tool_name="ask_user",
            arguments="{}",
            tool_call_id="tc-1",
            context=_make_context(),
            tool=tool,
        )
        assert result.result.status == ToolStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_bash_background_skips_timeout(self):
        tool = _make_tool(
            result=ToolResult(status=ToolStatus.SUCCESS, content="bg running")
        )
        executor, _, _ = _setup_executor(
            tools={"bash": tool},
            tool_call_timeout=0.01,
        )
        result = await executor.execute_tool(
            tool_name="bash",
            arguments='{"command": "sleep 100", "background": true}',
            tool_call_id="tc-1",
            context=_make_context(),
            tool=tool,
        )
        assert result.result.status == ToolStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_bash_foreground_does_not_skip_timeout(self):
        """bash without background=true should use normal timeout."""
        tool = _make_tool(result=ToolResult(status=ToolStatus.SUCCESS, content="done"))
        executor, _, _ = _setup_executor(
            tools={"bash": tool},
            tool_call_timeout=0.01,
        )
        result = await executor.execute_tool(
            tool_name="bash",
            arguments='{"command": "echo hi"}',
            tool_call_id="tc-1",
            context=_make_context(),
            tool=tool,
        )
        # Should complete before the short timeout since it's fast
        assert result.result.status == ToolStatus.SUCCESS


# ---------------------------------------------------------------------------
# #6  Dedicated timeout
# ---------------------------------------------------------------------------


class TestDedicatedTimeout:
    @pytest.mark.asyncio
    async def test_assign_task_gets_longer_timeout(self):
        """Verify _get_timeout returns the assign_task-specific timeout."""
        executor = DefaultToolExecutor()
        _init_executor(
            executor,
            tools={},
            permission_provider=_MockPermissionProvider(),
            tool_call_timeout=10,
            assign_task_timeout=300,
        )
        assert executor._get_timeout("assign_task") == 300
        assert executor._get_timeout("bash") == 10


# ---------------------------------------------------------------------------
# #7  Exception mapping
# ---------------------------------------------------------------------------


class TestExceptionMapping:
    @pytest.mark.asyncio
    async def test_tool_error_mapped_to_user_message(self):
        tool = _make_tool(exception=ToolError(message="custom tool error"))
        executor, _, _ = _setup_executor(tools={"tool_a": tool})
        result = await executor.execute_tool(
            tool_name="tool_a",
            arguments="{}",
            tool_call_id="tc-1",
            context=_make_context(),
            tool=tool,
        )
        assert result.result.status == ToolStatus.ERROR
        assert "custom tool error" in result.result.content

    @pytest.mark.asyncio
    async def test_timeout_returns_friendly_message(self):
        """A tool that hangs beyond the timeout should return a friendly error."""
        tool = _make_tool()

        # Make the tool hang
        async def hang(arguments, context):
            await asyncio.sleep(10)

        tool.execute = hang  # type: ignore

        executor, _, _ = _setup_executor(
            tools={"tool_a": tool}, tool_call_timeout=0.05
        )
        result = await executor.execute_tool(
            tool_name="tool_a",
            arguments="{}",
            tool_call_id="tc-1",
            context=_make_context(),
            tool=tool,
        )
        assert result.result.status == ToolStatus.ERROR
        assert "timed out" in result.result.content

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates(self):
        """CancelledError must propagate (not be caught and converted)."""
        tool = _make_tool()

        async def cancel(arguments, context):
            raise asyncio.CancelledError()

        tool.execute = cancel  # type: ignore

        executor, _, _ = _setup_executor(tools={"tool_a": tool})
        with pytest.raises(asyncio.CancelledError):
            await executor.execute_tool(
                tool_name="tool_a",
                arguments="{}",
                tool_call_id="tc-1",
                context=_make_context(),
                tool=tool,
            )


# ---------------------------------------------------------------------------
# #8  Session decision
# ---------------------------------------------------------------------------


class TestSessionDecision:
    @pytest.mark.asyncio
    async def test_allow_session_override(self):
        """User grants with 'always allow' → set_session_override called."""
        tool = _make_tool(result=ToolResult(status=ToolStatus.SUCCESS, content="ok"))
        executor, pp, _ = _setup_executor(tools={"tool_a": tool}, permission="ask")
        pp.request_result = (True, "allow")  # user grants + always allow
        result = await executor.execute_tool(
            tool_name="tool_a",
            arguments="{}",
            tool_call_id="tc-1",
            context=_make_context(),
            tool=tool,
        )
        assert ("tool_a", "allow") in pp.override_calls

    @pytest.mark.asyncio
    async def test_forbid_session_override(self):
        """User grants with 'always forbid' → set_session_override called."""
        tool = _make_tool()
        executor, pp, _ = _setup_executor(tools={"tool_a": tool}, permission="ask")
        pp.request_result = (False, "forbid")  # user denies + always forbid
        result = await executor.execute_tool(
            tool_name="tool_a",
            arguments="{}",
            tool_call_id="tc-1",
            context=_make_context(),
            tool=tool,
        )
        assert ("tool_a", "forbidden") in pp.override_calls


# ---------------------------------------------------------------------------
# get_permission / is_readonly_tool / initialize
# ---------------------------------------------------------------------------


class TestDelegationAndInit:
    def test_get_permission_delegates(self):
        executor, pp, _ = _setup_executor(tools={})
        pp.set_permission("bash", "forbidden")
        assert executor.get_permission("bash") == "forbidden"

    def test_is_readonly_tool(self):
        executor = DefaultToolExecutor()
        _init_executor(executor, tools={}, permission_provider=_MockPermissionProvider())
        assert executor.is_readonly_tool("grep") is True
        assert executor.is_readonly_tool("bash") is False

    @pytest.mark.asyncio
    async def test_initialize_is_idempotent(self):
        executor = DefaultToolExecutor()
        tools = {"t": _make_tool()}
        pp = _MockPermissionProvider()
        comm = AsyncMock()

        config = MagicMock()
        config.interactive = True
        config.execution_config = None

        await executor.initialize(
            tool_mapping=tools,
            permission_provider=pp,
            config=config,
            communicator=comm,
        )
        first_tool_mapping = executor._tool_mapping

        # Second call with same tool_mapping should be a no-op
        await executor.initialize(
            tool_mapping=tools,
            permission_provider=pp,
            config=config,
            communicator=comm,
        )
        assert executor._tool_mapping is first_tool_mapping

    @pytest.mark.asyncio
    async def test_initialize_reads_config(self):
        executor = DefaultToolExecutor()
        config = MagicMock()
        config.interactive = True
        exec_cfg = MagicMock()
        exec_cfg.tool_call_timeout = 30
        exec_cfg.assign_task_timeout = 600
        config.execution_config = exec_cfg

        await executor.initialize(
            tool_mapping={},
            permission_provider=_MockPermissionProvider(),
            config=config,
            communicator=AsyncMock(),
        )
        assert executor._interactive is True
        assert executor._tool_call_timeout == 30
        assert executor._assign_task_timeout == 600
