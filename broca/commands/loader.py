"""
Dynamic Command Loader

Supports scanning directories for command.md + __init__.py to dynamically load commands.
Commands are auto-discovered and registered without manual registration.
"""

import importlib.util
import inspect
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import yaml

from broca.commands.base import CommandBase, LocalCommand, PromptCommand
from broca.logging_config import get_logger
from broca.errors import ValidationError

if TYPE_CHECKING:
    from broca.commands.registry import CommandRegistry

logger = get_logger(__name__)


def _parse_command_md(md_path: Path) -> tuple[dict, str]:
    """Parse a command.md file, returning (header_dict, body_text)"""
    with open(md_path, encoding="utf-8") as f:
        content = f.read()

    parts = content.split("---", 2)
    if len(parts) < 3:
        raise ValidationError(f"Invalid command.md format: {md_path}")

    header = yaml.safe_load(parts[1].strip()) or {}
    body = parts[2].strip()
    return header, body


def _import_command_class(py_path: Path) -> type[CommandBase]:
    """Dynamically import the Command subclass from __init__.py"""
    spec = importlib.util.spec_from_file_location(py_path.parent.name, str(py_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Failed to load {py_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for name, obj in inspect.getmembers(module, inspect.isclass):
        if (
            issubclass(obj, CommandBase)
            and obj is not CommandBase
            and obj is not PromptCommand
            and obj is not LocalCommand
            and not inspect.isabstract(obj)
        ):
            return obj

    raise ValidationError(f"No concrete Command subclass found in {py_path}")


def _build_command_from_md(cmd_dir: Path) -> Optional[CommandBase]:
    """
    Build a command instance from a command directory.

    command.md provides metadata, __init__.py provides the implementation class.
    """
    md_path = cmd_dir / "command.md"
    py_path = cmd_dir / "__init__.py"

    if not md_path.exists() or not py_path.exists():
        raise FileNotFoundError(f"Missing command.md or __init__.py in {cmd_dir}")

    # Parse command.md
    header, body = _parse_command_md(md_path)

    # Import the command class
    cmd_class = _import_command_class(py_path)

    # Instantiate
    instance = cmd_class()

    # Override attributes from command.md header
    instance.name = header.get("name", instance.name)
    instance.description = header.get("description", instance.description)
    instance.short_description = header.get(
        "short_description", instance.short_description
    )
    instance.argument_hint = header.get("argument_hint", instance.argument_hint)
    instance.type = header.get("type", instance.type)
    instance.is_hidden = header.get("is_hidden", instance.is_hidden)
    instance.is_enabled = header.get("is_enabled", instance.is_enabled)
    instance.show_result = header.get("show_result", instance.show_result)

    # PromptCommand-specific attributes
    if isinstance(instance, PromptCommand):
        instance.use_sub_agent = header.get("use_sub_agent", instance.use_sub_agent)
        instance.sub_agent_name = header.get("sub_agent_name", instance.sub_agent_name)
        instance.prompt_template = body  # body is the prompt template

    return instance


def load_commands_from_dir(
    registry: "CommandRegistry",
    scan_dir: Path,
    loaded_from: str = "builtin",
) -> None:
    """
    Scan a directory for command folders, dynamically load and register them.

    Each subdirectory must contain command.md and __init__.py.
    Directories starting with '_' are skipped.
    """
    if not scan_dir.exists() or not scan_dir.is_dir():
        return

    for cmd_dir in sorted(scan_dir.iterdir()):
        if not cmd_dir.is_dir():
            continue
        if cmd_dir.name.startswith("_"):
            continue

        try:
            cmd = _build_command_from_md(cmd_dir)
            if cmd is None:
                continue
            cmd.loaded_from = loaded_from
            if not registry.has(cmd.name):
                registry.register(cmd)
                logger.debug(f"Loaded command '{cmd.name}' from {cmd_dir}")
        except Exception as e:
            logger.warning(f"Failed to load command from {cmd_dir}: {e}")
            continue


def load_all_commands(registry: "CommandRegistry", workspace: str) -> None:
    """Load all commands: builtin LocalCommands + builtin PromptCommands + custom commands"""
    # Base directory is the commands package directory
    base_dir = Path(__file__).parent

    # 1. Load builtin LocalCommands
    builtin_dir = base_dir / "builtin"
    load_commands_from_dir(registry, builtin_dir, "builtin")

    # 2. Load builtin PromptCommands
    prompt_dir = base_dir / "prompt"
    load_commands_from_dir(registry, prompt_dir, "builtin")

    # 3. Load workspace custom commands (do not override builtin)
    custom_dir = Path(workspace) / ".broca" / "commands"
    load_commands_from_dir(registry, custom_dir, "custom")
