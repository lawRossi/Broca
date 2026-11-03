"""CommandSystem ABC — interface for command parsing and dispatch.

Manages slash-command parsing, lookup, and dispatch to handlers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional, Tuple


class CommandSystem(ABC):
    """Abstract base class for command management.

    Implementations parse user input for slash-commands, dispatch
    to registered handlers, and manage command lifecycle.
    """

    @abstractmethod
    async def initialize(self, **kwargs: Any) -> None:
        """Initialize the command system.

        Note: The concrete implementation receives the agent via its
        constructor (composition root internal exception).
        """
        ...

    @abstractmethod
    def parse(self, text: str) -> Optional[Tuple[str, str]]:
        """Parse text for a slash-command.

        Returns (command_name, args) or None if not a command.
        """
        ...

    @abstractmethod
    async def dispatch(
        self,
        name: str,
        args: str,
        raw_input: str,
        **kwargs: Any,
    ) -> Optional[Any]:
        """Dispatch a command to its handler. Returns the result or None."""
        ...
