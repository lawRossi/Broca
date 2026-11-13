"""Regression: sub agents must always use the main agent's LLM choice.

Bug: the user changed an agent's ``provider`` / ``model`` in the agent
sidebar.  On the next ``/compact`` the session-memory sub agent still called
the old model, because the strategy snapshotted ``provider`` / ``model`` in
``initialize()`` and ``DefaultLoopEngine._ensure_strategies()`` only ever runs
once per agent instance — and sub agent instances are cached in
``AgentFactory._session_agents`` and reused across turns.

Fix: ``RetryLLMStrategy`` reads the target from ``AgentConfig`` on every call,
so updating ``agent.config.provider`` / ``.model`` is enough.  The three
sub-agent call sites re-apply the main agent's choice on every use.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from broca.agent import Agent
from broca.agent_configs import AgentConfig
from broca.context_compressor import SessionMemoryCompressor
from broca.llm import LiteLLMClient
from broca.loop_engine.strategies.retry_llm import RetryLLMStrategy
from broca.persistent_memory.manager import SubAgentMemoryManager
from broca.skill.skill_evolution import run_skill_sub_agent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _ScriptedClient(LiteLLMClient):
    """Real aggregation logic, scripted transport.

    Records the ``(provider, model)`` of every call so tests can assert which
    target the strategy actually used.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def get_stream_response(
        self, provider, model, messages, tools=None, **kwargs
    ):
        self.calls.append((provider, model))
        yield {"type": "content", "data": "ok"}
        yield {
            "type": "usage",
            "data": {"input_tokens": 1, "output_tokens": 1},
        }


class _Exec:
    step_max_errors = 1
    llm_retry_delay = 0
    llm_timeout = 5


class _Cfg:
    def __init__(self, provider: str = "old-provider", model: str = "old-model"):
        self.provider = provider
        self.model = model
        self.execution_config = _Exec()


async def _make_strategy(cfg: _Cfg) -> tuple[RetryLLMStrategy, _ScriptedClient]:
    strategy = RetryLLMStrategy()
    client = _ScriptedClient()
    await strategy.initialize(llm_client=client, config=cfg)
    return strategy, client


def _make_agent() -> Agent:
    cfg = AgentConfig()
    cfg.name = "test-agent"
    cfg.role = "test"
    cfg.system_prompt_template = "test"
    cfg.tools = []
    cfg.workspace = "/tmp/test-workspace"
    cfg.save_history = False
    cfg.enable_context_compression = False
    cfg.enable_snapshot_tracking = False

    sm = AsyncMock()
    sm.session_id = "test-session"
    sm.agent_service = AsyncMock()
    sm.agent_service.get = AsyncMock(return_value=None)

    return Agent(config=cfg, llm_client=MagicMock(), session_manager=sm)


def _cc_ctx(provider: str, model: str) -> MagicMock:
    compact_cfg = MagicMock()
    compact_cfg.session_trunc_threshold = 100000
    compact_cfg.session_trunc_percentage = 0.8
    compact_cfg.keep_steps = 5

    cc = MagicMock()
    cc.session_id = "sess-1"
    cc.communicator = AsyncMock()
    cc.session_manager = AsyncMock()
    cc.compact_config = compact_cfg
    cc.provider = provider
    cc.model = model
    cc.workspace = "/tmp"
    cc.last_context_length = None
    return cc


# ---------------------------------------------------------------------------
# RetryLLMStrategy reads the target from the config on every call
# ---------------------------------------------------------------------------


