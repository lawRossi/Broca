import json
from enum import Enum

from loguru import logger


class ToolStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"


class ToolResult:
    def __init__(self, status: ToolStatus, content: str):
        self.status = status
        self.content = content

    def to_dict(self) -> dict:
        return {"status": self.status, "content": self.content}


class ToolCallContext:
    def __init__(self):
        self.agent = None
        self.workspace = None


class Tool:
    @property
    def name(self) -> str:
        return "tool"

    @property
    def description(self) -> str:
        return "This is a tool"

    @property
    def parameters(self) -> dict:
        return {}

    def format(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    async def execute(self, arguments: str, context: ToolCallContext) -> ToolResult:
        try:
            args_dict = json.loads(arguments)
            result = await self._execute(args_dict, context)
            return result
        except json.JSONDecodeError:
            logger.error("Invalid JSON arguments")
            return ToolResult(status=ToolStatus.ERROR, content="Invalid JSON arguments")
        except Exception as e:
            logger.error(f"Error executing tool: {e}")
            return ToolResult(
                status=ToolStatus.ERROR, content=f"Error executing tool: {e}"
            )

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        return ToolResult(
            status=ToolStatus.SUCCESS,
            content=f"Tool {self.name} does not implement _execute method",
        )
