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
        self.session_id = None


class Tool:
    def __init__(self, max_content_length: int = 15000):
        self.max_content_length = max_content_length

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

    def _post_process_result(self, result: ToolResult) -> ToolResult:
        if len(result.content) > self.max_content_length:
            content = result.content
            half_length = self.max_content_length // 2
            content = content[:half_length] + "..." + content[-half_length:]
            content += "\n**Notice**: The output is too long and has been truncated in the middle."
            result.content = content

        return result

    async def execute(self, arguments: str, context: ToolCallContext) -> ToolResult:
        try:
            args_dict = json.loads(arguments)
            result = await self._execute(args_dict, context)
            return self._post_process_result(result)
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