class TestStrategyReadsConfigLazily:
    @pytest.mark.asyncio
    async def test_initial_target_used(self) -> None:
        strategy, client = await _make_strategy(_Cfg())
        await strategy.call([], [])
        assert client.calls == [("old-provider", "old-model")]

    @pytest.mark.asyncio
    async def test_config_change_takes_effect_without_reinit(self) -> None:
        """The regression: a live agent's config change must be honoured."""
        cfg = _Cfg()
        strategy, client = await _make_strategy(cfg)

        cfg.provider = "new-provider"
        cfg.model = "new-model"
        result = await strategy.call([], [])

        assert result.success is True
        assert client.calls == [("new-provider", "new-model")]

    @pytest.mark.asyncio
    async def test_reset_does_not_lose_target(self) -> None:
        cfg = _Cfg()
        strategy, client = await _make_strategy(cfg)
        cfg.provider = "new-provider"
        cfg.model = "new-model"

        strategy.reset()
        await strategy.call([], [])

        assert client.calls == [("new-provider", "new-model")]


# ---------------------------------------------------------------------------
# Sub-agent call sites
# ---------------------------------------------------------------------------


class TestSubAgentCallSitesUseMainAgentLLM:
    """All three sub-agent runners must mirror the main agent's config."""

    def test_context_compressor(self) -> None:
        source = inspect.getsource(SessionMemoryCompressor._run_extraction_subagent)
        assert "sub_agent.config.provider = compressor_context.provider" in source
        assert "sub_agent.config.model = compressor_context.model" in source

    def test_persistent_memory_manager(self) -> None:
        source = inspect.getsource(SubAgentMemoryManager._run_extraction_subagent)
        assert "sub_agent.config.provider = self.agent.config.provider" in source
        assert "sub_agent.config.model = self.agent.config.model" in source

    def test_skill_evolution(self) -> None:
        source = inspect.getsource(run_skill_sub_agent)
        assert "sub_agent.config.provider = agent.config.provider" in source
        assert "sub_agent.config.model = agent.config.model" in source


class TestContextCompressorSyncsMainAgentLLM:
    """End-to-end at the compressor seam: cached sub agent gets retargeted."""

    @pytest.mark.asyncio
    async def test_cached_sub_agent_gets_main_agent_llm(self, tmp_path) -> None:
        from broca.loop_engine import ExecutionResult, ExecutionStatus

        compressor = SessionMemoryCompressor()
        compressor._agent_id = "agent-1"
        compressor._session_id = "sess-1"
        compressor._workspace = str(tmp_path)
        compressor._config = MagicMock()
        compressor._config.to_dict.return_value = {}
        compressor._initialized = True

        snapshot = Path(compressor.snapshot_memory_path)
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text("original", encoding="utf-8")

        cc_ctx = _cc_ctx("new-provider", "new-model")
        # Existing config row → restore path (the buggy one).
        cc_ctx.session_manager.get_agent_config = AsyncMock(
            return_value={
                "name": "session-memory-agent",
                "role": "session_memory_manager",
            }
        )

        # A *real* Agent so the config write really happens.
        sub_agent = _make_agent()
        sub_agent.config.name = "session-memory-agent"
        sub_agent.config.provider = "stale-provider"
        sub_agent.config.model = "stale-model"
        sub_agent.context = MagicMock()
        sub_agent.running = True

        async def _fake_run(msg, **kwargs):
            snapshot.write_text("updated", encoding="utf-8")
            return ExecutionResult(status=ExecutionStatus.COMPLETED)

        sub_agent.run = AsyncMock(side_effect=_fake_run)

        factory = MagicMock()
        factory.get_agent.return_value = sub_agent

        with pytest.MonkeyPatch.context() as mp:
            registry = MagicMock()
            registry.get.return_value = factory
            mp.setattr(
                "broca.components.ComponentRegistry.get_instance",
                lambda: registry,
            )
            ok = await compressor._run_extraction_subagent(
                user_prompt="summarize",
                old_history=[{"role": "user", "content": "hi"}],
                current_content="original",
                compressor_context=cc_ctx,
            )

        assert ok is True
        assert sub_agent.config.provider == "new-provider"
        assert sub_agent.config.model == "new-model"
        assert sub_agent.config.interactive is False