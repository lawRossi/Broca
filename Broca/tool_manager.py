from Broca.skill_manager import SkillManager
from Broca.tools import CreateTask, ExecuteCode, LoadSkill, Tool


class ToolManager:
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ToolManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            self.tools = {}
            self._init_tools()

    def _init_tools(self):
        self.tools = {}
        execute_code = ExecuteCode()
        self._add_tool(execute_code)
        load_skill = LoadSkill(SkillManager())
        self._add_tool(load_skill)
        create_task = CreateTask()
        self._add_tool(create_task)

    def _add_tool(self, tool: Tool):
        if tool.name in self.tools:
            raise ValueError(f"Tool with name {tool.name} already exists")
        self.tools[tool.name] = tool

    def get_tools(self, tool_names: list[str]|None=None) -> list[Tool]:
        if tool_names is not None:
            tools = []
            for tool_name in tool_names:
                if tool_name not in self.tools:
                    raise ValueError(f"Tool '{tool_name}' not found.")
                tools.append(self.tools[tool_name])
            return tools
        else:
            return list(self.tools.values())
