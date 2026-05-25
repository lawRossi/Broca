"""
Command Registry

Provides command registration, lookup, and listing functionality.
Commands are registered by name, no aliases supported.
"""

from typing import Optional

from broca.commands.base import CommandBase


class CommandRegistry:
    """Registry for managing commands"""

    def __init__(self):
        self._commands: dict[str, CommandBase] = {}

    def register(self, cmd: CommandBase) -> None:
        """Register a command by its name"""
        self._commands[cmd.name] = cmd

    def unregister(self, name: str) -> None:
        """Remove a command by name"""
        self._commands.pop(name, None)

    def get(self, name: str) -> Optional[CommandBase]:
        """Get a command by name, returns None if not found"""
        return self._commands.get(name)

    def get_all(self) -> list[CommandBase]:
        """Return a deduplicated list of all commands"""
        seen = set()
        result = []
        for cmd in self._commands.values():
            if id(cmd) not in seen:
                seen.add(id(cmd))
                result.append(cmd)
        return result

    def has(self, name: str) -> bool:
        """Check if a command exists by name"""
        return name in self._commands
