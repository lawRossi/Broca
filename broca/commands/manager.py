"""
Command Manager

Integrates the registry, loader, and dispatcher.
Mounted on the Agent to provide command management functionality.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from broca.commands.base import CommandContext, CommandResult
from broca.commands.dispatcher import dispatch_command, parse_command_input
from broca.commands.loader import load_all_commands
from broca.commands.registry import CommandRegistry
from broca.logging_config import get_logger

if TYPE_CHECKING:
    from broca.agent import Agent

logger = get_logger(__name__)


class CommandManager:
    """Command manager, mounted on Agent"""

    def __init__(self, agent: "Agent"):
        self.agent = agent
        self.registry = CommandRegistry()
        self._initialized = False

    async def initialize(self):
        """Initialize the command manager by loading all commands"""
        if self._initialized:
            return

        load_all_commands(self.registry, self.agent.config.workspace)
        self._initialized = True
        logger.info(
            f"CommandManager initialized with {len(self.registry.get_all())} commands"
        )

    def parse(self, text: str) -> Optional[tuple[str, str]]:
        """Parse user input to extract command name and arguments"""
        return parse_command_input(text)

    async def dispatch(
        self,
        name: str,
        args: str,
        raw_input: Optional[str] = None,
        original_message_id: Optional[str] = None,
    ) -> Optional[CommandResult]:
        """Dispatch a command to its handler"""
        ctx = CommandContext(
            workspace=self.agent.config.workspace,
            session_id=self.agent.session_id,
            agent_id=self.agent.agent_id,
            agent=self.agent,
            context=self.agent.context,
            raw_input=raw_input,
            original_message_id=original_message_id,
        )
        return await dispatch_command(name, args, self.registry, ctx)
