from contextlib import AsyncExitStack

from broca.skill_manager import SkillManager
from broca.tools.agent_interaction import AskUser, AssignTask
from broca.tools.bash import ExecuteCode
from broca.tools.cron import CronTool
from broca.tools.filesystem import EditFile, ListDir, ReadFile, TreeDir, WriteFile
from broca.tools.memory import MemoryTool
from broca.tools.glob import GlobTool
from broca.tools.grep import GrepTool
from broca.tools.mcp import connect_mcp_servers
from broca.tools.skill import LoadSkill
from broca.tools.task import TaskManagement
from broca.tools.todo import TodoManagement
from broca.tools.tool import Tool
from broca.tools.web import WebFetch, WebSearch


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
    }

    MODIFY_TOOLS = {"edit_file", "write_file"}

    READ_SEARCH_FILE_CONTENT_TOOLS = {"read_file", "grep"}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ToolManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._initialized = True
            self.tools = {}
            self._init_tools()
            self.stack = AsyncExitStack()

    def _init_tools(self):
        self.tools = {}
        self._add_tool(AssignTask())
        self._add_tool(ExecuteCode())
        self._add_tool(ReadFile())
        self._add_tool(WriteFile())
        self._add_tool(EditFile())
        self._add_tool(ListDir())
        self._add_tool(TreeDir())
        self._add_tool(GlobTool())
        self._add_tool(GrepTool())
        self._add_tool(TodoManagement())
        self._add_tool(TaskManagement())
        self._add_tool(MemoryTool())
        self._add_tool(CronTool())
        load_skill = LoadSkill(SkillManager())
        self._add_tool(load_skill)
        self._add_tool(WebFetch())
        self._add_tool(WebSearch())
        self._add_tool(AskUser())

    def _add_tool(self, tool: Tool):
        if tool.name in self.tools:
            raise ValueError(f"Tool with name {tool.name} already exists")
        self.tools[tool.name] = tool

    async def setup_mcp(self, mcp_configs: dict):
        mcp_tools = await connect_mcp_servers(mcp_configs, self.stack)
        for tool in mcp_tools:
            self._add_tool(tool)

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
