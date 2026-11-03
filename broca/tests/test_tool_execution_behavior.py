"""Characterization tests for the tool execution pipeline.

These tests lock in the behaviour of the tool execution pipeline
so that the Phase 2 refactoring (extracting the pipeline into
``DefaultToolExecutor``) can be verified as behaviour-preserving.

Pipeline order (MUST be preserved)::

    #4 broadcast → #1 exists → #2 allowed_tools → #3 permission
    → #5/#6 timeout → execute → #7 error mapping → #8 session decision

Broadcast is **first**, so even rejected / forbidden tools are
broadcast (the frontend relies on this to show "tool denied").

Run before **and** after the refactoring::

    pytest broca/tests/test_tool_execution_behavior.py -v
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from broca.configs import ExecutionConfig
from broca.errors import ToolError
from broca.tools.executor import DefaultToolExecutor
from broca.tools.tool import ToolCallContext, ToolResult, ToolStatus


# ── Mock tool implementations ────────────────────────────────────────


class _InstantTool:
    """Completes immediately with a fixed result."""

    def __init__(self, content: str = "ok"):
        self._content = content
        self.call_count = 0

    async def execute(self, arguments: str, context: ToolCallContext) -> ToolResult:
        self.call_count += 1
        return ToolResult(status=ToolStatus.SUCCESS, content=self._content)


class _SlowTool:
    """Sleeps for *delay* seconds before returning."""

    def __init__(self, delay: float = 0.2):
        self._delay = delay
        self.called = False

    async def execute(self, arguments: str, context: ToolCallContext) -> ToolResult:
        self.called = True
        await asyncio.sleep(self._delay)
        return ToolResult(status=ToolStatus.SUCCESS, content="slow done")


class _ErrorTool:
    """Raises a ``ToolError`` when executed."""

    def __init__(self, msg: str = "boom"):
        self._msg = msg

    async def execute(self, arguments: str, context: ToolCallContext) -> ToolResult:
        raise ToolError(message=self._msg)


class _CancelledTool:
    """Raises ``asyncio.CancelledError`` when executed."""

    async def execute(self, arguments: str, context: ToolCallContext) -> ToolResult:
        raise asyncio.CancelledError()


# ── Helper factories ─────────────────────────────────────────────────


def _make_executor(
    tool_mapping: dict | None = None,
    interactive: bool = True,
    permission: str = "allow",
    tool_call_timeout: float | None = None,
    assign_task_timeout: float | None = None,
    permission_provider=None,
) -> DefaultToolExecutor:
    """Create a ``DefaultToolExecutor`` wired with mocks."""
    executor = DefaultToolExecutor()

    # Build config mock
    config = MagicMock()
    config.interactive = interactive
    config.execution_config = ExecutionConfig()
    if tool_call_timeout is not None:
        config.execution_config.tool_call_timeout = tool_call_timeout
    if assign_task_timeout is not None:
        config.execution_config.assign_task_timeout = assign_task_timeout

    # Build communicator mock
    communicator = MagicMock()
    communicator.send_tool_call = AsyncMock(return_value="msg-broadcast")

    # Build permission provider mock
    if permission_provider is None:
        permission_provider = MagicMock()
        permission_provider.get_permission.return_value = permission
        permission_provider.request_tool_permission = AsyncMock(
            return_value=(True, None)
        )

    return executor, permission_provider, communicator, config


async def _init_executor(
    executor, permission_provider, communicator, config, tool_mapping=None
):
    await executor.initialize(
        tool_mapping=tool_mapping or {},
        permission_provider=permission_provider,
        config=config,
        communicator=communicator,
    )


def _ctx() -> ToolCallContext:
    """Minimal ``ToolCallContext`` for tests."""
    c = ToolCallContext()
    c.agent = None
    c.workspace = "/tmp"
    c.session_id = "test-session"
    c.turn_id = "turn-1"
    c.agent_id = "agent-1"
    return c


# ════════════════════════════════════════════════════════════════════
# #5  Timeout skip rules
# ════════════════════════════════════════════════════════════════════


class TestTimeoutSkipRules:
    """#5: ``ask_user`` and ``bash --background`` skip the outer
    ``asyncio.wait_for`` timeout entirely."""

    @pytest.mark.asyncio
    async def test_ask_user_not_interrupted_by_outer_timeout(self):
        """#5 — ``ask_user``: even if the tool takes longer than
        ``tool_call_timeout``, it completes normally because the
        executor skips the outer timeout for ``ask_user``.
        """
        executor, pp, comm, config = _make_executor(
            tool_call_timeout=0.05,  # 50 ms << 200 ms sleep
        )
        tool = _SlowTool(delay=0.2)
        await _init_executor(
            executor, pp, comm, config,
            tool_mapping={"ask_user": tool},
        )
        outcome = await executor.execute_tool(
            "ask_user", "{}", "call-1", _ctx(), tool,
        )
        assert outcome.result.status == ToolStatus.SUCCESS
        assert outcome.result.content == "slow done"

    @pytest.mark.asyncio
    async def test_bash_background_skips_outer_timeout(self):
        """#5 — ``bash`` with ``{"background": true}`` skips the outer
        timeout just like ``ask_user``."""
        executor, pp, comm, config = _make_executor(tool_call_timeout=0.05)
        tool = _SlowTool(delay=0.2)
        await _init_executor(
            executor, pp, comm, config,
            tool_mapping={"bash": tool},
        )
        outcome = await executor.execute_tool(
            "bash", '{"background": true}', "call-1", _ctx(), tool,
        )
        assert outcome.result.status == ToolStatus.SUCCESS
        assert outcome.result.content == "slow done"


# ════════════════════════════════════════════════════════════════════
# #6  Dedicated timeout for assign_task
# ════════════════════════════════════════════════════════════════════


class TestDedicatedTimeout:
    """#6: ``assign_task`` uses its own (longer) timeout instead of
    the default ``tool_call_timeout``."""

    @pytest.mark.asyncio
    async def test_assign_task_uses_dedicated_timeout(self):
        """#6 — a tool that takes 0.2 s would time out under the
        default ``tool_call_timeout=0.1`` but completes under
        ``assign_task_timeout=0.5``."""
        executor, pp, comm, config = _make_executor(
            tool_call_timeout=0.1,
            assign_task_timeout=0.5,
        )
        tool = _SlowTool(delay=0.2)
        await _init_executor(
            executor, pp, comm, config,
            tool_mapping={"assign_task": tool},
        )
        outcome = await executor.execute_tool(
            "assign_task", "{}", "call-1", _ctx(), tool,
        )
        assert outcome.result.status == ToolStatus.SUCCESS
        assert outcome.result.content == "slow done"


# ════════════════════════════════════════════════════════════════════
# #2  allowed_tools whitelist + per-run scoping
# ════════════════════════════════════════════════════════════════════


class TestAllowedTools:
    """#2: ``allowed_tools`` whitelist blocks tools not in the list."""

    @pytest.mark.asyncio
    async def test_disallowed_tool_rejected(self):
        """#2 — when ``allowed_tools=['read_file']``, calling ``bash``
        returns ``this tool is currently not allowed`` and the tool
        is never executed."""
        bash = _InstantTool()
        executor, pp, comm, config = _make_executor()
        await _init_executor(
            executor, pp, comm, config,
            tool_mapping={"bash": bash, "read_file": _InstantTool()},
        )
        outcome = await executor.execute_tool(
            "bash", "{}", "call-1", _ctx(), bash,
            allowed_tools=["read_file"],
        )
        assert outcome.result.status == ToolStatus.ERROR
        assert outcome.result.content == "this tool is currently not allowed"
        assert bash.call_count == 0

    @pytest.mark.asyncio
    async def test_run_scoped_allowed_tools_reset(self):
        """#2 (per-run state) — ``allowed_tools`` is passed as a
        parameter to each ``execute_tool()`` call.  The same executor
        can be called with different whitelists per run, and when
        ``allowed_tools=None``, all tools are accessible."""
        tool = _InstantTool(content="bash-result")
        executor, pp, comm, config = _make_executor()
        await _init_executor(
            executor, pp, comm, config,
            tool_mapping={"bash": tool},
        )

        # During a run with allowed_tools=["read_file"]:
        outcome = await executor.execute_tool(
            "bash", "{}", "call-1", _ctx(), tool,
            allowed_tools=["read_file"],
        )
        assert outcome.result.status == ToolStatus.ERROR
        assert "not allowed" in outcome.result.content
        assert tool.call_count == 0

        # After the run (allowed_tools=None):
        outcome2 = await executor.execute_tool(
            "bash", "{}", "call-2", _ctx(), tool,
            allowed_tools=None,
        )
        assert outcome2.result.status == ToolStatus.SUCCESS
        assert tool.call_count == 1


