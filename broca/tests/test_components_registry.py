"""ComponentRegistry tests — scoped instantiation, plugin discovery,
lazy loading, config overrides, and lifecycle management."""

from __future__ import annotations

import importlib.metadata
import sys
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from broca.components.agent_factory import AgentFactory
from broca.components.communicator import Communicator
from broca.components.context_compressor import ContextCompressor
from broca.components.errors import ComponentNotFoundError, ComponentScopeError
from broca.components.llm_client import LLMClient
from broca.components.loop_engine import LoopEngine
from broca.components.permission_provider import PermissionProvider
from broca.components.registry import ComponentRegistry
from broca.components.tool_executor import ToolExecutor


# ---------------------------------------------------------------------------
# Fixture: fresh registry per test
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> ComponentRegistry:
    """Provide a fresh, isolated ``ComponentRegistry`` for each test."""
    reg = ComponentRegistry()
    reg.register_defaults()
    yield reg
    reg.reset()


# ---------------------------------------------------------------------------
# Minimal concrete implementations for scope tests
# ---------------------------------------------------------------------------


class _FakeSingleton:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakePerAgent:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeTransient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


# ---------------------------------------------------------------------------
# Scope tests
# ---------------------------------------------------------------------------


class TestSingletonScope:
    def test_same_instance_on_repeated_get(self, registry):
        """LLMClient is singleton — multiple calls return the same instance."""
        # Use a fake singleton to avoid importing heavy LLMClient
        registry.set_override(LLMClient, _FakeSingleton)

        a = registry.get(LLMClient)
        b = registry.get(LLMClient)
        assert a is b

    def test_kwargs_ignored_on_cache_hit(self, registry, monkeypatch):
        """Cache hit with kwargs should return same instance (kwargs ignored)."""
        registry.set_override(LLMClient, _FakeSingleton)
        a = registry.get(LLMClient)

        # Spy on the logger to verify debug message was emitted
        from broca.components.registry import logger as reg_logger

        debug_calls = []
        monkeypatch.setattr(
            reg_logger, "debug",
            lambda msg: debug_calls.append(msg),
        )

        b = registry.get(LLMClient, extra_param="ignored")

        assert a is b
        assert any("cache hit" in msg for msg in debug_calls)


class TestPerAgentScope:
    def test_different_scope_keys_different_instances(self, registry):
        """Communicator is per-agent — different scope_keys get different instances."""
        registry.set_override(Communicator, _FakePerAgent)

        a1 = registry.get(Communicator, scope_key="agent-1")
        a2 = registry.get(Communicator, scope_key="agent-2")
        assert a1 is not a2

    def test_same_scope_key_same_instance(self, registry):
        """Same scope_key returns the cached instance."""
        registry.set_override(Communicator, _FakePerAgent)

        a1 = registry.get(Communicator, scope_key="agent-1")
        a1_again = registry.get(Communicator, scope_key="agent-1")
        assert a1 is a1_again

    def test_missing_scope_key_raises(self, registry):
        """Per-agent component without scope_key raises ComponentScopeError."""
        registry.set_override(Communicator, _FakePerAgent)

        with pytest.raises(ComponentScopeError, match="scope_key is required"):
            registry.get(Communicator)


class TestTransientScope:
    def test_new_instance_every_call(self, registry):
        """Transient components are never cached."""
        # Use a fake interface by overriding a known interface to transient scope
        registry._scopes[AgentFactory] = "transient"
        registry.set_override(AgentFactory, _FakeTransient)

        a = registry.get(AgentFactory)
        b = registry.get(AgentFactory)
        assert a is not b


# ---------------------------------------------------------------------------
# Resolution priority tests
# ---------------------------------------------------------------------------


class TestResolutionPriority:
    def test_override_beats_default(self, registry):
        """Explicit override takes priority over default."""
        registry.set_override(LLMClient, _FakeSingleton)

        impl = registry.resolve(LLMClient)
        assert impl is _FakeSingleton

    def test_discovered_beats_default(self, registry):
        """Discovered plugin takes priority over default."""
        registry._discovered[LLMClient] = _FakeSingleton

        impl = registry.resolve(LLMClient)
        assert impl is _FakeSingleton

    def test_override_beats_discovered(self, registry):
        """Override takes priority over discovered plugin."""
        registry._discovered[LLMClient] = _FakePerAgent
        registry.set_override(LLMClient, _FakeSingleton)

        impl = registry.resolve(LLMClient)
        assert impl is _FakeSingleton

    def test_not_found_raises(self, registry):
        """Unknown interface with no mapping raises ComponentNotFoundError."""

        class UnknownInterface:
            pass

        # Remove from any mapping
        registry._defaults.pop(UnknownInterface, None)
        registry._overrides.pop(UnknownInterface, None)
        registry._discovered.pop(UnknownInterface, None)

        with pytest.raises(ComponentNotFoundError, match="UnknownInterface"):
            registry.resolve(UnknownInterface)


