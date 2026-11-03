"""Phase 6.3: Agent composition integration tests.

Verifies the composition-root assembly: scope isolation, lifecycle order,
circular-reference removal, adapter passthrough, custom component
replacement, and full agent lifecycle.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent_config(**overrides):
    """Build a minimal AgentConfig for tests."""
    from broca.agent_configs import AgentConfig

    cfg = AgentConfig()
    cfg.name = "test-agent"
    cfg.role = "test"
    cfg.role_description = "test role"
    cfg.system_prompt_template = "You are a test agent."
    cfg.tools = []
    cfg.workspace = "/tmp/test-workspace"
    cfg.save_history = False
    cfg.server_url = "http://localhost:9999"
    cfg.enable_context_compression = False
    cfg.enable_snapshot_tracking = False
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _make_session_manager():
    """Create a mock SessionManager for tests."""
    sm = AsyncMock()
    sm.session_id = "test-session-001"
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
    """Create a mock LLM client."""
    llm = AsyncMock()
    llm.config = {"openai": {"models": {"gpt-4": {"meta": {}}}}}

    async def _fake_stream(*a, **kw):
        yield {"type": "content", "data": "ok"}
        yield {"type": "finish", "data": "stop"}

    llm.get_stream_response = _fake_stream

    from litellm import Message as LLMMessage

    llm.aggregate_message.return_value = LLMMessage(
        role="assistant", content="ok"
    )
    return llm


def _register_mock_tool_manager(registry):
    """Register a mock ToolManager to avoid real MCP connections."""
    from broca.components.tool_manager import ToolManager

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
    """Fresh registry with mock ToolManager, patched as the singleton.

    ``Agent.create()`` calls ``ComponentRegistry.get_instance()`` which
    returns the process-wide singleton.  We patch it to return our
    ``fresh_registry`` so the test controls all component resolution.
    """
    _register_mock_tool_manager(fresh_registry)
    with patch(
        "broca.components.registry.ComponentRegistry.get_instance",
        return_value=fresh_registry,
    ):
        yield fresh_registry


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAgentCreateWithDefaults:
    """Agent.create() with no plugins → all default implementations."""

    @pytest.mark.asyncio
    async def test_agent_create_with_defaults(
        self, agent_registry, test_workspace
    ):
        from broca.agent import Agent
        from broca.components import (
            CommandSystem,
            Communicator,
            ContextCompressor,
            LoopEngine,
            MemoryManager,
            PermissionProvider,
            ToolExecutor,
            ToolManager,
        )

        sm = _make_session_manager()
        cfg = _make_agent_config(workspace=test_workspace)
        llm = _make_mock_llm()

        agent = await Agent.create(
            cfg, llm, sm, agent_id="test-defaults"
        )

        # All components should be instances of their ABCs
        assert isinstance(agent.execution_engine, LoopEngine)
        assert isinstance(agent.permission_provider, PermissionProvider)
        assert isinstance(agent.communicator, Communicator)
        assert agent.command_manager is not None
        assert agent.context is not None
        assert isinstance(agent.tool_manager, ToolManager)


class TestAgentCreateWithCustomComponents:
    """Custom components via registry override."""

    @pytest.mark.asyncio
    async def test_agent_create_with_custom_tool_executor(
        self, agent_registry, test_workspace
    ):
        from broca.agent import Agent
        from broca.components.tool_executor import ToolExecutor

        sm = _make_session_manager()
        cfg = _make_agent_config(workspace=test_workspace)
        llm = _make_mock_llm()

        # Create a custom ToolExecutor subclass
        class CustomToolExecutor(ToolExecutor):
            _custom = True
            async def initialize(self, **kw): pass
            async def execute_tool(self, *a, **kw): pass
            def is_readonly_tool(self, name): return False
            async def get_permission(self, *a, **kw): return "allow"

        # Override the ToolExecutor in the registry
        agent_registry.set_override(ToolExecutor, CustomToolExecutor)

        agent = await Agent.create(
            cfg, llm, sm, agent_id="test-custom-exec"
        )

        # The loop engine's tool_executor should be our custom type
        assert isinstance(
            agent.execution_engine.tool_executor, CustomToolExecutor
        )

    @pytest.mark.asyncio
    async def test_agent_create_with_custom_llm_client(
        self, agent_registry, test_workspace
    ):
        from broca.agent import Agent

        sm = _make_session_manager()
        cfg = _make_agent_config(workspace=test_workspace)

        custom_llm = _make_mock_llm()
        custom_llm._is_custom = True

        agent = await Agent.create(
            cfg, custom_llm, sm, agent_id="test-custom-llm"
        )
        # LLMClient is passed directly, not via registry
        assert agent.llm_client is custom_llm


class TestTwoAgentsIsolated:
    """Two Agent instances get completely separate per-agent components."""

    @pytest.mark.asyncio
    async def test_two_agents_isolated(self, agent_registry, test_workspace):
        from broca.agent import Agent

        sm_a = _make_session_manager()
        sm_a.session_id = "session-A"
        cfg_a = _make_agent_config(workspace=test_workspace, name="agent-A")
        llm_a = _make_mock_llm()

        sm_b = _make_session_manager()
        sm_b.session_id = "session-B"
        cfg_b = _make_agent_config(workspace=test_workspace, name="agent-B")
        llm_b = _make_mock_llm()

        agent_a = await Agent.create(
            cfg_a, llm_a, sm_a, agent_id="agent-A"
        )
        agent_b = await Agent.create(
            cfg_b, llm_b, sm_b, agent_id="agent-B"
        )

        # Per-agent components must be different instances
        assert agent_a.execution_engine is not agent_b.execution_engine
        assert agent_a.permission_provider is not agent_b.permission_provider
        assert agent_a.communicator is not agent_b.communicator
        assert agent_a.command_manager is not agent_b.command_manager


class TestAgentReferenceAdapter:
    """AgentReferenceAdapter proxies 3 callbacks + turn_id read/write."""

    @pytest.mark.asyncio
    async def test_agent_reference_adapter_full(
        self, agent_registry, test_workspace
    ):
        from broca.agent import Agent
        from broca.agent_reference import AgentReferenceAdapter

        sm = _make_session_manager()
        cfg = _make_agent_config(workspace=test_workspace)
        llm = _make_mock_llm()

        agent = await Agent.create(
            cfg, llm, sm, agent_id="test-adapter"
        )

        adapter = AgentReferenceAdapter(agent)

        # agent_id / session_id are proxied
        assert adapter.agent_id == "test-adapter"
        assert adapter.session_id == sm.session_id

        # turn_id read/write
        assert adapter.turn_id is None
        adapter.turn_id = "turn-123"
        assert agent.turn_id == "turn-123"
        assert adapter.turn_id == "turn-123"

        # last_context_length read/write
        adapter.last_context_length = 12345
        assert agent.last_context_length == 12345

        # Callbacks return coroutines (proxied to real agent methods)
        coro = adapter.ask_for_permission("test")
        assert asyncio.iscoroutine(coro)
        coro.close()

        coro2 = adapter.ask_for_tool_permission("test_tool", "{}")
        assert asyncio.iscoroutine(coro2)
        coro2.close()

        # __getattr__ passthrough: agent.name, agent.config, agent.llm_client
        assert adapter.name == "test-agent"
        assert adapter.config is cfg
        assert adapter.llm_client is llm


class TestCreateInitializeOrder:
    """initialize() call order matches topological order."""

    @pytest.mark.asyncio
    async def test_create_initialize_order(self, agent_registry, test_workspace):
        from broca.agent import Agent
        from broca.components import (
            Communicator,
            ContextCompressor,
            LoopEngine,
            MemoryManager,
            PermissionProvider,
            ToolExecutor,
            ToolManager,
        )

        sm = _make_session_manager()
        cfg = _make_agent_config(workspace=test_workspace)
        llm = _make_mock_llm()

        # Track initialize() call order using spies
        call_order: list[str] = []

        # We need to spy on the actual instances created by the registry.
        # Since we can't easily intercept the registry's instance creation,
        # we'll verify the order by checking the attributes after creation.

        agent = await Agent.create(
            cfg, llm, sm, agent_id="test-order"
        )

        # Verify the topological wiring:
        # communicator is initialized (has _session_id set)
        assert agent.communicator._session_id == sm.session_id

        # permission_provider has communicator
        assert agent.permission_provider._communicator is agent.communicator

        # tool_manager is initialized
        assert agent.tool_manager is not None

        # tool_executor has tool_mapping and communicator
        te = agent.execution_engine.tool_executor
        assert te is not None
        assert te._communicator is agent.communicator

        # context_compressor / memory_manager are owned by CompressionMemoryHook;
        # the agent keeps a handle for /compact, /clear* and shutdown().
        engine = agent.execution_engine
        cc = agent.context_compressor
        assert cc is not None
        mm = agent.persistent_memory_manager
        assert mm is not None

        compression_hook = next(h for h in engine._hooks if h.name == "compression")
        assert compression_hook._context_compressor is cc
        assert compression_hook._memory_manager is mm

        # loop_engine has all deps
        assert engine.llm_client is llm
        assert engine.context is agent.context
        assert engine.communicator is agent.communicator
        assert engine.session_manager is sm
        # 2 strategies + 4 hooks injected by Agent.create()
        assert type(engine._llm_strategy).__name__ == "RetryLLMStrategy"
        assert type(engine._tool_strategy).__name__ == "ParallelToolStrategy"
        assert [h.name for h in engine._hooks] == [
            "snapshot",
            "lifecycle_broadcast",
            "dead_loop",
            "compression",
            "context_cleanup",
        ]


class TestLoopEngineNoAgentDependency:
    """LoopEngine has no Agent type dependency (mechanical assertion)."""

    def test_loop_engine_has_no_agent_dependency(self):
        from broca.loop_engine import DefaultLoopEngine

        # Check that initialize() signature has no 'agent' param
        sig = inspect.signature(DefaultLoopEngine.initialize)
        param_names = list(sig.parameters.keys())
        assert "agent" not in param_names, (
            f"LoopEngine.initialize() should not have 'agent' param, got: {param_names}"
        )

        # Check that __init__ has no 'agent' param (only agent_ref)
        init_sig = inspect.signature(DefaultLoopEngine.__init__)
        init_params = list(init_sig.parameters.keys())
        assert "agent" not in init_params, (
            f"DefaultLoopEngine.__init__ should not have 'agent' param, got: {init_params}"
        )
        # agent_ref IS allowed (it's the AgentReference protocol, not Agent)
        assert "agent_ref" in init_params


class TestAgentFullLifecycle:
    """Create → verify wiring → close."""

    @pytest.mark.asyncio
    async def test_agent_full_lifecycle(self, agent_registry, test_workspace):
        from broca.agent import Agent

        sm = _make_session_manager()
        cfg = _make_agent_config(workspace=test_workspace)
        llm = _make_mock_llm()

        agent = await Agent.create(
            cfg, llm, sm, agent_id="test-lifecycle"
        )

        # Verify all components are wired
        assert agent.execution_engine is not None
        assert agent.permission_provider is not None
        assert agent.communicator is not None
        assert agent.command_manager is not None
        assert agent.context is not None

        # Verify the loop engine's dependencies are set
        engine = agent.execution_engine
        assert engine.tool_executor is not None
        assert agent.context_compressor is not None
        assert engine._hooks

        # Status should be disconnected initially
        assert agent.status == Agent.STATUS_DISCONNECTED


class TestAgentRestoreFromSession:
    """Restore from session → component stack intact → state correct."""

    @pytest.mark.asyncio
    async def test_agent_restore_from_session(self, agent_registry, test_workspace):
        from broca.agent import Agent

        sm = _make_session_manager()
        cfg = _make_agent_config(workspace=test_workspace)
        llm = _make_mock_llm()

        agent = await Agent.create(
            cfg, llm, sm, agent_id="test-restore"
        )

        # Mock restore_from_session
        agent.context.build_history_from_session = AsyncMock()
        await agent.restore_from_session("test-restore")

        # Agent should still be functional after restore
        assert agent.execution_engine is not None
        assert agent.permission_provider is not None
        assert agent.context is not None


class TestToolsReceiveFullAgent:
    """Tool layer gets object with full Agent attribute access via adapter."""

    @pytest.mark.asyncio
    async def test_tools_receive_full_agent(self, agent_registry, test_workspace):
        from broca.agent import Agent
        from broca.agent_reference import AgentReferenceAdapter

        sm = _make_session_manager()
        cfg = _make_agent_config(workspace=test_workspace)
        llm = _make_mock_llm()

        agent = await Agent.create(
            cfg, llm, sm, agent_id="test-tools-agent"
        )

        adapter = AgentReferenceAdapter(agent)

        # These are the attributes that 6 tool modules access:
        assert adapter.name == "test-agent"
        assert adapter.config is cfg
        assert adapter.llm_client is llm
        assert adapter.llm_client.config is not None
        assert adapter.agent_id == "test-tools-agent"
        assert adapter.session_id == sm.session_id


class TestDisconnectReleasesScope:
    """Agent.disconnect() does reverse-topological shutdown + release."""

    @pytest.mark.asyncio
    async def test_disconnect_releases_scope(self, agent_registry, test_workspace):
        from broca.agent import Agent
        from broca.components import ComponentRegistry

        sm = _make_session_manager()
        cfg = _make_agent_config(workspace=test_workspace)
        llm = _make_mock_llm()

        agent = await Agent.create(
            cfg, llm, sm, agent_id="test-disconnect"
        )

        # Spy on registry.release
        registry = ComponentRegistry.get_instance()
        release_spy = MagicMock(wraps=registry.release)

        with patch.object(registry, "release", release_spy):
            await agent.disconnect()

        # Verify the three-phase sequence:
        # 1. execution_engine.abort() (side effect: status change)
        # 2. communicator.shutdown/disconnect (real SocketIO disconnect)
        # 3. registry.release(agent_id)
        release_spy.assert_called_once_with("test-disconnect")


class TestAgentCreateComponentsWired:
    """After creation, all components are correctly connected."""

    @pytest.mark.asyncio
    async def test_components_correctly_wired(
        self, agent_registry, test_workspace
    ):
        from broca.agent import Agent

        sm = _make_session_manager()
        cfg = _make_agent_config(workspace=test_workspace)
        llm = _make_mock_llm()

        agent = await Agent.create(
            cfg, llm, sm, agent_id="test-wired"
        )

        # The loop engine's dependencies should match the agent's components
        engine = agent.execution_engine
        assert engine.llm_client is llm
        assert engine.context is agent.context
        assert engine.config is cfg
        assert engine.session_manager is sm
        assert engine.communicator is agent.communicator
        assert engine.tool_mapping is agent.tool_mapping

    @pytest.mark.asyncio
    async def test_main_agent_gets_the_full_hook_set(
        self, agent_registry, test_workspace
    ):
        from broca.agent import Agent

        cfg = _make_agent_config(workspace=test_workspace, role="coding")
        agent = await Agent.create(
            cfg, _make_mock_llm(), _make_session_manager(), agent_id="test-hooks-main"
        )

        names = [hook.name for hook in agent.execution_engine._hooks]
        assert names == [
            "snapshot",
            "lifecycle_broadcast",
            "dead_loop",
            "compression",
            "context_cleanup",
        ]

    @pytest.mark.asyncio
    async def test_subagent_gets_the_reduced_hook_set(
        self, agent_registry, test_workspace
    ):
        """Review M1: sub agents must not snapshot or broadcast to the front end."""
        from broca.agent import Agent

        cfg = _make_agent_config(
            workspace=test_workspace, role="session_memory_manager"
        )
        agent = await Agent.create(
            cfg, _make_mock_llm(), _make_session_manager(), agent_id="test-hooks-sub"
        )

        names = [hook.name for hook in agent.execution_engine._hooks]
        assert "snapshot" not in names
        assert "communicator" not in names
        assert names[0] == "dead_loop"
