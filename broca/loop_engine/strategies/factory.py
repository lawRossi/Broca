"""Strategy factory — the single entry point for choosing strategy instances.

Selection is driven by ``AgentConfig`` only (plan decision: the
``ComponentRegistry`` path for strategies is a documented TODO).

Configuration priority for every parameter resolved here:

    explicit argument > AgentConfig attribute (agent-level override)
                     > execution_config (global) > built-in default
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from broca.loop_engine.strategies.parallel_tool import ParallelToolStrategy
from broca.loop_engine.strategies.retry_llm import RetryLLMStrategy
from broca.loop_engine.strategies.serial_tool import SerialToolStrategy

if TYPE_CHECKING:
    from broca.components.llm_strategy import LLMStrategy
    from broca.components.tool_strategy import ToolExecutionStrategy


def resolve_tool_execution_mode(config: Any) -> str:
    """Resolve ``"parallel" | "serial"`` with the documented priority."""
    exec_cfg = getattr(config, "execution_config", None)
    mode = getattr(config, "tool_execution_mode", None)  # agent-level override
    if not (isinstance(mode, str) and mode):
        mode = getattr(exec_cfg, "tool_execution_mode", None)  # global config
    return mode if isinstance(mode, str) and mode else "parallel"  # default


def create_llm_strategy(config: Any = None) -> "LLMStrategy":
    """Create the LLM strategy for ``config``.

    Currently always ``RetryLLMStrategy``; the hook is kept so alternative
    strategies can be selected without touching the engine.
    """
    return RetryLLMStrategy()


def create_tool_strategy(config: Any = None) -> "ToolExecutionStrategy":
    """Create the tool execution strategy for ``config``.

    Priority: ``AgentConfig.tool_execution_mode`` > ``execution_config``
    > ``"parallel"``.
    """
    if resolve_tool_execution_mode(config) == "serial":
        return SerialToolStrategy()
    return ParallelToolStrategy()
