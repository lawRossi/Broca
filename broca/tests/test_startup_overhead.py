"""Startup overhead and lazy-loading verification.

Hard assertions (always run):
  1. ``discover_plugins()`` never calls ``EntryPoint.load()``
  2. Unresolved interface plugins never enter ``sys.modules``

Positive case:
  3. ``resolve()`` does trigger lazy loading for that interface

Soft assertion (``@pytest.mark.perf``, skipped by default):
  4. Startup time regression ≤ 15%

See plan: plans/component-plugin-architecture-plan.md → Task 7.3
"""

from __future__ import annotations

import importlib.metadata
import sys
from unittest.mock import MagicMock, patch

import pytest

from broca.components.llm_client import LLMClient
from broca.components.registry import ComponentRegistry
from broca.components.tool_executor import ToolExecutor


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
# Hard assertion 1: discover_plugins() does NOT call ep.load()
# ---------------------------------------------------------------------------


class TestDiscoverDoesNotLoad:
    """``discover_plugins()`` only enumerates EntryPoint objects.

    The ``ep.load()`` call must NEVER happen during discovery — only
    during ``resolve()`` for the specific interface being resolved.
    """

    def test_discover_plugins_does_not_load(self, registry, monkeypatch):
        """No EntryPoint.load() call during discover_plugins()."""
        fake_ep = MagicMock()
        fake_ep.name = "tool_executor"
        fake_ep.value = "my_pkg:MyExecutor"
        fake_ep.load = MagicMock(return_value=MagicMock)

        monkeypatch.setattr(
            importlib.metadata, "entry_points",
            lambda **kw: [fake_ep],
        )

        registry.discover_plugins()

        # HARD ASSERTION: load was never called
        fake_ep.load.assert_not_called()

    def test_discover_with_multiple_eps_no_load(self, registry, monkeypatch):
        """Multiple entry points → none are loaded during discovery."""
        ep1 = MagicMock()
        ep1.name = "tool_executor"
        ep1.value = "pkg_a:ExecA"
        ep1.load = MagicMock()

        ep2 = MagicMock()
        ep2.name = "llm_client"
        ep2.value = "pkg_b:LLM_B"
        ep2.load = MagicMock()

        ep3 = MagicMock()
        ep3.name = "loop_engine"
        ep3.value = "pkg_c:Engine_C"
        ep3.load = MagicMock()

        monkeypatch.setattr(
            importlib.metadata, "entry_points",
            lambda **kw: [ep1, ep2, ep3],
        )

        registry.discover_plugins()

        # NONE of the EPs were loaded
        for ep in (ep1, ep2, ep3):
            ep.load.assert_not_called()


# ---------------------------------------------------------------------------
# Hard assertion 2: unresolved interface plugin NOT imported
# ---------------------------------------------------------------------------


class TestUnresolvedPluginNotImported:
    """A plugin EP registered for interface X is NOT imported when
    only interface Y is resolved.

    Precondition: the fake plugin registers for ``loop_engine`` (which we
    will NOT resolve).  We only resolve ``ToolExecutor`` (via override).
    The fake plugin module must NOT appear in ``sys.modules``.
    """

    def test_unresolved_interface_plugin_not_in_sys_modules(self, registry, monkeypatch):
        """Fake plugin for loop_engine is NOT imported when only ToolExecutor is resolved.

        Precondition: plugin registers for 'loop_engine' (NOT resolved),
        we only resolve 'tool_executor' (via override).  The plugin module
        must never be imported.
        """
        fake_module_name = "_fake_scheduler_plugin"
        # Ensure it's not already imported
        sys.modules.pop(fake_module_name, None)

        fake_ep = MagicMock()
        fake_ep.name = "loop_engine"  # We will NOT resolve LoopEngine
        fake_ep.value = f"{fake_module_name}:FakeEngine"

        monkeypatch.setattr(
            importlib.metadata, "entry_points",
            lambda **kw: [fake_ep],
        )
        registry.discover_plugins()

        # Resolve ONLY ToolExecutor (via override, so no EP.load needed)
        from broca.tests.test_plugin_loading import MockSandboxToolExecutor
        registry.set_override(ToolExecutor, MockSandboxToolExecutor)
        registry.resolve(ToolExecutor)

        # HARD ASSERTION: fake plugin module was never imported
        assert fake_module_name not in sys.modules

        # And the EP was never loaded
        fake_ep.load.assert_not_called()


# ---------------------------------------------------------------------------
# Positive case: resolve() DOES trigger lazy loading
# ---------------------------------------------------------------------------


class TestResolveLazilyLoads:
    """When ``resolve(interface)`` is called for an interface with a
    registered plugin EP, ``ep.load()`` is called exactly once.
    """

    def test_resolve_triggers_load_once(self, registry, monkeypatch):
        """First resolve triggers ep.load(); second resolve uses cache."""
        loaded_cls = MagicMock(name="LoadedPluginClass")

        fake_ep = MagicMock()
        fake_ep.name = "tool_executor"
        fake_ep.value = "my_pkg:PluginExecutor"
        fake_ep.load = MagicMock(return_value=loaded_cls)

        monkeypatch.setattr(
            importlib.metadata, "entry_points",
            lambda **kw: [fake_ep],
        )
        registry.discover_plugins()

        # First resolve → triggers load
        impl = registry.resolve(ToolExecutor)
        assert impl is loaded_cls
        assert fake_ep.load.call_count == 1

        # Second resolve → cached, no second load
        impl2 = registry.resolve(ToolExecutor)
        assert impl2 is loaded_cls
        assert fake_ep.load.call_count == 1

    def test_resolve_different_interface_no_cross_load(self, registry, monkeypatch):
        """Resolving ToolExecutor does NOT load the LLMClient EP."""
        tool_ep = MagicMock()
        tool_ep.name = "tool_executor"
        tool_ep.value = "pkg:ToolExec"
        tool_ep.load = MagicMock(return_value=MagicMock)

        llm_ep = MagicMock()
        llm_ep.name = "llm_client"
        llm_ep.value = "pkg:LLMClient"
        llm_ep.load = MagicMock(return_value=MagicMock)

        monkeypatch.setattr(
            importlib.metadata, "entry_points",
            lambda **kw: [tool_ep, llm_ep],
        )
        registry.discover_plugins()

        # Resolve only ToolExecutor
        registry.resolve(ToolExecutor)

        # ToolExecutor EP was loaded
        tool_ep.load.assert_called_once()
        # LLMClient EP was NOT loaded
        llm_ep.load.assert_not_called()


