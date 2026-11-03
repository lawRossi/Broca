"""Mock/stub implementations of the 7 core component interfaces.

Used for isolation testing — each mock implements just enough of the
interface to allow focused unit testing of a single component without
pulling in its real dependencies.

Phase 1 provides mocks for all 7 core components.  The remaining 16
support/infrastructure components get mocks incrementally in Phase 5.
"""

from __future__ import annotations

from typing import Any, AsyncGenerator, Optional

# ---------------------------------------------------------------------------
# Mock ToolExecutor
# ---------------------------------------------------------------------------


class MockToolExecutor:
    """Minimal stub for ``ToolExecutor``.

    ``execute_tool`` returns a success result by default.
    Override ``_execute_result`` in tests for custom behavior.
    """

    def __init__(self):
        self._tool_mapping: dict = {}
        self._permission_provider = None
        self._communicator = None
        self._initialized = False
        # Default: all tools succeed
        self._execute_result = None  # If set, use this ToolResult

    async def initialize(
        self,
        tool_mapping: dict,
        permission_provider: Any,
        config: Any,
        communicator: Any,
    ) -> None:
        self._tool_mapping = tool_mapping
        self._permission_provider = permission_provider
        self._communicator = communicator
        self._initialized = True

    async def execute_tool(
        self,
        tool_name: str,
        arguments: str,
        tool_call_id: str,
        context: Any,
        tool: Any,
        allowed_tools=None,
    ):
        from broca.components.tool_executor import ToolExecutionOutcome
        from broca.tools.tool import ToolResult, ToolStatus

        if self._execute_result is not None:
            return ToolExecutionOutcome(
                result=self._execute_result,
                session_action=None,
            )

        return ToolExecutionOutcome(
            result=ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"mock result for {tool_name}",
            ),
            session_action=None,
        )

    def get_permission(self, tool_name: str) -> str:
        return "allow"

    def is_readonly_tool(self, tool_name: str) -> bool:
        return False


# ---------------------------------------------------------------------------
# Mock ContextCompressor
# ---------------------------------------------------------------------------


