"""
Command Base Types

Defines the base data types for the Broca command system:
- CommandBase: Base class for all commands
- PromptCommand: Command that constructs a prompt and calls agent.run
- LocalCommand: Command that executes local logic
- CommandResult: Result of command execution
- CommandContext: Context passed to command execution
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from broca.agent import Agent
    from broca.context import Context


@dataclass
class CommandBase:
    """Base class for all commands"""

    name: str = ""  # Command name (e.g., "help", "abort")
    description: str = ""  # Description text for help display
    argument_hint: Optional[str] = None  # Argument hint (e.g., "[command_name]")
    type: str = ""  # "prompt" or "local"
    loaded_from: str = "builtin"  # Source: builtin / custom
    is_hidden: bool = False  # Whether to hide from help list
    is_enabled: bool = True  # Whether the command is enabled


@dataclass
class CommandResult:
    """Result of command execution"""

    type: str = "text"  # text / error
    value: str = ""


@dataclass
class CommandContext:
    """Context passed to command execution"""

    workspace: str
    session_id: str
    agent_id: str
    agent: "Agent"
    context: "Context"
    raw_input: Optional[str] = None  # Raw user input, e.g., "/deploy staging"
    original_message_id: Optional[str] = None  # Original input message_id


@dataclass
class PromptCommand(CommandBase):
    """
    Command that constructs a prompt and calls agent.run.

    The prompt_template is the body of the command.md file, supporting {args} placeholders.
    When use_sub_agent is True, the command is dispatched to a sub-agent asynchronously.
    """

    type: str = "prompt"

    use_sub_agent: bool = False  # True = dispatch to sub_agent asynchronously
    sub_agent_name: str = "sub-agent"  # Sub-agent name
    prompt_template: str = ""  # Prompt template with {args} placeholder

    async def build_prompt(self, args: str, ctx: CommandContext) -> str:
        """Render the prompt template with the given arguments"""
        return self.prompt_template.replace("{args}", args)


@dataclass
class LocalCommand(CommandBase):
    """
    Command that executes local logic.

    Subclasses must implement the execute method.
    """

    type: str = "local"

    @abc.abstractmethod
    async def execute(self, args: str, ctx: CommandContext) -> Optional[CommandResult]:
        """Execute the command with the given arguments and context"""
        ...
