"""LLM strategy component interface.

A ``LLMStrategy`` encapsulates *how* the agent talks to the LLM — retries,
rate limiting, timeouts, empty-response handling and stream aggregation.
The loop engine only orchestrates; it passes thin callbacks so the strategy
stays free of communicator / session / context dependencies.

Callback contracts::

    on_chunk(event)   # streaming broadcast
        {"type": "content",           "data": str,      "index": int, "message_id": str}
        {"type": "reasoning_content", "data": str,      "index": int, "message_id": str}
        {"type": "tool_call",         "data": ToolCall, "message_id": str}  # first sighting only

    on_error(message, code, severity)   # severity: "warning" | "error"

    should_abort()   # checked before each retry iteration and each chunk;
                     # returning True must abort immediately (no sleep, no retry)
                     # with LLMCallResult(success=False, aborted=True)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional

from broca.components.base import BaseComponent

if TYPE_CHECKING:
    from broca.components.llm_client import LLMClient


@dataclass
class LLMCallResult:
    """Outcome of one ``LLMStrategy.call()`` invocation."""

    message: Optional[Any] = None  # aggregated LLMMessage (has .message_id)
    message_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    success: bool = True
    aborted: bool = False  # should_abort hit → True (no sleep, no retry)
    error_code: str = ""
    error_message: str = ""


class LLMStrategy(BaseComponent, ABC):
    """Strategy interface for a single LLM call (including streaming).

    Concrete strategies own retry/rate-limit/timeout policy.  They must not
    depend on ``communicator``, ``session_manager`` or ``context`` — everything
    outward-facing goes through the ``on_chunk`` / ``on_error`` callbacks.
    """

    name: str = "llm_strategy"  # non-abstract; every strategy should override

    @abstractmethod
    async def call(
        self,
        history: list,
        tools: list[dict],
        *,
        on_chunk: Optional[Callable[[dict], Awaitable[None]]] = None,
        on_error: Optional[Callable[[str, str, str], Awaitable[None]]] = None,
        should_abort: Optional[Callable[[], bool]] = None,
    ) -> LLMCallResult:
        """Call the LLM and return the aggregated result.

        Args:
            history: Conversation history (already parsed message dicts).
            tools: Tool definitions to advertise to the model.
            on_chunk: Streaming broadcast callback (see module docstring).
            on_error: Error notification callback ``(message, code, severity)``.
            should_abort: Abort predicate; checked before each retry iteration
                and before each chunk is processed.

        Returns:
            ``LLMCallResult`` describing the outcome.
        """
        ...

    @abstractmethod
    async def initialize(self, *, llm_client: "LLMClient", config: Any) -> None:
        """Inject required dependencies.

        Args:
            llm_client: Client used to open the stream and aggregate chunks.
            config: Agent configuration (provider, model, timeout and retry
                parameters are all read from here).
        """
        ...

    def reset(self) -> None:
        """Reset internal state (e.g. rate-limit counters).

        Called by the engine on ``reset()`` and at the start of every turn.
        The default implementation is a no-op.
        """
