"""Commands API

提供可用的命令列表，用于前端命令补全功能。
"""

from broca.commands.loader import load_all_commands
from broca.commands.registry import CommandRegistry
from fastapi import APIRouter
from loguru import logger

from app.schemas.schemas import ApiResponse

router = APIRouter()


# 缓存命令列表，避免每次请求都重新加载
_commands_cache: list[dict] | None = None


def _load_commands() -> list[dict]:
    """加载所有可用命令"""
    global _commands_cache

    if _commands_cache is not None:
        return _commands_cache

    try:
        registry = CommandRegistry()
        load_all_commands(registry, "/tmp")

        commands = []
        for cmd in registry.get_all():
            if not cmd.is_hidden and cmd.is_enabled:
                commands.append(
                    {
                        "name": cmd.name,
                        "description": cmd.description,
                        "short_description": getattr(cmd, "short_description", ""),
                        "type": cmd.type,
                        "argument_hint": getattr(cmd, "argument_hint", ""),
                        "show_result": getattr(cmd, "show_result", False),
                    }
                )

        # 按名称排序
        commands.sort(key=lambda c: c["name"])
        _commands_cache = commands
        return commands
    except Exception as e:
        logger.error(f"Failed to load commands: {e}")
        return []


@router.get("", response_model=ApiResponse)
async def get_commands() -> ApiResponse:
    """获取所有可用的命令列表"""
    commands = _load_commands()
    return ApiResponse.success(
        {"commands": commands},
        msg="Commands retrieved successfully",
    )


@router.get("/{name}", response_model=ApiResponse)
async def get_command(name: str) -> ApiResponse:
    """获取指定命令的详情"""
    commands = _load_commands()
    for cmd in commands:
        if cmd["name"] == name:
            return ApiResponse.success(cmd, msg="Command found")

    return ApiResponse.error(404, f"Command '{name}' not found")
