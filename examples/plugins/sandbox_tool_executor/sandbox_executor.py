"""SandboxToolExecutor — example plugin that executes tools in a sandbox.

This is a minimal, self-contained example showing how to implement the
``ToolExecutor`` ABC for a Broca plugin.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from broca.components.tool_executor import ToolExecutionOutcome, ToolExecutor


class SandboxToolExecutor(ToolExecutor):
    """Execute tools inside a (simulated) sandbox environment.

    In production, you would replace the ``_sandbox_run`` method with
    an actual sandbox implementation (Docker, Firecracker, gVisor, etc.).
    """

    def __init__(self, **kwargs) -> None:
        # Registry calls this with **kwargs; accept but ignore.
        self._tool_mapping: dict = {}
        self._permission_provider = None
        self._config = None
        self._communicator = None
        self._initialized = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(
        self,
        tool_mapping: dict,
        permission_provider,
        config,
        communicator,
    ) -> None:
        """Inject dependencies (idempotent)."""
        self._tool_mapping = tool_mapping
        self._permission_provider = permission_provider
        self._config = config
        self._communicator = communicator
        self._initialized = True

    async def shutdown(self) -> None:
        """Clean up sandbox resources."""
        self._initialized = False

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def execute_tool(
        self,
        tool_name: str,
        arguments: str,
        tool_call_id: str,
        context: Any,
        tool,
        allowed_tools: Sequence[str] | None = None,
    ) -> ToolExecutionOutcome:
        """Execute a tool call inside the sandbox."""
        from broca.tools.tool import ToolResult, ToolStatus

        # 1. Broadcast
        if self._communicator:
            await self._communicator.send_tool_call(
                message_type="tool_call_start",
                tool_name=tool_name,
                tool_call_id=tool_call_id,
            )

        # 2. Check existence
        if tool_name not in self._tool_mapping:
            return ToolExecutionOutcome(
                result=ToolResult(
                    status=ToolStatus.ERROR,
                    content=f"Tool '{tool_name}' not found in sandbox",
                ),
                session_action=None,
            )

        # 3. Check whitelist
        if allowed_tools is not None and tool_name not in allowed_tools:
            return ToolExecutionOutcome(
                result=ToolResult(
                    status=ToolStatus.ERROR,
                    content=f"Tool '{tool_name}' not in allowed list",
                ),
                session_action=None,
            )

        # 4. Check permission
        if self._permission_provider:
            permission = self._permission_provider.get_permission(tool_name)
            if permission == "forbidden":
                return ToolExecutionOutcome(
                    result=ToolResult(
                        status=ToolStatus.ERROR,
                        content=f"Tool '{tool_name}' is forbidden",
                    ),
                    session_action=None,
                )

        # 5. Execute in sandbox
        try:
            content = await self._sandbox_run(tool_name, arguments)
            return ToolExecutionOutcome(
                result=ToolResult(
                    status=ToolStatus.SUCCESS,
                    content=content,
                ),
                session_action=None,
            )
        except Exception as e:
            return ToolExecutionOutcome(
                result=ToolResult(
                    status=ToolStatus.ERROR,
                    content=f"Sandbox error: {e}",
                ),
                session_action=None,
            )

    # ------------------------------------------------------------------
    # Permission queries
    # ------------------------------------------------------------------

    def get_permission(self, tool_name: str) -> str:
        if self._permission_provider:
            return self._permission_provider.get_permission(tool_name)
        return "allow"

    def is_readonly_tool(self, tool_name: str) -> bool:
        return tool_name in ("read_file", "list_dir", "grep", "glob")

    # ------------------------------------------------------------------
    # Sandbox (replace with real implementation)
    # ------------------------------------------------------------------

    async def _sandbox_run(self, tool_name: str, arguments: str) -> str:
        """Simulated sandbox execution."""
        tool = self._tool_mapping.get(tool_name)
        if tool is None:
            return f"[sandbox] {tool_name}: no tool instance"
        result = await tool.execute(
            arguments_dict=arguments if isinstance(arguments, dict) else {},
            context=None,
        )
        return f"[sandbox:{tool_name}] {result}"
