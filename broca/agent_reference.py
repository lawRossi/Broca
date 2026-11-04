"""AgentReferenceAdapter — narrow proxy for Agent used by components.

This adapter satisfies the ``AgentReference`` protocol while breaking the
``Agent ↔ LoopEngine`` circular reference.  It proxies the four members
declared by the protocol and uses ``__getattr__`` passthrough so that tool
modules can still access full Agent attributes (``agent.name``,
``agent.config``, ``agent.llm_client.config``, etc.) through
``ToolCallContext.agent``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, Tuple
from broca.logging_config import get_logger

if TYPE_CHECKING:
    from broca.agent import Agent

logger = get_logger(__name__)


class AgentReferenceAdapter:
    """Narrow proxy that wraps an ``Agent`` instance.

    Explicitly proxies the members declared by the ``AgentReference``
    protocol.  Any other attribute access falls through to the wrapped
    Agent via ``__getattr__``, preserving backward compatibility for tool
    modules that access ``context.agent.name``, ``context.agent.config``,
    ``context.agent.llm_client.config``, etc.
    """

    def __init__(self, agent: "Agent") -> None:
        # Use object.__setattr__ to avoid triggering __getattr__ during init
        object.__setattr__(self, "_agent", agent)

    # ── AgentReference protocol members ───────────────────────────────

    @property
    def agent_id(self) -> str:
        return self._agent.agent_id

    @property
    def session_id(self) -> Optional[str]:
        return self._agent.session_id

    @property
    def turn_id(self) -> Optional[str]:
        return self._agent.turn_id

    @turn_id.setter
    def turn_id(self, value: Optional[str]) -> None:
        self._agent.turn_id = value

    @property
    def last_context_length(self) -> Optional[int]:
        return self._agent.last_context_length

    @last_context_length.setter
    def last_context_length(self, value: Optional[int]) -> None:
        self._agent.last_context_length = value

    # ── Callbacks (proxied as bound methods) ─────────────────────────

    def on_llm_call_completed(self, input_tokens: int, output_tokens: int) -> Any:
        return self._agent.on_llm_call_completed(input_tokens, output_tokens)

    def ask_for_permission(self, message: str) -> Any:
        return self._agent.ask_for_permission(message)

    def ask_for_tool_permission(
        self, tool_name: str, arguments: str
    ) -> Any:
        return self._agent.ask_for_tool_permission(tool_name, arguments)

    # ── Passthrough for full Agent attribute access ───────────────────

    _KNOWN_AGENT_ATTRS = frozenset({
        "name", "config", "agent_id", "session_id", "turn_id",
        "llm_client", "tool_mapping", "tools", "status",
        "context", "communicator", "session_manager",
    })

    def __getattr__(self, name: str) -> Any:
        """Fall through to the wrapped Agent for any attribute not
        explicitly proxied above.  This is critical for tool modules
        that access ``context.agent.name``, ``context.agent.config``,
        ``context.agent.llm_client.config``, etc.
        """
        if name not in self._KNOWN_AGENT_ATTRS:
            logger.debug(
                "AgentReferenceAdapter.__getattr__('%s') — not in known set; "
                "falling through to Agent. Consider adding to AgentReference protocol.",
                name,
            )
        agent = object.__getattribute__(self, "_agent")
        return getattr(agent, name)

    def __repr__(self) -> str:
        return f"AgentReferenceAdapter(agent_id={self.agent_id!r})"
