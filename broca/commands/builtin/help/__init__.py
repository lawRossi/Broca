from broca.commands.base import LocalCommand, CommandContext, CommandResult


class HelpCommand(LocalCommand):
    """Show available commands or detailed information about a specific command"""

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        registry = ctx.agent.command_manager.registry

        if args:
            # Show detailed info for a specific command
            cmd = registry.get(args)
            if not cmd:
                return CommandResult(
                    type="error", value=f"Command '{args}' not found."
                )
            return CommandResult(
                type="text", value=self._format_detail(cmd)
            )
        else:
            # List all available commands
            lines = ["## Available Commands\n"]
            for cmd in registry.get_all():
                if not cmd.is_hidden:
                    hint = f" {cmd.argument_hint}" if cmd.argument_hint else ""
                    lines.append(
                        f"- **/{cmd.name}{hint}**: {cmd.description}"
                    )
            return CommandResult(type="text", value="\n".join(lines))

    def _format_detail(self, cmd) -> str:
        """Format detailed information for a command"""
        lines = [f"## /{cmd.name}\n"]
        lines.append(f"**Description**: {cmd.description}")
        if cmd.argument_hint:
            lines.append(f"**Usage**: `/{cmd.name} {cmd.argument_hint}`")
        else:
            lines.append(f"**Usage**: `/{cmd.name}`")
        lines.append(f"**Type**: {cmd.type}")
        lines.append(f"**Source**: {cmd.loaded_from}")
        return "\n".join(lines)
