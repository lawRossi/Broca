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
from broca.components.command_system import CommandSystem as CommandSystemABC
from broca.logging_config import get_logger

if TYPE_CHECKING:
    from broca.agent import Agent

logger = get_logger(__name__)


class FileCommandSystem(CommandSystemABC):
    """Command manager (default implementation), mounted on Agent"""

    def __init__(self, agent: Optional["Agent"] = None):
        self.agent = agent
        self.registry = CommandRegistry()
        self._initialized = False
        self._communicator = None

    async def initialize(self, agent=None, communicator=None, **kwargs):
        """Initialize the command manager by loading all commands.

        When constructed via ``ComponentRegistry`` (no-arg), the ``agent``
        is passed through *kwargs* here.
        """
        if agent is not None:
            self.agent = agent
        elif "agent" in kwargs and kwargs["agent"] is not None:
            self.agent = kwargs["agent"]
        if communicator is not None:
            self._communicator = communicator
        else:
            self._communicator = getattr(self.agent, "communicator", None)
        if self._initialized:
            return

        load_all_commands(self.registry, self.agent.config.workspace)
        self._initialized = True
        logger.info(
            f"CommandManager initialized with {len(self.registry.get_all())} commands"
        )

    async def send_result(self, name: str, result: CommandResult, subscription: str) -> None:
        """将命令结果发送回前端"""
        if self._communicator is None:
            logger.warning("send_result called but communicator not initialized")
            return
        if result.type == "error":
            await self._communicator.send_error(
                {"message": result.value, "code": "COMMAND_ERROR", "severity": "error"},
                subscription=subscription,
            )
        else:
            cmd = self.registry.get(name)
            if cmd is not None and getattr(cmd, "show_result", False):
                await self._communicator.send_command_result(
                    command=name,
                    result={"code": 0, "message": result.value},
                    subscription=subscription,
                )

    async def send_dispatch_error(self, command: str, subscription: str) -> None:
        """发送未知命令错误"""
        if self._communicator is None:
            logger.warning("send_dispatch_error called but communicator not initialized")
            return
        await self._communicator.send_error(
            {"message": f"未知命令: {command}", "code": "COMMAND_ERROR", "severity": "error"},
            subscription=subscription,
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

# Backward-compatibility alias
CommandManager = FileCommandSystem