# ---------------------------------------------------------------------------
# Plugin discovery tests
# ---------------------------------------------------------------------------


class TestDiscoverPlugins:
    def test_discovers_entry_points(self, registry, monkeypatch):
        """discover_plugins() finds entry points and caches them (unloaded)."""

        fake_ep = MagicMock()
        fake_ep.name = "llm_client"
        fake_ep.value = "my_pkg:MyLLMClient"

        fake_eps = [fake_ep]
        monkeypatch.setattr(
            importlib.metadata, "entry_points", lambda **kw: fake_eps
        )

        registry.discover_plugins()

        assert LLMClient in registry._entry_points
        assert registry._entry_points[LLMClient] is fake_ep

    def test_discover_is_idempotent(self, registry, monkeypatch):
        """Second call to discover_plugins() is a no-op."""

        fake_ep = MagicMock()
        fake_ep.name = "llm_client"
        fake_ep.value = "my_pkg:MyLLMClient"

        call_count = 0

        def fake_entry_points(**kw):
            nonlocal call_count
            call_count += 1
            return [fake_ep]

        monkeypatch.setattr(
            importlib.metadata, "entry_points", fake_entry_points
        )

        registry.discover_plugins()
        assert call_count == 1

        registry.discover_plugins()
        assert call_count == 1  # No second call

    def test_discover_does_not_load(self, registry, monkeypatch):
        """discover_plugins() must NOT call EntryPoint.load()."""

        fake_ep = MagicMock()
        fake_ep.name = "llm_client"
        fake_ep.value = "my_pkg:MyLLMClient"
        fake_ep.load = MagicMock(return_value=_FakeSingleton)

        monkeypatch.setattr(
            importlib.metadata, "entry_points", lambda **kw: [fake_ep]
        )

        registry.discover_plugins()

        fake_ep.load.assert_not_called()

    def test_resolve_triggers_load(self, registry, monkeypatch):
        """resolve() triggers ep.load() only for the specific interface."""

        fake_ep = MagicMock()
        fake_ep.name = "llm_client"
        fake_ep.value = "my_pkg:MyLLMClient"
        fake_ep.load = MagicMock(return_value=_FakeSingleton)

        monkeypatch.setattr(
            importlib.metadata, "entry_points", lambda **kw: [fake_ep]
        )
        registry.discover_plugins()

        # Resolve LLMClient → should trigger load
        impl = registry.resolve(LLMClient)
        assert impl is _FakeSingleton
        assert fake_ep.load.call_count == 1

        # Resolve again → cached, no second load
        impl2 = registry.resolve(LLMClient)
        assert impl2 is _FakeSingleton
        assert fake_ep.load.call_count == 1

    def test_unresolved_plugin_not_in_sys_modules(self, registry, monkeypatch):
        """A plugin for an interface that is never resolved stays out of sys.modules."""

        # Create a fake module that won't be imported
        fake_module_name = "test_fake_unresolved_plugin"
        if fake_module_name in sys.modules:
            del sys.modules[fake_module_name]

        fake_ep = MagicMock()
        fake_ep.name = "agent_factory"  # We won't resolve AgentFactory
        fake_ep.value = f"{fake_module_name}:FakeFactory"

        monkeypatch.setattr(
            importlib.metadata, "entry_points", lambda **kw: [fake_ep]
        )
        registry.discover_plugins()

        # Resolve a DIFFERENT interface (LLMClient)
        registry.set_override(LLMClient, _FakeSingleton)
        registry.resolve(LLMClient)

        # The unresolved plugin module should NOT be in sys.modules
        assert fake_module_name not in sys.modules


# ---------------------------------------------------------------------------
# Release tests
# ---------------------------------------------------------------------------


class TestRelease:
    def test_release_only_affected_scope(self, registry):
        """release(scope_key) only removes instances for that scope_key."""
        registry.set_override(Communicator, _FakePerAgent)

        a1 = registry.get(Communicator, scope_key="agent-1")
        a2 = registry.get(Communicator, scope_key="agent-2")

        registry.release("agent-1")

        # agent-1's instance is gone
        a1_fresh = registry.get(Communicator, scope_key="agent-1")
        assert a1_fresh is not a1

        # agent-2's instance is still cached
        a2_again = registry.get(Communicator, scope_key="agent-2")
        assert a2_again is a2

    def test_release_nonexistent_key_is_noop(self, registry):
        """Releasing a scope_key with no instances is a safe no-op."""
        registry.set_override(Communicator, _FakePerAgent)
        registry.get(Communicator, scope_key="agent-1")

        # Should not raise
        registry.release("nonexistent-key")


