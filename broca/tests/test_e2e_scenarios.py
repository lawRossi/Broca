"""E2E regression tests — verify full agent pipeline with ComponentRegistry.

Uses mock LLM / Communicator / SessionManager (no real SocketIO).
Tests the full Agent.create() → component wiring → tool execution pipeline.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broca.components.communicator import Communicator
from broca.components.llm_client import LLMClient
from broca.components.loop_engine import LoopEngine
from broca.components.permission_provider import PermissionProvider
from broca.components.registry import ComponentRegistry
from broca.components.tool_executor import ToolExecutor
from broca.components.tool_manager import ToolManager


# ---------------------------------------------------------------------------
# Helpers (same pattern as test_agent_composition.py)
# ---------------------------------------------------------------------------


def _make_agent_config(**overrides):
    from broca.agent_configs import AgentConfig

    cfg = AgentConfig()
    cfg.name = "e2e-agent"
    cfg.role = "test"
    cfg.role_description = "E2E test agent"
    cfg.system_prompt_template = "You are a test agent."
    cfg.tools = []
    cfg.workspace = "/tmp/e2e-workspace"
    cfg.save_history = False
    cfg.server_url = "http://localhost:9999"
    cfg.enable_context_compression = False
    cfg.enable_snapshot_tracking = False
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _make_session_manager():
    sm = AsyncMock()
    sm.session_id = "e2e-session-001"
    sm.save_agent = AsyncMock()
    sm.save_message = AsyncMock()
    sm.agent_service = AsyncMock()
    sm.agent_service.get = AsyncMock(return_value=None)
    sm.agent_service.update = AsyncMock()
    sm.agent_service.update_agent_status = AsyncMock()
    sm.get_agents = AsyncMock(return_value=[])
    sm.get_agent_config = AsyncMock(return_value=None)
    sm.load_session = AsyncMock()
    sm.create_session = AsyncMock()
    return sm


def _make_mock_llm():
    llm = AsyncMock()
    llm.config = {"openai": {"models": {"gpt-4": {"meta": {}}}}}

    async def _fake_stream(*a, **kw):
        yield {"type": "content", "data": "Hello from E2E mock LLM"}
        yield {"type": "finish", "data": "stop"}

    llm.get_stream_response = _fake_stream

    from litellm import Message as LLMMessage
    llm.aggregate_message.return_value = LLMMessage(
        role="assistant", content="Hello from E2E mock LLM"
    )
    return llm


def _register_mock_tool_manager(registry):
    class MockToolManager(ToolManager):
        async def init(self, workspace=None):
            self._initialized = True

        def get_tools(self, tool_names=None):
            return []

        def get_mcp_tools(self, mcp_servers=None):
            return []

        def load_custom_tools(self, workspace=None):
            return []

    registry.set_override(ToolManager, MockToolManager)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def agent_registry(fresh_registry):
    """Fresh registry with mock ToolManager, patched as the singleton."""
    _register_mock_tool_manager(fresh_registry)
    with patch(
        "broca.components.registry.ComponentRegistry.get_instance",
        return_value=fresh_registry,
    ):
        yield fresh_registry


# ---------------------------------------------------------------------------
# Scenario 1: Agent.create() with defaults → all components wired
# ---------------------------------------------------------------------------


class TestE2EAgentCreation:
    @pytest.mark.asyncio
    async def test_agent_create_wires_all_components(self, agent_registry, test_workspace):
        """Agent.create() with defaults wires all components from registry."""
        from broca.agent import Agent
        from broca.components.context_compressor import ContextCompressor
        from broca.components.memory_manager import MemoryManager
        from broca.components.command_system import CommandSystem

        sm = _make_session_manager()
        cfg = _make_agent_config(workspace=test_workspace)
        llm = _make_mock_llm()

        agent = await Agent.create(cfg, llm, sm, agent_id="e2e-create")

        # All key components should be set
        assert agent.execution_engine is not None
        assert agent.llm_client is not None
        assert agent.communicator is not None
        assert agent.context is not None
        assert isinstance(agent.execution_engine, LoopEngine)


# ---------------------------------------------------------------------------
# Scenario 2: Tool execution pipeline via DefaultToolExecutor
# ---------------------------------------------------------------------------


class TestE2EToolPipeline:
    @pytest.mark.asyncio
    async def test_tool_execution_success(self, agent_registry, test_workspace, test_tool):
        """Full tool pipeline: init → execute → success result."""
        from broca.tools.executor import DefaultToolExecutor
        from broca.tools.tool import ToolResult, ToolStatus, ToolCallContext

        executor = DefaultToolExecutor()
        agent_registry.set_override(ToolExecutor, type(executor))
        agent_registry._instances[(ToolExecutor, "e2e-pipe")] = executor

        perm_provider = AsyncMock()
        perm_provider.get_permission = MagicMock(return_value="allow")
        comm = AsyncMock()
        comm.send_tool_call = AsyncMock(return_value="msg-1")

        await executor.initialize(
            tool_mapping={"test_tool": test_tool},
            permission_provider=perm_provider,
            config=MagicMock(),
            communicator=comm,
        )

        ctx = ToolCallContext()
        ctx.agent_id = "e2e-pipe"
        ctx.turn_id = "turn-1"
        ctx.agent = None
        ctx.namespace = {}
        ctx.tool_call_id = "call-001"

        outcome = await executor.execute_tool(
            tool_name="test_tool",
            arguments="{}",
            tool_call_id="call-001",
            context=ctx,
            tool=test_tool,
            allowed_tools=None,
        )

        assert outcome.result.status == ToolStatus.SUCCESS
        assert "test result" in outcome.result.content
        # Tool call was broadcast
        assert comm.send_tool_call.call_count >= 1

    @pytest.mark.asyncio
    async def test_permission_forbidden_blocks_execution(self, agent_registry, test_workspace, test_tool):
        """Permission 'forbidden' → tool execution blocked with error."""
        from broca.tools.executor import DefaultToolExecutor
        from broca.tools.tool import ToolResult, ToolStatus, ToolCallContext

        executor = DefaultToolExecutor()
        agent_registry.set_override(ToolExecutor, type(executor))
        agent_registry._instances[(ToolExecutor, "e2e-perm")] = executor

        perm_provider = AsyncMock()
        perm_provider.get_permission = MagicMock(return_value="forbidden")
        comm = AsyncMock()

        await executor.initialize(
            tool_mapping={"test_tool": test_tool},
            permission_provider=perm_provider,
            config=MagicMock(),
            communicator=comm,
        )

        ctx = ToolCallContext()
        ctx.agent_id = "e2e-perm"
        ctx.turn_id = "turn-1"
        ctx.agent = None
        ctx.namespace = {}
        ctx.tool_call_id = "call-001"

        outcome = await executor.execute_tool(
            tool_name="test_tool",
            arguments="{}",
            tool_call_id="call-001",
            context=ctx,
            tool=test_tool,
            allowed_tools=None,
        )

        assert outcome.result.status == ToolStatus.ERROR

    @pytest.mark.asyncio
    async def test_allowed_tools_whitelist_blocks(self, agent_registry, test_workspace, test_tool):
        """Tool not in allowed_tools whitelist → blocked."""
        from broca.tools.executor import DefaultToolExecutor
        from broca.tools.tool import ToolResult, ToolStatus, ToolCallContext

        executor = DefaultToolExecutor()
        agent_registry.set_override(ToolExecutor, type(executor))
        agent_registry._instances[(ToolExecutor, "e2e-wl")] = executor

        perm_provider = AsyncMock()
        perm_provider.get_permission = MagicMock(return_value="allow")
        comm = AsyncMock()

        await executor.initialize(
            tool_mapping={"test_tool": test_tool},
            permission_provider=perm_provider,
            config=MagicMock(),
            communicator=comm,
        )

        ctx = ToolCallContext()
        ctx.agent_id = "e2e-wl"
        ctx.turn_id = "turn-1"
        ctx.agent = None
        ctx.namespace = {}
        ctx.tool_call_id = "call-001"

        # "other_tool" in whitelist, "test_tool" is NOT
        outcome = await executor.execute_tool(
            tool_name="test_tool",
            arguments="{}",
            tool_call_id="call-001",
            context=ctx,
            tool=test_tool,
            allowed_tools=["other_tool"],
        )

        assert outcome.result.status == ToolStatus.ERROR

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self, agent_registry, test_workspace, test_tool):
        """Tool not in tool_mapping → error result, no crash."""
        from broca.tools.executor import DefaultToolExecutor
        from broca.tools.tool import ToolResult, ToolStatus, ToolCallContext

        executor = DefaultToolExecutor()
        agent_registry.set_override(ToolExecutor, type(executor))
        agent_registry._instances[(ToolExecutor, "e2e-unk")] = executor

        perm_provider = AsyncMock()
        perm_provider.get_permission = MagicMock(return_value="allow")
        comm = AsyncMock()

        await executor.initialize(
            tool_mapping={"test_tool": test_tool},
            permission_provider=perm_provider,
            config=MagicMock(),
            communicator=comm,
        )

        ctx = ToolCallContext()
        ctx.agent_id = "e2e-unk"
        ctx.turn_id = "turn-1"
        ctx.agent = None
        ctx.namespace = {}
        ctx.tool_call_id = "call-001"

        outcome = await executor.execute_tool(
            tool_name="nonexistent_tool",
            arguments="{}",
            tool_call_id="call-001",
            context=ctx,
            tool=None,
            allowed_tools=None,
        )

        assert outcome.result.status == ToolStatus.ERROR

    @pytest.mark.asyncio
    async def test_tool_exception_caught(self, agent_registry, test_workspace):
        """Tool that raises → error ToolResult (no crash)."""
        from broca.tools.executor import DefaultToolExecutor
        from broca.tools.tool import Tool, ToolResult, ToolStatus, ToolCallContext

        class _FailingTool(Tool):
            @property
            def name(self):
                return "failing_tool"

            @property
            def description(self):
                return "Always fails"

            @property
            def parameters(self):
                return {"type": "object", "properties": {}}

            async def _execute(self, arguments, context):
                raise RuntimeError("Simulated failure")

        failing = _FailingTool()
        executor = DefaultToolExecutor()
        agent_registry.set_override(ToolExecutor, type(executor))
        agent_registry._instances[(ToolExecutor, "e2e-exc")] = executor

        perm_provider = AsyncMock()
        perm_provider.get_permission = MagicMock(return_value="allow")
        comm = AsyncMock()

        await executor.initialize(
            tool_mapping={"failing_tool": failing},
            permission_provider=perm_provider,
            config=MagicMock(),
            communicator=comm,
        )

        ctx = ToolCallContext()
        ctx.agent_id = "e2e-exc"
        ctx.turn_id = "turn-1"
        ctx.agent = None
        ctx.namespace = {}
        ctx.tool_call_id = "call-001"

        outcome = await executor.execute_tool(
            tool_name="failing_tool",
            arguments="{}",
            tool_call_id="call-001",
            context=ctx,
            tool=failing,
            allowed_tools=None,
        )

        assert outcome.result.status == ToolStatus.ERROR
        assert "Simulated failure" in (outcome.result.content or "")


# ---------------------------------------------------------------------------
# Scenario 3: Multi-agent isolation via registry
# ---------------------------------------------------------------------------


class TestE2EMultiAgentIsolation:
    @pytest.mark.asyncio
    async def test_two_agents_get_separate_per_agent_components(self, agent_registry, test_workspace):
        """Two agents: LLMClient shared (singleton), per-agent components separate."""
        from broca.agent import Agent

        sm1 = _make_session_manager()
        sm1.session_id = "session-a"
        sm2 = _make_session_manager()
        sm2.session_id = "session-b"
        cfg = _make_agent_config(workspace=test_workspace)
        llm = _make_mock_llm()

        # Register LLM singleton
        agent_registry._instances[(LLMClient, None)] = llm

        agent1 = await Agent.create(cfg, llm, sm1, agent_id="agent-1")
        agent2 = await Agent.create(cfg, llm, sm2, agent_id="agent-2")

        # LLMClient should be shared (singleton)
        assert agent1.llm_client is agent2.llm_client
        # Communicators should be separate (per-agent)
        assert agent1.communicator is not agent2.communicator
        assert agent1.agent_id == "agent-1"
        assert agent2.agent_id == "agent-2"


# ---------------------------------------------------------------------------
# Scenario 4: Plugin override changes ToolExecutor behavior
# ---------------------------------------------------------------------------


class TestE2EPluginOverride:
    @pytest.mark.asyncio
    async def test_plugin_tool_executor_used_by_agent(self, agent_registry, test_workspace):
        """With plugin override, agent uses the overridden ToolExecutor."""
        from broca.agent import Agent
        from broca.tests.test_plugin_loading import MockSandboxToolExecutor

        sm = _make_session_manager()
        cfg = _make_agent_config(workspace=test_workspace)
        llm = _make_mock_llm()
        agent_registry._instances[(LLMClient, None)] = llm

        # Override ToolExecutor with the sandbox plugin
        agent_registry.set_override(ToolExecutor, MockSandboxToolExecutor)

        agent = await Agent.create(cfg, llm, sm, agent_id="e2e-plugin")

        assert isinstance(agent.execution_engine.tool_executor, MockSandboxToolExecutor)


# ---------------------------------------------------------------------------
# Scenario 5: Agent disconnect releases scoped components
# ---------------------------------------------------------------------------


class TestE2EDisconnect:
    @pytest.mark.asyncio
    async def test_disconnect_releases_per_agent_instances(self, agent_registry, test_workspace):
        """Agent.disconnect() releases per-agent scoped instances from registry."""
        from broca.agent import Agent

        sm = _make_session_manager()
        cfg = _make_agent_config(workspace=test_workspace)
        llm = _make_mock_llm()
        agent_registry._instances[(LLMClient, None)] = llm

        agent = await Agent.create(cfg, llm, sm, agent_id="e2e-dc")

        # Before disconnect, per-agent instances exist
        has_comm = any(
            k[0] == Communicator and k[1] == "e2e-dc"
            for k in agent_registry._instances
        )
        assert has_comm

        await agent.disconnect()

        # After disconnect, per-agent instances are released
        has_comm_after = any(
            k[0] == Communicator and k[1] == "e2e-dc"
            for k in agent_registry._instances
        )
        assert not has_comm_after


# ---------------------------------------------------------------------------
# Scenario 6: Component registry release by scope_key
# ---------------------------------------------------------------------------


class TestE2ERelease:
    def test_release_removes_only_target_scope(self, agent_registry):
        """release(scope_key) removes only that agent's instances."""
        from broca.tests.test_plugin_loading import MockSandboxToolExecutor

        agent_registry.set_override(ToolExecutor, MockSandboxToolExecutor)

        a1 = agent_registry.get(ToolExecutor, scope_key="agent-1")
        a2 = agent_registry.get(ToolExecutor, scope_key="agent-2")

        assert a1 is not a2

        agent_registry.release("agent-1")

        # agent-1's instance is gone
        a1_new = agent_registry.get(ToolExecutor, scope_key="agent-1")
        assert a1_new is not a1

        # agent-2's instance is still cached
        a2_again = agent_registry.get(ToolExecutor, scope_key="agent-2")
        assert a2_again is a2


