"""Plugin loading tests — end-to-end verification of the component plugin system.

Covers 6 scenarios:
1. Entry point discovery (monkeypatched)
2. Config override via components.json
3. Default fallback (no plugin configured)
4. Error handling (broken config → warn + fallback, Agent still starts)
5. Multi-plugin conflict (two entry points, same interface)
6. Scope isolation (plugin replacement → per-agent instances)
"""

from __future__ import annotations

import importlib.metadata
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broca.components.communicator import Communicator
from broca.components.errors import ComponentError
from broca.components.llm_client import LLMClient
from broca.components.loop_engine import LoopEngine
from broca.components.permission_provider import PermissionProvider
from broca.components.registry import ComponentRegistry
from broca.components.tool_executor import ToolExecutor


# ---------------------------------------------------------------------------
# Test plugin: minimal ToolExecutor implementation
# ---------------------------------------------------------------------------


class MockSandboxToolExecutor(ToolExecutor):
    """A minimal ToolExecutor for plugin loading tests."""

    def __init__(self, **kwargs) -> None:
        self.initialized = False
        self.tool_mapping = None
        self.permission_provider = None

    async def initialize(self, tool_mapping, permission_provider, config, communicator):
        self.tool_mapping = tool_mapping
        self.permission_provider = permission_provider
        self.initialized = True

    async def execute_tool(self, **kwargs):
        """Returns a sandbox-style result."""
        from broca.tools.tool import ToolResult, ToolStatus

        tool_name = kwargs.get("tool_name", "unknown")
        return ToolResult(
            status=ToolStatus.SUCCESS,
            content=f"[sandbox] {tool_name} executed in sandbox",
        )

    def get_permission(self, tool_name: str) -> str:
        return "allow"

    def is_readonly_tool(self, tool_name: str) -> bool:
        return False

    async def shutdown(self):
        self.initialized = False


class MockSandboxLLMClient(LLMClient):
    """A minimal LLMClient for plugin loading tests."""

    def __init__(self, **kwargs) -> None:
        self.model = "mock-sandbox-llm"

    async def get_stream_response(self, **kwargs):
        yield {"type": "content", "data": "sandbox llm response"}
        yield {"type": "finish", "data": "stop"}

    def aggregate_message(self, chunks):
        from litellm import Message
        return Message(role="assistant", content="sandbox llm response")


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> ComponentRegistry:
    reg = ComponentRegistry()
    reg.register_defaults()
    yield reg
    reg.reset()


# ---------------------------------------------------------------------------
# 1. Entry point discovery
# ---------------------------------------------------------------------------


class TestEntryPointDiscovery:
    def test_discover_finds_plugin_entry_point(self, registry, monkeypatch):
        """monkeypatch entry_points() → discover_plugins caches the EP."""
        fake_ep = MagicMock()
        fake_ep.name = "tool_executor"
        fake_ep.value = "my_pkg:MockSandboxToolExecutor"
        fake_ep.load = MagicMock(return_value=MockSandboxToolExecutor)

        monkeypatch.setattr(
            importlib.metadata, "entry_points",
            lambda **kw: [fake_ep],
        )

        registry.discover_plugins()

        assert ToolExecutor in registry._entry_points
        assert registry._entry_points[ToolExecutor] is fake_ep

    def test_resolve_triggers_ep_load(self, registry, monkeypatch):
        """Resolving an interface with a plugin EP triggers ep.load()."""
        fake_ep = MagicMock()
        fake_ep.name = "tool_executor"
        fake_ep.value = "my_pkg:MockSandboxToolExecutor"
        fake_ep.load = MagicMock(return_value=MockSandboxToolExecutor)

        monkeypatch.setattr(
            importlib.metadata, "entry_points",
            lambda **kw: [fake_ep],
        )
        registry.discover_plugins()

        impl = registry.resolve(ToolExecutor)

        assert impl is MockSandboxToolExecutor
        assert fake_ep.load.call_count == 1

    def test_unresolved_interface_ep_not_loaded(self, registry, monkeypatch):
        """An EP for LLMClient is NOT loaded when only ToolExecutor is resolved."""
        tool_ep = MagicMock()
        tool_ep.name = "tool_executor"
        tool_ep.value = "my_pkg:MockSandboxToolExecutor"
        tool_ep.load = MagicMock(return_value=MockSandboxToolExecutor)

        llm_ep = MagicMock()
        llm_ep.name = "llm_client"
        llm_ep.value = "my_pkg:MockSandboxLLMClient"
        llm_ep.load = MagicMock(return_value=MockSandboxLLMClient)

        monkeypatch.setattr(
            importlib.metadata, "entry_points",
            lambda **kw: [tool_ep, llm_ep],
        )
        registry.discover_plugins()

        # Resolve only ToolExecutor
        registry.resolve(ToolExecutor)

        # LLMClient EP should NOT have been loaded
        llm_ep.load.assert_not_called()


