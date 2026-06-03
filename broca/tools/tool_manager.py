import importlib
import inspect
import pkgutil
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Optional

from broca.logging_config import get_logger
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
        "task_management",
        "todo_management",
        "cron",
        "read_blackboard",
        "list_blackboard",
        "write_blackboard",
        "blackboard_changes",
    }

    MODIFY_TOOLS = {"edit_file", "write_file"}

    READ_SEARCH_FILE_CONTENT_TOOLS = {"read_file", "grep"}

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
                        raise ValueError(
                            f"Tool with name '{instance.name}' already exists "
                            f"(defined in {module.__name__}). Tool names must be unique."
                        )
                    self.tools[instance.name] = instance
                except Exception as e:
                    raise ValueError(
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
                    raise ValueError(
                        f"Custom tool '{instance.name}' from {tool_py} conflicts with "
                        f"an already registered tool. Custom tool names must be unique "
                        f"and must not overlap with built-in tools."
                    )
                self.tools[instance.name] = instance
                logger.info(f"Loaded custom tool: {instance.name}")

    def _add_tool(self, tool: Tool):
        """Legacy method kept for backward compatibility (e.g. MCP tools)."""
        if tool.name in self.tools:
            raise ValueError(f"Tool with name '{tool.name}' already exists")
        self.tools[tool.name] = tool

    async def setup_mcp(self, mcp_configs: dict) -> list[str]:
        mcp_tools = await connect_mcp_servers(mcp_configs, self.stack)
        for tool in mcp_tools:
            self._add_tool(tool)
        tool_names = [tool.name for tool in mcp_tools]
        return tool_names

    async def cleanup(self):
        await self.stack.aclose()

    def get_tools(self, tool_names: list[str] | None = None) -> list[Tool]:
        if tool_names is not None:
            tools = []
            for tool_name in tool_names:
                if tool_name not in self.tools:
                    raise ValueError(f"Tool '{tool_name}' not found.")
                tools.append(self.tools[tool_name])
            return tools
        else:
            return list(self.tools.values())