# ---------------------------------------------------------------------------
# Scenario 7: Configuration override via components.json
# ---------------------------------------------------------------------------


class TestE2EConfigOverride:
    def test_components_json_override_loaded(self, agent_registry, test_workspace):
        """components.json in workspace overrides default LLMClient."""
        import json
        from pathlib import Path

        broca_dir = Path(test_workspace) / ".broca"
        broca_dir.mkdir()
        (broca_dir / "components.json").write_text(json.dumps({
            "tool_executor": "broca.tests.test_plugin_loading:MockSandboxToolExecutor"
        }))

        agent_registry.load_config_overrides(test_workspace)

        impl = agent_registry.resolve(ToolExecutor)
        assert impl.__name__ == "MockSandboxToolExecutor"


# ---------------------------------------------------------------------------
# Scenario 8: Error config does not prevent agent creation
# ---------------------------------------------------------------------------


class TestE2EErrorConfig:
    @pytest.mark.asyncio
    async def test_broken_config_agent_still_starts(self, agent_registry, test_workspace):
        """Broken components.json → warning, agent still starts with defaults."""
        import json
        from pathlib import Path
        from broca.agent import Agent

        broca_dir = Path(test_workspace) / ".broca"
        broca_dir.mkdir()
        (broca_dir / "components.json").write_text(json.dumps({
            "llm_client": "nonexistent_pkg.nonexistent:FakeLLM"
        }))

        # Load config (should warn and skip)
        agent_registry.load_config_overrides(test_workspace)

        # Agent can still be created with defaults
        sm = _make_session_manager()
        cfg = _make_agent_config(workspace=test_workspace)
        llm = _make_mock_llm()
        agent_registry._instances[(LLMClient, None)] = llm

        agent = await Agent.create(cfg, llm, sm, agent_id="e2e-broken")
        assert agent is not None
        assert agent.llm_client is llm