# ---------------------------------------------------------------------------
# Reset tests
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_clears_all(self, registry):
        """reset() clears instances, overrides, discovered, entry_points."""
        registry.set_override(LLMClient, _FakeSingleton)
        registry.get(LLMClient)

        registry._discovered[Communicator] = _FakePerAgent
        registry._entry_points[LoopEngine] = MagicMock()
        registry._plugins_discovered = True

        registry.reset()

        assert len(registry._instances) == 0
        assert len(registry._overrides) == 0
        assert len(registry._discovered) == 0
        assert len(registry._entry_points) == 0
        assert registry._plugins_discovered is False


# ---------------------------------------------------------------------------
# COMPONENT_SCOPES consistency test
# ---------------------------------------------------------------------------


class TestComponentScopes:
    """Verify COMPONENT_SCOPES matches the plan's design table exactly."""

    EXPECTED_SCOPES = {
        ToolExecutor: "per-agent",
        ContextCompressor: "per-agent",
        LLMClient: "singleton",
        PermissionProvider: "per-agent",
        Communicator: "per-agent",
        LoopEngine: "per-agent",
        AgentFactory: "singleton",
    }

    def test_scopes_match_design_table(self, registry):
        """COMPONENT_SCOPES entries for 7 core components match the plan."""
        from broca.components.defaults import COMPONENT_SCOPES

        for interface, expected_scope in self.EXPECTED_SCOPES.items():
            assert interface in COMPONENT_SCOPES, (
                f"{interface.__name__} missing from COMPONENT_SCOPES"
            )
            assert COMPONENT_SCOPES[interface] == expected_scope, (
                f"{interface.__name__} scope is '{COMPONENT_SCOPES[interface]}', "
                f"expected '{expected_scope}'"
            )

    def test_registry_scopes_match_defaults(self, registry):
        """Registry's _scopes must match defaults.COMPONENT_SCOPES."""
        from broca.components.defaults import COMPONENT_SCOPES

        for interface, scope in COMPONENT_SCOPES.items():
            assert registry._scopes.get(interface) == scope, (
                f"Registry scope for {interface.__name__} is "
                f"'{registry._scopes.get(interface)}', "
                f"but defaults says '{scope}'"
            )


# ---------------------------------------------------------------------------
# Config override tests
# ---------------------------------------------------------------------------


class TestConfigOverrides:
    def test_load_workspace_config(self, registry, tmp_path):
        """Load components.json from workspace directory."""
        import json

        broca_dir = tmp_path / ".broca"
        broca_dir.mkdir()
        config_file = broca_dir / "components.json"
        config_file.write_text(
            json.dumps({"llm_client": "_config_test_mod:CustomLLM"})
        )

        # _config_test_mod won't exist, so this tests the warning path.
        # Just verify no crash.
        registry.load_config_overrides(str(tmp_path))

    def test_missing_config_file_is_safe(self, registry, tmp_path):
        """No components.json → no overrides, no crash."""
        registry.load_config_overrides(str(tmp_path))
        assert len(registry._overrides) == 0

    def test_invalid_json_is_safe(self, registry, tmp_path):
        """Malformed JSON → warning, no crash, no overrides."""
        broca_dir = tmp_path / ".broca"
        broca_dir.mkdir()
        (broca_dir / "components.json").write_text("{invalid json")

        registry.load_config_overrides(str(tmp_path))
        assert len(registry._overrides) == 0

    def test_env_var_config_path(self, registry, tmp_path, monkeypatch):
        """BROCA_COMPONENTS_CONFIG env var points to a specific file."""
        import json

        config_file = tmp_path / "custom_components.json"
        config_file.write_text(json.dumps({}))

        monkeypatch.setenv("BROCA_COMPONENTS_CONFIG", str(config_file))
        registry.load_config_overrides(None)
        # Empty config → no overrides, but no crash

    def test_resolve_module_class_colon(self, registry):
        """'module:Class' format resolves correctly."""
        import broca.components.tool_executor as mod

        cls = registry._resolve_module_class(
            "broca.components.tool_executor:ToolExecutor"
        )
        assert cls is ToolExecutor

    def test_resolve_module_class_dot(self, registry):
        """'module.Class' format resolves correctly."""
        cls = registry._resolve_module_class(
            "broca.components.tool_executor.ToolExecutor"
        )
        assert cls is ToolExecutor

    def test_resolve_module_class_invalid(self, registry):
        """Invalid reference raises ValueError."""
        with pytest.raises(ValueError, match="Cannot parse"):
            registry._resolve_module_class("nocolon_nodot")