class MockContextCompressor:
    """Minimal stub for ``ContextCompressor``.

    ``check_and_compress`` always returns empty stats (no compression).
    """

    def __init__(self):
        self.compressed = False
        self.force_called = False

    @property
    def snapshot_memory_path(self) -> str:
        return "/tmp/mock-snapshot.md"

    @property
    def memory_path(self) -> str:
        return "/tmp/mock-memory.md"

    async def check_and_compress(
        self,
        context: Any,
        compressor_context: Any,
        force: bool = False,
    ) -> Any:
        from broca.context_compressor import CompressionStats

        self.compressed = True
        self.force_called = force
        return CompressionStats()

    def reset_session_memory(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Mock LLMClient
# ---------------------------------------------------------------------------


class MockLLMClient:
    """Minimal stub for ``LLMClient``.

    ``get_stream_response`` yields a content chunk + finish by default.
    ``aggregate_message`` returns a simple assistant message.
    ``parse_message`` returns a basic user-role dict.
    """

    def __init__(self):
        self.config = {"openai": {"models": {"gpt-4": {"meta": {}}}}}
        self.stream_chunks: list[dict] = [
            {"type": "content", "data": "Mock LLM response"},
            {"type": "finish", "data": "stop"},
        ]
        self.call_count = 0

    def parse_message(self, provider: str, model: str, message: Any) -> dict:
        """Parse internal Message to LLM format (mock: extract content)."""
        content = ""
        if message and hasattr(message, "data") and message.data:
            content = message.data.get("content", str(message.data))
        return {"role": "user", "content": content, "raw_input": None}

    async def get_stream_response(
        self,
        provider: str,
        model: str,
        messages: list,
        tools: Optional[list] = None,
        first_chunk_timeout: Optional[float] = None,
        timeout: Optional[float] = None,
    ) -> AsyncGenerator[dict, None]:
        self.call_count += 1
        for chunk in self.stream_chunks:
            yield chunk

    def aggregate_message(
        self, content_chunks: list, tool_call_chunks: list
    ) -> Any:
        from broca.context import LLMMessage

        content = ""
        for chunk in content_chunks:
            if chunk.get("type") == "content":
                content += chunk.get("data", "")

        if not content and not tool_call_chunks:
            return None

        return LLMMessage(
            role="assistant",
            content=content or None,
            tool_calls=tool_call_chunks or None,
        )


# ---------------------------------------------------------------------------
# Mock PermissionProvider
# ---------------------------------------------------------------------------


class MockPermissionProvider:
    """Minimal stub for ``PermissionProvider``.

    Default: all tools are "allow", permission requests auto-approve.
    Configure via ``_permissions`` dict for custom behavior.
    """

    def __init__(self):
        self._permissions: dict[str, str] = {}
        self._session_overrides: dict[str, str] = {}
        self.request_log: list[str] = []

    async def request_permission(self, message: str) -> bool:
        self.request_log.append(message)
        return True

    async def request_tool_permission(
        self, tool_name: str, arguments: str | None = None
    ) -> tuple[bool, Optional[str]]:
        self.request_log.append(tool_name)
        return True, None

    def get_permission(self, tool_name: str) -> str:
        if tool_name in self._session_overrides:
            return self._session_overrides[tool_name]
        return self._permissions.get(tool_name, "allow")

    def set_session_override(self, tool_name: str, permission: str) -> None:
        self._session_overrides[tool_name] = permission

    def clear_session_overrides(self) -> None:
        self._session_overrides.clear()

    # Convenience for tests
    def set_permissions(self, permissions: dict[str, str]) -> None:
        self._permissions = permissions

    def set_mode(self, mode: str) -> None:
        """Set all tools to a specific permission mode."""
        assert mode in ("allow", "ask", "forbidden")
        self._permissions = {"*": mode}
        # Override get_permission to handle wildcard
        self._wildcard = mode
        original_get = self.get_permission

        def get_with_wildcard(tool_name: str) -> str:
            if tool_name in self._session_overrides:
                return self._session_overrides[tool_name]
            if tool_name in self._permissions:
                return self._permissions[tool_name]
            if "*" in self._permissions:
                return self._permissions["*"]
            return "allow"

        self.get_permission = get_with_wildcard


# ---------------------------------------------------------------------------
# Mock Communicator
# ---------------------------------------------------------------------------


class MockCommunicator:
    """Minimal stub for ``Communicator``.

    All send_* methods are no-ops that return a fake message ID.
    Records sent messages for assertion in tests.
    """

    def __init__(self):
        self.agent_id = "mock-agent"
        self.connected = True
        self.sent_messages: list[dict] = []
        self._msg_counter = 0

    async def connect(self, timeout: float = 10.0) -> bool:
        self.connected = True
        return True

    async def disconnect(self) -> None:
        self.connected = False

    def is_connected(self) -> bool:
        return self.connected

    async def send_message(
        self, message: Any, callback=None, retry_on_disconnect: bool = True
    ) -> str:
        self._msg_counter += 1
        msg_id = f"mock-msg-{self._msg_counter}"
        self.sent_messages.append({"type": "message", "message": message})
        return msg_id

    async def send_user_message(
        self,
        content: str,
        subscription: Optional[str] = None,
        receiver_id: Optional[str] = None,
    ) -> str:
        self._msg_counter += 1
        msg_id = f"mock-msg-{self._msg_counter}"
        self.sent_messages.append(
            {"type": "user_message", "content": content}
        )
        return msg_id

    async def send_tool_call(
        self,
        tool_call_id: str,
        tool_name: str,
        arguments: str,
        turn_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        subscription: Optional[str] = None,
    ) -> str:
        self._msg_counter += 1
        msg_id = f"mock-msg-{self._msg_counter}"
        self.sent_messages.append(
            {
                "type": "tool_call",
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "arguments": arguments,
            }
        )
        return msg_id

    async def send_error(
        self,
        error_info: dict,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
        callback=None,
    ) -> str:
        self._msg_counter += 1
        msg_id = f"mock-msg-{self._msg_counter}"
        self.sent_messages.append({"type": "error", "error_info": error_info})
        return msg_id


# ---------------------------------------------------------------------------
# Mock LoopEngine
# ---------------------------------------------------------------------------


class MockLoopEngine:
    """Minimal stub for ``LoopEngine``.

    ``execute`` returns a COMPLETED result by default.
    ``abort`` / ``reset`` are no-ops.
    """

    def __init__(self):
        self.aborted = False
        self.reset_called = False
        self.turn_id: Optional[str] = None
        self.execute_count = 0

    async def execute(
        self,
        message: Any = None,
        max_steps: Optional[int] = None,
        from_agent: Optional[bool] = False,
    ) -> Any:
        from broca.loop_engine import ExecutionResult, ExecutionStatus

        self.execute_count += 1
        if self.aborted:
            return ExecutionResult(
                status=ExecutionStatus.ABORTED,
                message="Aborted by mock",
            )
        return ExecutionResult(status=ExecutionStatus.COMPLETED)

    def abort(self) -> None:
        self.aborted = True

    def reset(self) -> None:
        self.reset_called = True
        self.aborted = False
        self.turn_id = None


# ---------------------------------------------------------------------------
# Mock AgentFactory
# ---------------------------------------------------------------------------


class MockAgentFactory:
    """Minimal stub for ``AgentFactory``.

    ``create_agent`` returns a MagicMock as the agent.
    """

    def __init__(self):
        self.created_agents: list = []

    async def create_agent(
        self,
        agent_config: Any,
        session_manager: Any,
        workspace: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> Any:
        from unittest.mock import MagicMock

        agent = MagicMock()
        agent.agent_id = agent_id or "mock-agent-id"
        agent.name = "mock_agent"
        self.created_agents.append(agent)
        return agent

    async def restore_agents_from_session(
        self, session_id: str
    ) -> list:
        return []
