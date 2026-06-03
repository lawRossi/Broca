import json
import uuid
from enum import Enum
from pathlib import Path
from typing import Optional

from broca.logging_config import get_logger

logger = get_logger(__name__)


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
        self.execution_id: Optional[str] = None
        self.namespace: Optional[str] = None


class Tool:
    TOOL_RESULT_CACHE_DIR = Path(".broca/tool_result_cache")

    def __init__(self, max_content_length: int = 20000):
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
            if self.name != "read_file":
                self.TOOL_RESULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                cache_file = self.TOOL_RESULT_CACHE_DIR / (uuid.uuid4().hex + ".txt")
                with open(cache_file, "w") as f:
                    f.write(content)
            half_length = self.max_content_length // 2
            content = content[:half_length] + "..." + content[-half_length:]
            content += "\n**Notice**: The output is too long and has been truncated in the middle."
            if self.name != "read_file":
                content += f" The full output is saved to {cache_file}."

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