# ---------------------------------------------------------------------------
# 2. Config override via components.json
# ---------------------------------------------------------------------------


class TestConfigOverride:
    def test_workspace_config_overrides_default(self, registry, tmp_path):
        """components.json in workspace overrides the default implementation."""
        # Write a config that points to our test plugin
        broca_dir = tmp_path / ".broca"
        broca_dir.mkdir()
        config_file = broca_dir / "components.json"
        config_file.write_text(json.dumps({
            "tool_executor": "broca.tests.test_plugin_loading:MockSandboxToolExecutor"
        }))

        registry.load_config_overrides(str(tmp_path))

        # resolve should return the test plugin class
        impl = registry.resolve(ToolExecutor)
        assert impl.__name__ == "MockSandboxToolExecutor"

    def test_configs_components_config_takes_priority(self, registry, tmp_path, monkeypatch):
        """configs.json components_config path takes priority over workspace."""
        # Workspace config (should be overridden by configs.json path)
        ws_broca = tmp_path / ".broca"
        ws_broca.mkdir()
        (ws_broca / "components.json").write_text(json.dumps({
            "llm_client": "broca.tests.test_plugin_loading:MockSandboxLLMClient"
        }))

        # Config file path (from configs.json components_config field)
        explicit_config = tmp_path / "explicit_components.json"
        explicit_config.write_text(json.dumps({
            "llm_client": "broca.tests.test_plugin_loading:MockSandboxLLMClient",
            "tool_executor": "broca.tests.test_plugin_loading:MockSandboxToolExecutor",
        }))

        with patch("broca.configs.get_configs") as mock_gc:
            mock_gc.return_value.components_config = str(explicit_config)
            registry.load_config_overrides(str(tmp_path))

        # Both overrides should be loaded from explicit config
        assert registry.resolve(ToolExecutor).__name__ == "MockSandboxToolExecutor"
        assert registry.resolve(LLMClient).__name__ == "MockSandboxLLMClient"


# ---------------------------------------------------------------------------
# 3. Default fallback (no plugin configured)
# ---------------------------------------------------------------------------


class TestDefaultFallback:
    def test_no_config_uses_default(self, registry, tmp_path, monkeypatch):
        """No components.json and no entry points → default implementation used."""
        # Ensure no entry points
        monkeypatch.setattr(
            importlib.metadata, "entry_points", lambda **kw: []
        )
        registry.discover_plugins()
        registry.load_config_overrides(str(tmp_path))

        # Resolve LLMClient → should be LiteLLMClient (default)
        impl = registry.resolve(LLMClient)
        assert impl.__name__ == "LiteLLMClient"

    def test_get_returns_default_instance(self, registry, tmp_path, monkeypatch):
        """registry.get() returns a default implementation instance."""
        monkeypatch.setattr(
            importlib.metadata, "entry_points", lambda **kw: []
        )
        registry.discover_plugins()
        registry.load_config_overrides(str(tmp_path))

        # LLMClient is singleton scope
        client = registry.get(LLMClient)
        assert client.__class__.__name__ == "LiteLLMClient"


# ---------------------------------------------------------------------------
# 4. Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_nonexistent_class_warns_and_falls_back(self, registry, tmp_path):
        """Config with non-existent class → default used, no crash."""
        broca_dir = tmp_path / ".broca"
        broca_dir.mkdir()
        config_file = broca_dir / "components.json"
        config_file.write_text(json.dumps({
            "llm_client": "nonexistent_package.nonexistent_module:FakeLLM"
        }))

        registry.load_config_overrides(str(tmp_path))

        # The override should NOT have been set (import failed)
        assert LLMClient not in registry._overrides

        # Default should still work
        impl = registry.resolve(LLMClient)
        assert impl.__name__ == "LiteLLMClient"

    def test_unknown_key_is_safe(self, registry, tmp_path):
        """Config with unknown key → no crash, no override set."""
        broca_dir = tmp_path / ".broca"
        broca_dir.mkdir()
        (broca_dir / "components.json").write_text(json.dumps({
            "nonexistent_component": "some_mod:SomeClass"
        }))

        registry.load_config_overrides(str(tmp_path))

        # No overrides were set
        assert len(registry._overrides) == 0

    def test_invalid_json_is_safe(self, registry, tmp_path):
        """Malformed JSON → no crash, no overrides."""
        broca_dir = tmp_path / ".broca"
        broca_dir.mkdir()
        (broca_dir / "components.json").write_text("{not valid json")

        registry.load_config_overrides(str(tmp_path))

        # All defaults still work
        impl = registry.resolve(LLMClient)
        assert impl.__name__ == "LiteLLMClient"


