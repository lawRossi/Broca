import json

from loguru import logger


class ToolCallContext:
    def __init__(self):
        self.agent = None


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

    async def execute(self, arguments: str, context: ToolCallContext) -> str:
        try:
            args_dict = json.loads(arguments)
            return await self._execute(args_dict, context)
        except Exception as e:
            logger.error(f"Error executing tool: {e}")
            return f"Error executing tool: {e}"

    async def _execute(self, arguments: dict, context: ToolCallContext) -> str:
        return f"Tool {self.name} does not implement _execute method"
