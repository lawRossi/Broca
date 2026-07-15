import importlib
import inspect
import json
import pkgutil
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Optional

from broca.logging_config import get_logger
from broca.errors import ErrorCode, ToolError, ValidationError
from broca.tools.mcp import connect_mcp_servers
from broca.tools.tool import Tool

logger = get_logger(__name__)


class ToolManager:
    _instance = None

    READONLY_TOOLS = {
        "read_file",
        "glob",
        "grep",
        "list_dir",
        "tree_dir",
        "web_fetch",
        "web_search",
        "ask_user",
        "assign_task",
        "task_management",
        "todo_management",
        "cron",
        "process_management",
        "read_blackboard",
        "list_blackboard",
        "blackboard_changes",
    }

    MODIFY_TOOLS = {"edit_file", "write_file"}

    _SKIP_MODULES = {
        "tool_manager",  # self
        "tool",  # base class
        "__init__",
        "mcp",  # loaded separately via setup_mcp()
    }

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ToolManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._initialized = True
            self.tools = {}
            self.stack = AsyncExitStack()
            self._custom_tools_loaded = False
            self._mcp_config: dict = {}
            self._mcp_connected: bool = False
            self._mcp_servers_tools: dict[str, list[Tool]] = {}
            self._scan_builtin_tools()

    def _scan_builtin_tools(self):
        """Auto-discover all Tool subclasses from broca/tools/ modules."""
        import broca.tools as tools_pkg

        self.tools = {}

        for importer, modname, ispkg in pkgutil.walk_packages(
            tools_pkg.__path__, prefix=tools_pkg.__name__ + ".", onerror=lambda x: None
        ):
            # Extract the leaf module name
            leaf_name = modname.rsplit(".", 1)[-1]
            if leaf_name in self._SKIP_MODULES:
                continue

            try:
                module = importlib.import_module(modname)
            except Exception:
                continue

            self._register_tool_classes(module)

    def _register_tool_classes(self, module):
        """Find all Tool subclasses in a module and register them."""
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, Tool)
                and obj is not Tool
                and not inspect.isabstract(obj)
            ):
                try:
                    instance = obj()
                    if instance.name in self.tools:
                        raise ValidationError(
                            f"Tool with name '{instance.name}' already exists "
                            f"(defined in {module.__name__}). Tool names must be unique."
                        )
                    self.tools[instance.name] = instance
                except Exception as e:
                    raise ValidationError(
                        f"Failed to instantiate tool class '{name}' from {module.__name__}: {e}"
                    )

    def load_custom_tools(self, workspace: Optional[str] = None):
        """
        Load custom tools from {workspace}/.broca/tools.py.
        Raises ValueError if any custom tool name conflicts with built-in tools.

        Args:
            workspace: Path to the workspace directory. If None, no custom tools are loaded.
        """
        if not workspace:
            return

        # Idempotent: only load once
        if self._custom_tools_loaded:
            return
        self._custom_tools_loaded = True

        tool_py = Path(workspace) / ".broca" / "tools.py"
        if not tool_py.exists():
            return

        import importlib.util

        spec = importlib.util.spec_from_file_location("custom_tools", str(tool_py))
        if spec is None or spec.loader is None:
            raise ImportError(f"Failed to load custom tool file: {tool_py}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, Tool)
                and obj is not Tool
                and not inspect.isabstract(obj)
            ):
                instance = obj()
                if instance.name in self.tools:
                    raise ValidationError(
                        f"Custom tool '{instance.name}' from {tool_py} conflicts with "
                        f"an already registered tool. Custom tool names must be unique "
                        f"and must not overlap with built-in tools."
                    )
                self.tools[instance.name] = instance
                logger.info(f"Loaded custom tool: {instance.name}")

    def _load_mcp_config(self, workspace: Optional[str] = None):
        """
        Load MCP server configuration from config files (internal).

        Reads configuration in the following order (later overrides earlier):
        1. ``{workspace}/.broca/mcp_config.json`` — workspace-level config (highest priority)
        2. ``~/.broca/configs/mcp_config.json`` — global/user-level config (fallback)

        If workspace config exists, it takes full precedence and global config is ignored.
        """
        if self._mcp_config:
            return  # Already loaded

        config: dict = {}

        # 1. Workspace config ({workspace}/.broca/mcp_config.json) — highest priority
        if workspace:
            workspace_path = Path(workspace) / ".broca" / "mcp_config.json"
            if workspace_path.exists():
                try:
                    with open(workspace_path, encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        config = data
                        logger.info("Loaded MCP config from {}", workspace_path)
                except Exception as e:
                    logger.warning(
                        "Failed to load MCP config from {}: {}", workspace_path, e
                    )

        # 2. Global config (~/.broca/configs/mcp_config.json) — fallback, only if no workspace config
        if not config:
            global_path = Path.home() / ".broca" / "configs" / "mcp_config.json"
            if global_path.exists():
                try:
                    with open(global_path, encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        config = data
                        logger.info("Loaded MCP config from {}", global_path)
                except Exception as e:
                    logger.warning(
                        "Failed to load MCP config from {}: {}", global_path, e
                    )

        self._mcp_config = config
        if not config:
            logger.info("No MCP configuration found (no config files)")

    async def _connect_mcp(self):
        """
        Connect all MCP servers defined in the loaded configuration (internal).

        Idempotent: will only connect once. After connection, tools are
        registered in ``self.tools`` and grouped by server name in
        ``self._mcp_servers_tools``.
        """
        if not self._mcp_config or self._mcp_connected:
            return

        mcp_tools = await connect_mcp_servers(self._mcp_config, self.stack)

        # Group by server_name
        self._mcp_servers_tools = {}
        for tool in mcp_tools:
            server = getattr(tool, "server_name", "unknown")
            if server not in self._mcp_servers_tools:
                self._mcp_servers_tools[server] = []
            self._mcp_servers_tools[server].append(tool)
            self._add_tool(tool)

        self._mcp_connected = True
        total = len(mcp_tools)
        logger.info(
            "MCP connected: {} server(s), {} tool(s) registered",
            len(self._mcp_servers_tools),
            total,
        )

    async def init(self, workspace: Optional[str] = None):
        """
        Initialize the ToolManager with workspace context.

        Performs the following (all idempotent):
        1. Load custom tools from ``{workspace}/.broca/tools.py``
        2. Load MCP configuration from config files
        3. Connect all configured MCP servers

        Args:
            workspace: Path to the workspace directory. If None, only global
                       MCP config is loaded and no custom tools are loaded.
        """
        self.load_custom_tools(workspace)
        self._load_mcp_config(workspace)
        await self._connect_mcp()

    def get_mcp_tools(
        self, server_names: Optional[list[str]] = None
    ) -> list[Tool]:
        """
        Get MCP tool instances, optionally filtered by server names.

        Args:
            server_names: List of server names to include. If None or empty,
                          returns all MCP tools from all connected servers.

        Returns:
            List of Tool instances matching the specified servers.
        """
        if not server_names:
            result = []
            for tools in self._mcp_servers_tools.values():
                result.extend(tools)
            return result

        result = []
        for name in server_names:
            tools = self._mcp_servers_tools.get(name)
            if tools:
                result.extend(tools)
            else:
                logger.warning("MCP server '{}' is not connected", name)
        return result

    def _add_tool(self, tool: Tool):
        """Register a tool instance. Raises ValueError on name conflict."""
        if tool.name in self.tools:
            raise ValidationError(f"Tool with name '{tool.name}' already exists")
        self.tools[tool.name] = tool

    async def cleanup(self):
        await self.stack.aclose()

    def get_tools(self, tool_names: list[str] | None = None) -> list[Tool]:
        if tool_names is not None:
            tools = []
            for tool_name in tool_names:
                if tool_name not in self.tools:
                    raise ValidationError(
                        f"Tool '{tool_name}' not found.",
                        error_code=ErrorCode.VALIDATION_CONFIG_ERROR,
                        details={"available_tools": list(self.tools.keys())},
                    )
                tools.append(self.tools[tool_name])
            return tools
        else:
            return list(self.tools.values())
