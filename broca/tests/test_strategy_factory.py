"""Unit tests for the strategy factory + configuration priority (Task 2.3).

Priority under test:
    AgentConfig attribute > execution_config > built-in default
"""

from __future__ import annotations

from typing import Optional

import pytest

from broca.loop_engine.strategies.factory import (
    create_llm_strategy,
    create_tool_strategy,
    resolve_tool_execution_mode,
)
from broca.loop_engine.strategies.parallel_tool import ParallelToolStrategy
from broca.loop_engine.strategies.retry_llm import RetryLLMStrategy
from broca.loop_engine.strategies.serial_tool import SerialToolStrategy


class FakeExecConfig:
    def __init__(self, mode: Optional[str] = None, max_parallel: Optional[int] = None):
        self.tool_execution_mode = mode
        self.max_parallel_tools = max_parallel


class FakeAgentConfig:
    def __init__(
        self,
        agent_mode: Optional[str] = None,
        exec_mode: Optional[str] = None,
        agent_max_parallel: Optional[int] = None,
        exec_max_parallel: Optional[int] = None,
    ):
        self.tool_execution_mode = agent_mode
        self.max_parallel_tools = agent_max_parallel
        self.execution_config = FakeExecConfig(exec_mode, exec_max_parallel)


class TestToolStrategySelection:
    def test_agent_level_override_wins(self):
        config = FakeAgentConfig(agent_mode="serial", exec_mode="parallel")
        assert isinstance(create_tool_strategy(config), SerialToolStrategy)

    def test_execution_config_used_when_agent_level_is_none(self):
        config = FakeAgentConfig(agent_mode=None, exec_mode="serial")
        assert isinstance(create_tool_strategy(config), SerialToolStrategy)

    def test_default_is_parallel_when_both_none(self):
        config = FakeAgentConfig(agent_mode=None, exec_mode=None)
        assert isinstance(create_tool_strategy(config), ParallelToolStrategy)
        assert resolve_tool_execution_mode(config) == "parallel"

    def test_agent_level_parallel_overrides_serial_exec_config(self):
        config = FakeAgentConfig(agent_mode="parallel", exec_mode="serial")
        assert isinstance(create_tool_strategy(config), ParallelToolStrategy)

    def test_missing_config_falls_back_to_parallel(self):
        assert isinstance(create_tool_strategy(None), ParallelToolStrategy)


class TestLLMStrategySelection:
    def test_returns_retry_strategy(self):
        assert isinstance(create_llm_strategy(FakeAgentConfig()), RetryLLMStrategy)

    def test_works_without_config(self):
        assert isinstance(create_llm_strategy(), RetryLLMStrategy)


class TestParameterResolutionPriority:
    @pytest.mark.asyncio
    async def test_max_parallel_tools_agent_level_wins(self):
        config = FakeAgentConfig(agent_max_parallel=3, exec_max_parallel=9)
        strategy = ParallelToolStrategy()
        await strategy.initialize(tool_executor=object(), config=config)
        assert strategy._max_parallel == 3

    @pytest.mark.asyncio
    async def test_max_parallel_tools_execution_config_fallback(self):
        config = FakeAgentConfig(agent_max_parallel=None, exec_max_parallel=9)
        strategy = ParallelToolStrategy()
        await strategy.initialize(tool_executor=object(), config=config)
        assert strategy._max_parallel == 9

    @pytest.mark.asyncio
    async def test_max_parallel_tools_default(self):
        config = FakeAgentConfig()
        config.execution_config.max_parallel_tools = None
        strategy = ParallelToolStrategy()
        await strategy.initialize(tool_executor=object(), config=config)
        assert strategy._max_parallel == 10

    @pytest.mark.asyncio
    async def test_invalid_max_parallel_tools_is_ignored(self):
        config = FakeAgentConfig(agent_max_parallel=0, exec_max_parallel=-5)
        strategy = ParallelToolStrategy()
        await strategy.initialize(tool_executor=object(), config=config)
        assert strategy._max_parallel == 10

    @pytest.mark.asyncio
    async def test_llm_params_use_execution_config(self):
        config = FakeAgentConfig()
        config.execution_config.step_max_errors = 5
        config.execution_config.llm_retry_delay = 2
        config.execution_config.llm_timeout = 60
        strategy = RetryLLMStrategy()
        await strategy.initialize(llm_client=object(), config=config)
        assert (strategy._max_errors, strategy._retry_delay, strategy._timeout) == (
            5,
            2,
            60,
        )

    @pytest.mark.asyncio
    async def test_llm_params_agent_level_attribute_wins(self):
        config = FakeAgentConfig()
        config.step_max_errors = 7
        config.execution_config.step_max_errors = 5
        strategy = RetryLLMStrategy()
        await strategy.initialize(llm_client=object(), config=config)
        assert strategy._max_errors == 7

    @pytest.mark.asyncio
    async def test_llm_params_default_when_missing(self):
        class BareConfig:
            provider = "p"
            model = "m"

        strategy = RetryLLMStrategy()
        await strategy.initialize(llm_client=object(), config=BareConfig())
        assert (strategy._max_errors, strategy._retry_delay, strategy._timeout) == (
            3,
            5,
            300,
        )