# ════════════════════════════════════════════════════════════════════
# #3 + #8  Permission + session override
# ════════════════════════════════════════════════════════════════════


class TestSessionOverride:
    """#3 + #8: when permission is ``ask`` and the user grants with
    ``session_action='allow'``, the executor writes a session
    override so the next call skips the ask step."""

    @pytest.mark.asyncio
    async def test_session_override_persisted(self):
        """#3+#8 — a realistic mock where ``get_permission`` respects
        overrides written by ``set_session_override``.
        """
        overrides: dict[str, str] = {}

        def get_permission(name):
            return overrides.get(name, "ask")

        def set_override(name, perm):
            overrides[name] = perm

        pp = MagicMock()
        pp.get_permission.side_effect = get_permission
        pp.set_session_override.side_effect = set_override
        pp.request_tool_permission = AsyncMock(return_value=(True, "allow"))

        executor = DefaultToolExecutor()
        comm = MagicMock()
        comm.send_tool_call = AsyncMock(return_value="msg-1")
        config = MagicMock()
        config.interactive = True
        config.execution_config = ExecutionConfig()

        tool = _InstantTool(content="executed")
        await executor.initialize(
            tool_mapping={"risky_tool": tool},
            permission_provider=pp,
            config=config,
            communicator=comm,
        )

        # ── First call: permission "ask" → asks user ──
        outcome = await executor.execute_tool(
            "risky_tool", "{}", "call-1", _ctx(), tool,
        )
        assert outcome.result.status == ToolStatus.SUCCESS

        # Override was written
        pp.set_session_override.assert_called_once_with("risky_tool", "allow")
        assert overrides["risky_tool"] == "allow"

        # ── Second call: permission now "allow" → no ask needed ──
        pp.request_tool_permission.reset_mock()
        outcome2 = await executor.execute_tool(
            "risky_tool", "{}", "call-2", _ctx(), tool,
        )
        assert outcome2.result.status == ToolStatus.SUCCESS
        pp.request_tool_permission.assert_not_called()


