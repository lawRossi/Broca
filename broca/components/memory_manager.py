"""MemoryManager ABC — interface for persistent memory extraction.

Manages extraction of persistent memories from conversation context using
a sub-agent. Supports auto-extraction (threshold-based) and on-demand
extraction (tool-triggered).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from broca.context import Context


class MemoryManager(ABC):
    """Abstract base class for persistent memory extraction managers.

    Implementations manage when and how to extract memories from
    conversation context, delegating to a sub-agent that can read
    and write memory files.
    """

    # -- Public API -----------------------------------------------------

    @abstractmethod
    async def check_and_extract(
        self, context: "Context", hint: Optional[str] = None
    ) -> bool:
        """Check thresholds and extract memories if criteria are met.

        Called automatically at the end of each turn. Returns True if
        extraction was triggered.
        """
        ...

    @abstractmethod
    async def trigger_extraction(
        self, context: "Context", hint: Optional[str] = None
    ) -> bool:
        """Force memory extraction, bypassing threshold checks.

        Called by the ``memory`` tool. Returns True if extraction was
        triggered.
        """
        ...

    @abstractmethod
    def increment_step(self) -> None:
        """Increment the step counter (called for each tool execution step)."""
        ...

    @abstractmethod
    def reset(self) -> None:
        """Reset internal counters and state (called at turn start)."""
        ...
