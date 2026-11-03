"""Loop engine strategies (Phase 2).

LLM and tool execution strategies: retry/serial/parallel implementations
and their factory.  Phase 2 owns this package.

Strategies encapsulate *how* the engine performs an operation; they never
depend on communicator / session_manager / context (everything outward-facing
goes through callbacks supplied by the engine).
"""

from broca.loop_engine.strategies.factory import (
    create_llm_strategy,
    create_tool_strategy,
    resolve_tool_execution_mode,
)
from broca.loop_engine.strategies.parallel_tool import ParallelToolStrategy
from broca.loop_engine.strategies.retry_llm import RetryLLMStrategy
from broca.loop_engine.strategies.serial_tool import SerialToolStrategy

__all__ = [
    "ParallelToolStrategy",
    "RetryLLMStrategy",
    "SerialToolStrategy",
    "create_llm_strategy",
    "create_tool_strategy",
    "resolve_tool_execution_mode",
]
