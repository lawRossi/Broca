"""Tools API

提供可用工具列表接口，用于前端 Agent 配置编辑时动态获取工具选项。

注意：不依赖 ToolManager 单例，避免跨 workspace 的工具泄漏。
"""

import importlib
import importlib.util
import inspect
import pkgutil
from pathlib import Path

from fastapi import APIRouter, Query
from loguru import logger

from broca.tools.tool import Tool
from app.schemas.schemas import ApiResponse

router = APIRouter()

# 内置工具模块跳过列表（与 ToolManager._SKIP_MODULES 保持一致）
_SKIP_MODULES = {"tool_manager", "tool", "__init__", "mcp"}

# 模块级缓存：内置工具名不会变，只扫描一次
_builtin_tool_names_cache: list[str] | None = None


def _get_builtin_tool_names() -> list[str]:
    """扫描 broca/tools/ 包获取所有内置工具名称（结果缓存）。"""
    global _builtin_tool_names_cache
    if _builtin_tool_names_cache is not None:
        return _builtin_tool_names_cache

    import broca.tools as tools_pkg

    names: set[str] = set()
    for _importer, modname, _ispkg in pkgutil.walk_packages(
        tools_pkg.__path__, prefix=tools_pkg.__name__ + ".", onerror=lambda x: None
    ):
        leaf_name = modname.rsplit(".", 1)[-1]
        if leaf_name in _SKIP_MODULES:
            continue
        try:
            module = importlib.import_module(modname)
        except Exception:
            continue
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, Tool) and obj is not Tool and not inspect.isabstract(obj):
                try:
                    instance = obj()
                    names.add(instance.name)
                except Exception:
                    pass

    _builtin_tool_names_cache = sorted(names)
    logger.info("Cached {} built-in tool names", len(_builtin_tool_names_cache))
    return _builtin_tool_names_cache


def _get_custom_tool_names(workspace: str) -> list[str]:
    """扫描 {workspace}/.broca/tools.py 获取自定义工具名称。"""
    tool_py = Path(workspace) / ".broca" / "tools.py"
    if not tool_py.exists():
        return []

    try:
        spec = importlib.util.spec_from_file_location("_custom_tools_api", str(tool_py))
        if spec is None or spec.loader is None:
            return []
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        names: set[str] = set()
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, Tool) and obj is not Tool and not inspect.isabstract(obj):
                try:
                    instance = obj()
                    names.add(instance.name)
                except Exception:
                    pass
        return sorted(names)
    except Exception as e:
        logger.warning("Failed to scan custom tools from {}: {}", tool_py, e)
        return []


@router.get("", response_model=ApiResponse)
async def get_available_tools(
    workspace: str | None = Query(default=None, description="工作空间路径"),
) -> ApiResponse:
    """获取所有可用的工具列表（内置 + 指定 workspace 的自定义工具）"""
    try:
        tool_names = set(_get_builtin_tool_names())
        if workspace:
            tool_names.update(_get_custom_tool_names(workspace))
        return ApiResponse.success(
            {"tools": sorted(tool_names)},
            msg="Available tools retrieved successfully",
        )
    except Exception as e:
        logger.exception("Error getting available tools")
        return ApiResponse.error(500, f"Failed to get available tools: {e!s}")
