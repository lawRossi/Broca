"""Tools API

提供可用工具列表接口，用于前端 Agent 配置编辑时动态获取工具选项。
"""

from broca.tools.tool_manager import ToolManager
from fastapi import APIRouter
from loguru import logger

from app.schemas.schemas import ApiResponse

router = APIRouter()


def _get_builtin_tool_names() -> list[str]:
    """获取所有内置工具名称（不含 MCP 工具，因为 MCP 工具需要连接后才有）"""
    tool_manager = ToolManager()
    tool_names = sorted(tool_manager.tools.keys())
    return tool_names


@router.get("", response_model=ApiResponse)
async def get_available_tools() -> ApiResponse:
    """获取所有可用的内置工具列表"""
    try:
        tool_names = _get_builtin_tool_names()
        return ApiResponse.success(
            {"tools": tool_names},
            msg="Available tools retrieved successfully",
        )
    except Exception as e:
        logger.exception("Error getting available tools")
        return ApiResponse.error(500, f"Failed to get available tools: {e!s}")
