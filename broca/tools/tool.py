import asyncio
import json
import uuid
from enum import Enum
from pathlib import Path
from typing import Optional

from broca.errors import BrocaError, ToolError
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

    def validate_arguments(self, args_dict: dict) -> Optional[str]:
        """Validate arguments against the tool's parameter schema.

        Checks:
        - Required parameters are present
        - Parameter types match schema (basic type checking)
        - Enum values are valid

        Returns:
            An error message string if validation fails, or None if valid.
        """
        schema = self.parameters

        properties = schema.get("properties", {})
        required = schema.get("required", [])

        # Check required parameters
        for param in required:
            if param not in args_dict or args_dict[param] is None:
                return f"Missing required parameter: '{param}'"

        # Check parameter types and enum values
        for param, value in args_dict.items():
            if param not in properties:
                continue

            prop_schema = properties[param]

            # Check enum values
            if "enum" in prop_schema and value not in prop_schema["enum"]:
                valid_values = ", ".join(repr(v) for v in prop_schema["enum"])
                return (
                    f"Invalid value for parameter '{param}': {value!r}. "
                    f"Must be one of: {valid_values}"
                )

            # Basic type checking
            expected_type = prop_schema.get("type")
            if expected_type and value is not None:
                if not self._check_type(value, expected_type):
                    return (
                        f"Invalid type for parameter '{param}': expected {expected_type}, "
                        f"got {type(value).__name__} ({value!r})"
                    )

        return None

    @staticmethod
    def _check_type(value, expected_type: str) -> bool:
        """Check if a value matches the expected JSON Schema type."""
        type_map: dict[str, type | tuple[type, ...]] = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        if isinstance(expected_type, str):
            py_type = type_map.get(expected_type)
            if py_type is None:
                return True  # Unknown type, skip check
            return isinstance(value, py_type)
        elif isinstance(expected_type, list):
            for type_ in expected_type:
                py_type = type_map.get(type_)
                if py_type is None:
                    continue  # Unknown type, skip check
                if isinstance(value, py_type):
                    return True

        return False

    async def execute(self, arguments: str, context: ToolCallContext) -> ToolResult:
        try:
            args_dict = json.loads(arguments)
        except json.JSONDecodeError:
            logger.error("Invalid JSON arguments")
            return ToolResult(status=ToolStatus.ERROR, content="Invalid JSON arguments")

        # Unified parameter validation
        validation_error = self.validate_arguments(args_dict)
        if validation_error:
            logger.error(
                f"Argument validation failed for {self.name}: {validation_error}"
            )
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Parameter validation error: {validation_error}",
            )

        try:
            result = await self._execute(args_dict, context)
            return self._post_process_result(result)
        except asyncio.CancelledError:
            raise
        except BrocaError as e:
            logger.error(f"Tool {self.name} error: {e}")
            return ToolResult(
                status=ToolStatus.ERROR, content=e.to_user_message()
            )
        except Exception as e:
            logger.error(f"Error executing tool {self.name}: {e}")
            return ToolResult(
                status=ToolStatus.ERROR, content=f"Error executing tool: {e}"
            )

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        return ToolResult(
            status=ToolStatus.SUCCESS,
            content=f"Tool {self.name} does not implement _execute method",
        )