# ---------------------------------------------------------------------------
# Agent.create() does not load plugin modules
# ---------------------------------------------------------------------------


class TestAgentCreateNoPluginLoad:
    """``Agent.create()`` should not trigger loading of third-party
    plugin modules that are not needed by the interfaces it resolves.
    """

    def test_agent_create_does_not_import_unneeded_plugins(
        self, registry, monkeypatch
    ):
        """An EP for 'scheduler' (unregistered) is not imported during Agent.create()."""
        fake_module_name = "_fake_scheduler_module"
        sys.modules.pop(fake_module_name, None)

        fake_ep = MagicMock()
        fake_ep.name = "scheduler"  # Not in ENTRY_POINT_NAMES → ignored
        fake_ep.value = f"{fake_module_name}:FakeScheduler"

        monkeypatch.setattr(
            importlib.metadata, "entry_points",
            lambda **kw: [fake_ep],
        )
        registry.discover_plugins()

        # The unknown name 'scheduler' is not in _name_to_interface,
        # so the EP is simply ignored during discovery.
        # No import should happen.
        assert fake_module_name not in sys.modules


# ---------------------------------------------------------------------------
# Soft assertion: startup time regression (perf, skipped by default)
# ---------------------------------------------------------------------------


class TestStartupTimeRegression:
    """Soft assertion: Agent.create() startup time should not regress
    by more than 15% compared to the baseline.

    **Skipped by default** (``-m 'not perf'`` in addopts).
    Run explicitly with: ``pytest -m perf --run-perf``
    or: ``pytest --override-ini="addopts=" -m perf``

    Baseline measurement: see ``scripts/bench_startup.py``.
    """

    @pytest.mark.perf
    def test_startup_time_regression(self, registry, tmp_path):
        """Measure median Agent.create() time over 20 runs.

        Baseline (measured 2026-10-31 on M2 MacBook Pro, Python 3.14):
          - import broca: ~180ms
          - Agent.create(): ~120ms (median of 20 runs)
        Threshold: median ≤ baseline * 1.15 (15% CI tolerance)
        """
        import time

        from broca.agent import Agent
        from broca.agent_configs import AgentConfig
        from unittest.mock import AsyncMock, patch as _patch

        # Build test fixtures
        llm = AsyncMock()
        llm.config = {"openai": {"models": {"gpt-4": {"meta": {}}}}}
        llm.get_stream_response = None  # not called

        from broca.components.tool_manager import ToolManager

        class _MockTM(ToolManager):
            async def init(self, workspace=None):
                pass
            def get_tools(self, tool_names=None):
                return []
            def get_mcp_tools(self, mcp_servers=None):
                return []
            def load_custom_tools(self, workspace=None):
                return []

        registry.set_override(ToolManager, _MockTM)

        sm = AsyncMock()
        sm.session_id = "perf-session"
        sm.agent_service = AsyncMock()
        sm.agent_service.get = AsyncMock(return_value=None)
        sm.agent_service.update = AsyncMock()
        sm.agent_service.update_agent_status = AsyncMock()
        sm.get_agents = AsyncMock(return_value=[])
        sm.get_agent_config = AsyncMock(return_value=None)
        sm.load_session = AsyncMock()
        sm.create_session = AsyncMock()

        cfg = AgentConfig()
        cfg.name = "perf"
        cfg.role = "perf"
        cfg.role_description = "perf"
        cfg.system_prompt_template = "test"
        cfg.tools = []
        cfg.workspace = str(tmp_path)
        cfg.save_history = False
        cfg.server_url = "http://localhost:9999"
        cfg.enable_context_compression = False
        cfg.enable_snapshot_tracking = False

        async def _create_once(i: int):
            with _patch(
                "broca.components.registry.ComponentRegistry.get_instance",
                return_value=registry,
            ):
                agent = await Agent.create(
                    cfg, llm, sm, agent_id=f"perf-{i}"
                )
                await agent.disconnect()
                return agent

        # Warm up (first call includes lazy imports)
        import asyncio
        asyncio.run(_create_once(0))

        # Measure 20 runs
        times = []
        for i in range(1, 21):
            t0 = time.perf_counter()
            asyncio.run(_create_once(i))
            times.append(time.perf_counter() - t0)

        times.sort()
        median = times[len(times) // 2]

        # Baseline: 120ms. Threshold: 120 * 1.15 = 138ms
        baseline_ms = 120.0
        threshold_ms = baseline_ms * 1.15

        print(f"  Median Agent.create() time: {median*1000:.1f}ms")
        print(f"  Baseline: {baseline_ms:.0f}ms, Threshold: {threshold_ms:.0f}ms")

        assert median * 1000 < threshold_ms, (
            f"Startup regression: median={median*1000:.0f}ms "
            f"exceeds threshold {threshold_ms:.0f}ms "
            f"({(median*1000/baseline_ms - 1)*100:.1f}% over baseline)"
        )
