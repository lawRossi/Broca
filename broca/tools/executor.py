"""Default tool executor — extracted from LoopEngine's tool execution pipeline.

Implements the 8 responsibilities identified in Task 2.1:

  #1  Tool existence check
  #2  ``allowed_tools`` whitelist (per-run, passed to ``execute_tool``)
  #3  Permission decision (forbidden / ask / allow)
  #4  Tool-call broadcast (``send_tool_call``)
  #5  Timeout skip rules (``ask_user``, ``bash --background``)
  #6  Dedicated timeout (``assign_task``)
  #7  Exception mapping (``ToolError``/``BrocaError`` → user message;
      ``TimeoutError`` → timeout text; ``CancelledError`` → re-raised)
  #8  Session decision (``allow``/``forbid`` → ``set_session_override``)

Pipeline order (matches the real code in ``LoopEngine._execute_single_tool_call``)::

    #4 broadcast → #1 exists → #2 allowed → #3 permission
    → #5/#6 timeout → execute → #7 error mapping → #8 session decision

Broadcast is **first**, so even rejected / forbidden tools are broadcast
(the frontend depends on this to show "tool denied" status).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Sequence

from broca.components.communicator import Communicator
from broca.components.permission_provider import PermissionProvider
from broca.components.tool_executor import (
    ToolExecutionOutcome,
    ToolExecutor,
)
from broca.errors import BrocaError, ToolError
from broca.logging_config import get_logger
from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus
from broca.tools.tool_manager import ToolManager

logger = get_logger(__name__)

_READONLY_TOOLS = ToolManager.READONLY_TOOLS


class DefaultToolExecutor(ToolExecutor):
    """Default implementation of the tool execution pipeline.

    All runtime dependencies are injected via :meth:`initialize`::

        executor = registry.get(ToolExecutor, scope_key=agent_id)
        await executor.initialize(
            tool_mapping=agent.tool_mapping,
            permission_provider=agent.permission_provider,
            config=agent.config,
            communicator=agent.communicator,
        )

    ``allowed_tools`` is **per-run** state managed by ``LoopEngine``
    and passed as a parameter to :meth:`execute_tool` — it is
    deliberately **not** part of ``initialize()``.
    """

    def __init__(self) -> None:
        self._tool_mapping: dict[str, Tool] = {}
        self._permission_provider: PermissionProvider | None = None
        self._communicator: Communicator | None = None
        self._interactive: bool = False
        self._tool_call_timeout: float = 120
        self._assign_task_timeout: float = 1800
        self._initialized = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(
        self,
        tool_mapping: dict[str, Tool],
        permission_provider: PermissionProvider,
        config: Any,
        communicator: Communicator,
    ) -> None:
        """Inject runtime dependencies.

        Parameters match the ``ToolExecutor`` ABC exactly.
        ``allowed_tools`` is deliberately excluded — it is per-run.
        """
        # Idempotency: re-calling with the same deps is a no-op
        if self._initialized and self._tool_mapping is tool_mapping:
            return

        self._tool_mapping = tool_mapping
        self._permission_provider = permission_provider
        self._communicator = communicator

        # Read execution config from the agent config
        self._interactive = bool(getattr(config, "interactive", False))
        exec_cfg = getattr(config, "execution_config", None)
        self._tool_call_timeout = float(
            getattr(exec_cfg, "tool_call_timeout", 120) or 120
        )
        self._assign_task_timeout = float(
            getattr(exec_cfg, "assign_task_timeout", 1800) or 1800
        )
        self._initialized = True

    # ------------------------------------------------------------------
    # Public API (from ToolExecutor ABC)
    # ------------------------------------------------------------------

    async def execute_tool(
        self,
        tool_name: str,
        arguments: str,
        tool_call_id: str,
        context: ToolCallContext,
        tool: Tool,
        allowed_tools: Sequence[str] | None = None,
    ) -> ToolExecutionOutcome:
        """Execute a single tool call.

        Pipeline (in order):
        1. ``#4``  broadcast
        2. ``#1``  existence check
        3. ``#2``  allowed_tools whitelist
        4. ``#3``  permission (forbidden / ask / allow)
        5. ``#5/#6`` timeout → execute
        6. ``#7``  exception mapping
        7. ``#8``  session decision
        """
        # ── #4: Broadcast (FIRST — before any validation) ──────────
        await self._broadcast_start(tool_name, arguments, tool_call_id, context)

        # ── #1: Existence check ────────────────────────────────────
        if tool_name not in self._tool_mapping:
            logger.error(f"Tool '{tool_name}' not found.")
            return ToolExecutionOutcome(
                result=ToolResult(
                    status=ToolStatus.ERROR,
                    content=f"Tool {tool_name} not found",
                ),
                session_action=None,
            )

        # ── #2: allowed_tools whitelist ────────────────────────────
        if not self._is_allowed(tool_name, allowed_tools):
            logger.warning(
                "Tool '%s' is not in allowed_tools list, skipping.", tool_name
            )
            return ToolExecutionOutcome(
                result=ToolResult(
                    status=ToolStatus.ERROR,
                    content="this tool is currently not allowed",
                ),
                session_action=None,
            )

        # ── #3: Permission decision ────────────────────────────────
        permission = self._permission_provider.get_permission(tool_name)

        if permission == "forbidden":
            logger.warning(
                "Tool '%s' is forbidden by permission settings, skipping.",
                tool_name,
            )
            return ToolExecutionOutcome(
                result=ToolResult(
                    status=ToolStatus.ERROR,
                    content=f"Tool {tool_name} is forbidden by permission settings",
                ),
                session_action=None,
            )

        if permission == "ask":
            # Ask user for permission, then execute if granted
            granted, session_action = (
                await self._permission_provider.request_tool_permission(
                    tool_name, arguments
                )
            )
            if not granted:
                logger.info(
                    "Tool '%s' execution denied by user", tool_name
                )
                return self._apply_session_decision(
                    ToolExecutionOutcome(
                        result=ToolResult(
                            status=ToolStatus.ERROR,
                            content=f"Tool {tool_name} execution denied by user",
                        ),
                        session_action=session_action,
                    ),
                    tool_name,
                )

            tool_result = await self._execute_with_timeout(
                tool_name, arguments, context
            )
            return self._apply_session_decision(
                ToolExecutionOutcome(
                    result=tool_result,
                    session_action=session_action,
                ),
                tool_name,
            )

        # ── #3.5: Content-aware pre-check (e.g. bash dangerous command) ──
        if tool is not None:
            # Use cached result from parallel partitioning if available
            pre_check_msg = None
            if context.pre_check_cache:
                pre_check_msg = context.pre_check_cache.get(tool_call_id)
            if pre_check_msg is None:
                # Cache miss (serial execution path has no partitioning phase)
                pre_check_fn = getattr(tool, "pre_execute_check", None)
                pre_check_msg = (
                    pre_check_fn(arguments, context) if pre_check_fn else None
                )
            if pre_check_msg:
                granted = await self._permission_provider.request_permission(
                    pre_check_msg
                )
                if not granted:
                    logger.info(
                        "Tool '%s' execution denied by user (pre-check)", tool_name
                    )
                    return ToolExecutionOutcome(
                        result=ToolResult(
                            status=ToolStatus.ERROR,
                            content="User refused to execute this tool",
                        ),
                        session_action=None,
                    )

        # permission == "allow" (or default)
        tool_result = await self._execute_with_timeout(tool_name, arguments, context)
        return ToolExecutionOutcome(result=tool_result, session_action=None)

    def get_permission(self, tool_name: str) -> str:
        """Delegate to ``PermissionProvider``."""
        return self._permission_provider.get_permission(tool_name)

    def is_readonly_tool(self, tool_name: str) -> bool:
        """Check if a tool is read-only (from ``ToolManager.READONLY_TOOLS``)."""
        return tool_name in _READONLY_TOOLS

    # ------------------------------------------------------------------
    # Internal pipeline steps
    # ------------------------------------------------------------------

    async def _broadcast_start(
        self,
        tool_name: str,
        arguments: str,
        tool_call_id: str,
        context: ToolCallContext,
    ) -> None:
        """#4 — broadcast tool-call-start to the frontend.

        Uses ``context.turn_id`` / ``context.agent_id`` /
        ``context.session_id`` — does **not** read ``context.agent``.
        """
        if not self._interactive:
            return
        if self._communicator is None:
            return
        await self._communicator.send_tool_call(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=arguments,
            turn_id=context.turn_id,
            agent_id=context.agent_id,
            subscription=context.session_id,
        )

    def _is_allowed(
        self, tool_name: str, allowed_tools: Sequence[str] | None
    ) -> bool:
        """#2 — check the per-run ``allowed_tools`` whitelist.

        ``None`` means no restriction.
        """
        return allowed_tools is None or tool_name in allowed_tools

    def _get_timeout(self, tool_name: str) -> float:
        """#6 — return the appropriate timeout for a tool.

        ``assign_task`` gets its own (longer) timeout; everything else
        uses the default ``tool_call_timeout``.
        """
        if tool_name == "assign_task":
            return self._assign_task_timeout
        return self._tool_call_timeout

    def _should_skip_timeout(self, tool_name: str, arguments: str) -> bool:
        """#5 — determine whether to skip the outer ``asyncio.wait_for``.

        ``ask_user`` and ``bash --background`` manage their own internal
        timeouts and must NOT be wrapped by the outer timeout.
        """
        if tool_name == "bash":
            try:
                args_dict = json.loads(arguments)
                return bool(args_dict.get("background", False))
            except (json.JSONDecodeError, TypeError):
                return False
        if tool_name == "ask_user":
            return True
        return False

    async def _execute_with_timeout(
        self,
        tool_name: str,
        arguments: str,
        context: ToolCallContext,
    ) -> ToolResult:
        """#5/#6/#7 — execute the tool with timeout + exception mapping.

        The tool is looked up from ``self._tool_mapping``.
        """
        tool = self._tool_mapping[tool_name]
        try:
            if self._should_skip_timeout(tool_name, arguments):
                # #5: no outer timeout — tool manages its own
                return await tool.execute(arguments, context)
            # #6: use the appropriate timeout
            timeout = self._get_timeout(tool_name)
            return await asyncio.wait_for(
                tool.execute(arguments, context),
                timeout=timeout,
            )
        except (ToolError, BrocaError) as e:
            # #7: map Broca errors to user-facing messages
            logger.error(f"Tool execution failed: {e}")
            return ToolResult(
                status=ToolStatus.ERROR, content=e.to_user_message()
            )
        except asyncio.TimeoutError:
            # #7: timeout → friendly error message
            timeout = self._get_timeout(tool_name)
            logger.error(
                "Tool '%s' execution timed out after %ss", tool_name, timeout
            )
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Tool {tool_name} execution timed out after {timeout}s",
            )
        except asyncio.CancelledError:
            # #7: CancelledError must propagate (user cancellation)
            logger.info("Tool execution cancelled by user")
            raise

    def _apply_session_decision(
        self, outcome: ToolExecutionOutcome, tool_name: str
    ) -> ToolExecutionOutcome:
        """#8 — apply the user's session-level permission decision.

        If the user chose "always allow" or "always forbid", write the
        override via ``PermissionProvider.set_session_override()``.
        ``outcome.session_action`` is observation-only; callers must
        NOT apply it again.
        """
        action = outcome.session_action
        if action == "allow":
            self._permission_provider.set_session_override(tool_name, "allow")
            logger.info(
                "User chose to always allow '%s' for this session", tool_name
            )
        elif action == "forbid":
            self._permission_provider.set_session_override(tool_name, "forbidden")
            logger.info(
                "User chose to always forbid '%s' for this session", tool_name
            )
        return outcome
