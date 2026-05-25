"""
Broca Command System

A command system based on claude-code architecture, supporting:
- PromptCommand: Construct prompt → call agent.run
- LocalCommand: Execute local logic
- Dynamic loading via directory scanning
- Unified command management
"""

from .base import CommandBase, PromptCommand, LocalCommand, CommandResult, CommandContext
from .registry import CommandRegistry
from .loader import load_all_commands
from .dispatcher import parse_command_input, dispatch_command
from .manager import CommandManager

__all__ = [
    "CommandBase",
    "PromptCommand",
    "LocalCommand",
    "CommandResult",
    "CommandContext",
    "CommandRegistry",
    "load_all_commands",
    "parse_command_input",
    "dispatch_command",
    "CommandManager",
]
