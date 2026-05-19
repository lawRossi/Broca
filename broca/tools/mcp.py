"""
MCP (Model Context Protocol) 客户端连接管理
=============================================

基于 fastmcp 库连接 MCP 服务器，将远程工具注册为 Broca Tool。

支持两种传输模式：
  - stdio：通过子进程的标准输入/输出通信
  - HTTP (SSE)：通过 HTTP 连接通信

    "mcp_configs": {
        "stock": {
            "command": "python",
            "args": ["stock_mcp_server.py"],
            "env": {"API_KEY": "xxx"},
            "tool_timeout": 15
        },
        "weather": {
            "url": "https://api.example.com/mcp",
            "headers": {"Authorization": "Bearer xxx"},
            "tool_timeout": 30
        }
    }
"""

import asyncio
import re
from contextlib import AsyncExitStack
from typing import Any, Optional

from fastmcp import Client as FastMCPClient
from fastmcp.client.transports import SSETransport, StdioTransport
from mcp import types

from broca.logging_config import get_logger
from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# 工具名称清理
# ---------------------------------------------------------------------------
def _sanitize_name(name: str) -> str:
    """将名称中的非法字符替换为下划线，确保 LLM 友好的工具名称。"""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)


# ---------------------------------------------------------------------------
# MCPTool — 将 MCP 工具包装为 Broca Tool
# ---------------------------------------------------------------------------
class MCPTool(Tool):
    """将单个 MCP 服务器工具包装为 Broca 可调用的 Tool。"""

    def __init__(
        self,
        client: Any,
        server_name: str,
        tool_def: types.Tool,
        tool_timeout: int = 10,
    ):
        """
        初始化 MCPTool。

        Args:
            client: fastmcp.Client 实例
            server_name: MCP 服务器名称
            tool_def: mcp.types.Tool 工具定义
            tool_timeout: 单次工具调用的超时秒数（默认 10）
        """
        super().__init__()
        self._client = client
        self._original_name = tool_def.name
        self._name = (
            f"mcp_{_sanitize_name(server_name)}_{_sanitize_name(tool_def.name)}"
        )
        self._description = tool_def.description or tool_def.name
        self._parameters = tool_def.inputSchema or {"type": "object", "properties": {}}
        self._tool_timeout = tool_timeout

    # -- 元数据属性 -----------------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict:
        return self._parameters

    # -- 执行逻辑 -------------------------------------------------------------

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        """
        调用 MCP 服务器上的远程工具。

        Args:
            arguments: 参数字典
            context: 调用上下文

        Returns:
            ToolResult: 包含执行结果或错误信息
        """
        try:
            content_list = await asyncio.wait_for(
                self._client.call_tool(self._original_name, arguments=arguments),
                timeout=self._tool_timeout,
            )
        except asyncio.TimeoutError:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=(
                    f"Tool '{self._original_name}' timed out after "
                    f"{self._tool_timeout}s"
                ),
            )
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Failed to execute tool '{self._original_name}': {e}",
            )

        # 将 MCP 返回的内容块拼接为纯文本
        parts: list[str] = []
        for block in content_list:
            if isinstance(block, types.TextContent):
                parts.append(block.text)
            else:
                parts.append(str(block))

        content = "".join(parts) if parts else "no output"
        return ToolResult(status=ToolStatus.SUCCESS, content=content)


# ---------------------------------------------------------------------------
# 客户端工厂
# ---------------------------------------------------------------------------
def _build_client(name: str, cfg: dict) -> Optional[Any]:
    """
    根据配置构建 fastmcp Client。

    Args:
        name: 服务器名称（仅用于日志）
        cfg: 服务器配置字典

    Returns:
        fastmcp.Client 实例，或 None（如果配置无效）
    """
    # -- stdio 传输 --
    if cfg.get("command"):
        command = cfg["command"]
        args = cfg.get("args", [])
        env = cfg.get("env")
        cwd = cfg.get("cwd")

        if not isinstance(command, str) or not command.strip():
            logger.warning("mcp server '{}': 'command' is empty or invalid", name)
            return None
        if not isinstance(args, list):
            logger.warning("mcp server '{}': 'args' must be a list", name)
            return None

        logger.debug(
            "mcp server '{}': building stdio transport (command='{}', args={})",
            name,
            command,
            args,
        )
        transport = StdioTransport(
            command=command,
            args=args,
            env=env,
            cwd=cwd,
        )
        return FastMCPClient(transport)

    # -- HTTP 传输 --
    if cfg.get("url"):
        url = cfg["url"]
        headers = cfg.get("headers")

        if not isinstance(url, str) or not url.strip():
            logger.warning("mcp server '{}': 'url' is empty or invalid", name)
            return None

        logger.debug(
            "mcp server '{}': building HTTP transport (url='{}')",
            name,
            url,
        )
        transport = SSETransport(url=url, headers=headers)
        return FastMCPClient(transport)

    # -- 无法识别的配置 --
    return None


# ---------------------------------------------------------------------------
# 连接入口
# ---------------------------------------------------------------------------
async def connect_mcp_servers(mcp_configs: dict, stack: AsyncExitStack) -> list[Tool]:
    """
    连接所有已配置的 MCP 服务器，注册其工具。

    遍历 ``mcp_configs`` 中的每个服务器配置，依次：
    1. 根据配置创建 fastmcp Client（stdio 或 HTTP）
    2. 将 Client 的生命周期托管给 AsyncExitStack
    3. 列出服务器上所有可用工具
    4. 将每个工具包装为 MCPTool 并返回

    Args:
        mcp_configs: 服务器配置字典，格式见模块文档
        stack: AsyncExitStack 实例，用于管理 Client 生命周期

    Returns:
        所有已注册的 MCPTool 列表

    Note:
        某个服务器连接失败不会影响其他服务器，错误会被记录并跳过。
    """
    if not mcp_configs:
        logger.info("No MCP servers configured")
        return []

    if not isinstance(mcp_configs, dict):
        logger.error("mcp_configs must be a dict, got {}", type(mcp_configs).__name__)
        return []

    mcp_tools: list[Tool] = []

    for server_name, cfg in mcp_configs.items():
        label = f"mcp server '{server_name}'"

        if not isinstance(cfg, dict):
            logger.warning("{}: config must be a dict, skipping", label)
            continue

        try:
            # 1. 构建 Client
            client = _build_client(server_name, cfg)
            if client is None:
                logger.warning("{}: no 'command' or 'url' configured, skipping", label)
                continue

            # 2. 将 Client 生命周期纳入 stack 管理
            await stack.enter_async_context(client)

            # 3. 发现工具列表
            tools = await client.list_tools()

            # 4. 包装为 MCPTool
            timeout = cfg.get("tool_timeout", 10)
            if not isinstance(timeout, (int, float)) or timeout <= 0:
                logger.warning(
                    "{}: invalid tool_timeout '{}', falling back to 10s",
                    label,
                    timeout,
                )
                timeout = 10

            for tool_def in tools:
                wrapped = MCPTool(
                    client=client,
                    server_name=server_name,
                    tool_def=tool_def,
                    tool_timeout=timeout,
                )
                mcp_tools.append(wrapped)
                logger.debug(
                    "{}: registered tool '{}' → '{}'",
                    label,
                    tool_def.name,
                    wrapped.name,
                )

            logger.info(
                "{}: connected, {} tool(s) registered",
                label,
                len(tools),
            )

        except Exception as e:
            logger.error(
                "{}: failed to connect: {}",
                label,
                e,
                exc_info=True,
            )

    return mcp_tools