# ---------------------------------------------------------------------------
# 5. Multi-plugin conflict
# ---------------------------------------------------------------------------


class TestMultiPluginConflict:
    def test_later_entry_point_wins(self, registry, monkeypatch):
        """When two EPs register the same interface, the later one wins."""
        ep1 = MagicMock()
        ep1.name = "tool_executor"
        ep1.value = "pkg_a:ToolExecA"
        ep1.load = MagicMock(return_value=MockSandboxToolExecutor)

        ep2 = MagicMock()
        ep2.name = "tool_executor"
        ep2.value = "pkg_b:ToolExecB"
        ep2.load = MagicMock(return_value=MockSandboxLLMClient)

        # Both EPs registered; discover iterates and last one wins
        monkeypatch.setattr(
            importlib.metadata, "entry_points",
            lambda **kw: [ep1, ep2],
        )
        registry.discover_plugins()

        # The cached EP should be the LAST one (ep2)
        assert registry._entry_points[ToolExecutor] is ep2

        # Resolving triggers ep2.load()
        impl = registry.resolve(ToolExecutor)
        assert impl is MockSandboxLLMClient
        ep2.load.assert_called_once()
        ep1.load.assert_not_called()


# ---------------------------------------------------------------------------
# 6. Scope isolation with plugin
# ---------------------------------------------------------------------------


class TestPluginScopeIsolation:
    def test_per_agent_plugin_instances_isolated(self, registry, monkeypatch):
        """Two agents get separate plugin instances for per-agent components."""
        monkeypatch.setattr(
            importlib.metadata, "entry_points",
            lambda **kw: [],
        )
        registry.discover_plugins()

        # Override ToolExecutor with our test plugin
        registry.set_override(ToolExecutor, MockSandboxToolExecutor)

        # Two "agents" get different instances
        agent1_exec = registry.get(ToolExecutor, scope_key="agent-1")
        agent2_exec = registry.get(ToolExecutor, scope_key="agent-2")

        assert agent1_exec is not agent2_exec
        assert isinstance(agent1_exec, MockSandboxToolExecutor)
        assert isinstance(agent2_exec, MockSandboxToolExecutor)

    def test_release_releases_plugin_instances(self, registry, monkeypatch):
        """Releasing an agent's scope removes its plugin instances."""
        monkeypatch.setattr(
            importlib.metadata, "entry_points",
            lambda **kw: [],
        )
        registry.discover_plugins()
        registry.set_override(ToolExecutor, MockSandboxToolExecutor)

        agent1_exec = registry.get(ToolExecutor, scope_key="agent-1")
        registry.release("agent-1")

        # After release, a new instance is created
        new_exec = registry.get(ToolExecutor, scope_key="agent-1")
        assert new_exec is not agent1_exec


# ---------------------------------------------------------------------------
# Integration: plugin replacement changes ToolExecutor behavior
# ---------------------------------------------------------------------------


class TestPluginReplacement:
    def test_plugin_tool_executor_changes_behavior(self, registry, monkeypatch):
        """After plugin replacement, execute_tool returns sandbox results."""
        from broca.tests.conftest import run_async
        from broca.tools.tool import ToolResult, ToolStatus

        monkeypatch.setattr(
            importlib.metadata, "entry_points",
            lambda **kw: [],
        )
        registry.discover_plugins()
        registry.set_override(ToolExecutor, MockSandboxToolExecutor)

        executor = registry.get(ToolExecutor, scope_key="agent-test")

        # Initialize with mocks
        comm = AsyncMock()
        perm = AsyncMock()
        perm.get_permission = AsyncMock(return_value="allow")

        async def _init():
            await executor.initialize(
                tool_mapping={"test": None},
                permission_provider=perm,
                config=MagicMock(),
                communicator=comm,
            )
            result = await executor.execute_tool(
                tool_name="test_tool",
                arguments={},
                context=MagicMock(),
                tool=None,
                tool_call_id="call-1",
            )
            return result

        result = run_async(_init())
        assert result.status == ToolStatus.SUCCESS
        assert "sandbox" in result.content