# ════════════════════════════════════════════════════════════════════
# #4  Broadcast (always first, even for rejected tools)
# ════════════════════════════════════════════════════════════════════


class TestBroadcast:
    """#4: ``send_tool_call`` broadcast is emitted **before** any
    validation (exists / allowed / permission)."""

    @pytest.mark.asyncio
    async def test_tool_call_broadcast_emitted(self):
        """#4 — when ``interactive=True``, ``send_tool_call`` is
        called with the correct ``tool_call_id``."""
        executor, pp, comm, config = _make_executor(interactive=True)
        tool = _InstantTool()
        await _init_executor(
            executor, pp, comm, config,
            tool_mapping={"my_tool": tool},
        )
        await executor.execute_tool(
            "my_tool", "{}", "call_abc123", _ctx(), tool,
        )

        comm.send_tool_call.assert_called_once()
        kwargs = comm.send_tool_call.call_args[1]
        assert kwargs["tool_name"] == "my_tool"
        assert kwargs["tool_call_id"] == "call_abc123"

    @pytest.mark.asyncio
    async def test_broadcast_emitted_for_forbidden_tool(self):
        """#4 — broadcast happens BEFORE the permission check, so a
        forbidden tool **still** gets ``send_tool_call``."""
        executor, pp, comm, config = _make_executor(
            interactive=True, permission="forbidden",
        )
        tool = _InstantTool()
        await _init_executor(
            executor, pp, comm, config,
            tool_mapping={"dangerous_tool": tool},
        )
        outcome = await executor.execute_tool(
            "dangerous_tool", "{}", "call_forbidden", _ctx(), tool,
        )

        # Tool was rejected:
        assert outcome.result.status == ToolStatus.ERROR
        assert "forbidden" in outcome.result.content

        # But broadcast WAS emitted:
        comm.send_tool_call.assert_called_once()
        kwargs = comm.send_tool_call.call_args[1]
        assert kwargs["tool_name"] == "dangerous_tool"


# ════════════════════════════════════════════════════════════════════
# #1  Tool existence check
# ════════════════════════════════════════════════════════════════════


class TestToolNotFound:
    """#1: a tool name not in ``tool_mapping`` returns an error."""

    @pytest.mark.asyncio
    async def test_tool_not_found_returns_error(self):
        """#1 — ``ToolResult(ERROR, 'Tool X not found')``."""
        executor, pp, comm, config = _make_executor()
        await _init_executor(
            executor, pp, comm, config,
            tool_mapping={"read_file": _InstantTool()},
        )
        # 'nonexistent_tool' is NOT in tool_mapping
        outcome = await executor.execute_tool(
            "nonexistent_tool", "{}", "call-1", _ctx(),
            tool=_InstantTool(),  # tool param is provided but name isn't in mapping
        )
        assert outcome.result.status == ToolStatus.ERROR
        assert outcome.result.content == "Tool nonexistent_tool not found"


# ════════════════════════════════════════════════════════════════════
# #7  Exception → ToolResult mapping
# ════════════════════════════════════════════════════════════════════


class TestErrorMapping:
    """#7: exception mapping rules:
    - ``ToolError`` / ``BrocaError`` → ``ToolResult(ERROR, to_user_message())``
    - ``asyncio.CancelledError`` → **re-raised**
    """

    @pytest.mark.asyncio
    async def test_tool_error_mapped_to_user_message(self):
        """#7 — a ``ToolError`` raised by the tool is mapped to
        ``ToolResult(ERROR)`` with ``e.to_user_message()``."""
        executor, pp, comm, config = _make_executor()
        failing = _ErrorTool(msg="disk full")
        await _init_executor(
            executor, pp, comm, config,
            tool_mapping={"failing": failing},
        )
        outcome = await executor.execute_tool(
            "failing", "{}", "call-1", _ctx(), failing,
        )
        assert outcome.result.status == ToolStatus.ERROR
        expected = ToolError(message="disk full").to_user_message()
        assert outcome.result.content == expected

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates(self):
        """#7 — ``asyncio.CancelledError`` is **re-raised**, not
        swallowed.  User cancellation must propagate up."""
        executor, pp, comm, config = _make_executor()
        cancel_me = _CancelledTool()
        await _init_executor(
            executor, pp, comm, config,
            tool_mapping={"cancel_me": cancel_me},
        )
        with pytest.raises(asyncio.CancelledError):
            await executor.execute_tool(
                "cancel_me", "{}", "call-1", _ctx(), cancel_me,
            )
