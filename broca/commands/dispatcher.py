"""
Command Dispatcher

Provides parsing and dispatching of commands.
- parse_command_input: Parse user input to extract command name and arguments
- dispatch_command: Dispatch a command to the appropriate handler (PromptCommand or LocalCommand)
"""

import asyncio
from typing import Optional

from broca.commands.base import (
    CommandContext,
    CommandResult,
    LocalCommand,
    PromptCommand,
)
from broca.commands.registry import CommandRegistry
from broca.errors import BrocaError
from broca.logging_config import get_logger
from broca.session import MessageProtocol

logger = get_logger(__name__)


def parse_command_input(raw: str) -> Optional[tuple[str, str]]:
    """
    Parse user input to extract command name and arguments.

    Format: /command_name arg1 arg2
    Returns: (name, args) or None if not a command
    """
    text = raw.strip()
    if not text.startswith("/"):
        return None

    text = text[1:]  # Remove leading '/'
    space_idx = text.find(" ")

    if space_idx == -1:
        return text, ""

    return text[:space_idx], text[space_idx + 1 :].strip()


async def dispatch_command(
    name: str,
    args: str,
    registry: CommandRegistry,
    ctx: CommandContext,
) -> Optional[CommandResult]:
    """
    Dispatch a command to its handler.

    For PromptCommand: build prompt and call agent.run (optionally via sub_agent).
    For LocalCommand: call execute method.

    Returns CommandResult or None if command not found.
    """
    cmd = registry.get(name)
    if not cmd:
        return None

    if not cmd.is_enabled:
        return CommandResult(
            type="error", value=f"Command '{name}' is currently disabled."
        )

    try:
        if isinstance(cmd, PromptCommand):
            prompt_text = await cmd.build_prompt(args, ctx)

            # Build message, reusing the original message_id for message chain consistency
            message = MessageProtocol.create_user_message(
                content=prompt_text,
                session_id=ctx.session_id,
                agent_id=ctx.agent_id,
            )
            if ctx.original_message_id:
                message.message_id = ctx.original_message_id
            if ctx.raw_input:
                message.data["raw_input"] = ctx.raw_input

            if cmd.use_sub_agent:
                # Sub Agent execution: async dispatch, non-blocking
                from broca.agent_manager import AgentFactory

                factory = AgentFactory()
                sub_agent = factory.get_agent(ctx.session_id, cmd.sub_agent_name)
                if sub_agent:
                    asyncio.create_task(sub_agent.run(message))
                    return CommandResult(
                        type="text",
                        value=f"Task dispatched to {cmd.sub_agent_name} via /{name}",
                    )
                else:
                    return CommandResult(
                        type="error",
                        value=f"Sub-agent '{cmd.sub_agent_name}' not found",
                    )
            else:
                # Current Agent execution: blocking wait
                result = await ctx.agent.run(message)
                return CommandResult(
                    type="text",
                    value=result.message or f"Command /{name} completed",
                )

        elif isinstance(cmd, LocalCommand):
            return await cmd.execute(args, ctx)

        return None
    except BrocaError as e:
        logger.error(f"Command /{name} failed: {e}")
        return CommandResult(
            type="error",
            value=e.to_user_message(),
        )
