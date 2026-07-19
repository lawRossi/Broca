from broca.commands.base import LocalCommand, CommandContext, CommandResult


class AbortCommand(LocalCommand):
    """Abort the current agent execution"""

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        await ctx.agent.abort()
        return CommandResult(value="Execution aborted")
