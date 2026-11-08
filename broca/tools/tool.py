import asyncio
import json
import os
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Optional

from broca.errors import BrocaError
from broca.logging_config import get_logger

logger = get_logger(__name__)

# ─── Tool result cache cleanup ─────────────────────────────────────
_tool_cache_cleanup_done = False
TOOL_CACHE_MAX_AGE = 3600  # seconds; files older than this are removed at startup


def cleanup_tool_result_cache():
    """Remove tool result cache files older than TOOL_CACHE_MAX_AGE.

    Called lazily on first cache write (guarded by module-level flag,
    runs at most once per process lifetime).
    """
    global _tool_cache_cleanup_done
    if _tool_cache_cleanup_done:
        return
    _tool_cache_cleanup_done = True

    cache_dir = Tool.TOOL_RESULT_CACHE_DIR
    if not cache_dir.exists():
        return

    now = time.time()
    cleaned = 0
    for f in cache_dir.iterdir():
        if not f.is_file():
            continue
        try:
            if now - f.stat().st_mtime > TOOL_CACHE_MAX_AGE:
                f.unlink(missing_ok=True)
                cleaned += 1
        except OSError:
            pass

    if cleaned:
        logger.info(f"Tool result cache cleanup: removed {cleaned} stale file(s)")


class ToolStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"


class ToolResult:
    def __init__(
        self,
        status: ToolStatus,
        content: str,
        extra_context_messages: Optional[list[dict]] = None,
        error_info=None,
    ):
        self.status = status
        self.content = content
        # Each dict: {"llm_message": dict, "data": dict, "role": str}
        # llm_message: LLM API format message to add to context.history
        # data: DB data field content
        # role: message role for DB storage (e.g. "user")
        self.extra_context_messages: list[dict] = (
            extra_context_messages if extra_context_messages is not None else []
        )
        # Structured error info (ErrorInfo) — set when a BrocaError is caught
        self.error_info = error_info

    def to_dict(self) -> dict:
        # extra_context_messages is NOT part of tool result serialization
        d = {"status": self.status, "content": self.content}
        if self.error_info:
            d["error_info"] = self.error_info.to_dict()
        return d


class ToolCallContext:
    def __init__(self):
        self.agent = None
        self.workspace = None
        self.session_id = None
        self.execution_id: Optional[str] = None
        self.namespace: Optional[str] = None
        self.turn_id: Optional[str] = None
        self.agent_id: Optional[str] = None
        # Runtime-only cache: pre_execute_check results from parallel partitioning.
        # Keyed by tool_call_id. Does NOT participate in serialization.
        self.pre_check_cache: Optional[dict] = None


class Tool:
    #: True when the tool never mutates the workspace.
    #:
    #: This is the *source of truth* for the snapshot hook: a step whose tool
    #: calls are all read-only skips snapshot capture entirely. Defaults to
    #: ``False`` (conservative — an unknown tool is treated as a writer), so
    #: read-only tools MUST opt in by setting ``is_readonly = True``.
    #:
    #: Note: forgetting to opt in only costs an extra snapshot; opting in by
    #: mistake would lose undo coverage, so keep the default.
    is_readonly: bool = False

    # Fallback cache dir when workspace is unavailable (relative to CWD).
    # Prefer the absolute path derived from context.workspace.
    TOOL_RESULT_CACHE_DIR = Path(".broca/tool_result_cache")

    def _get_cache_dir(self, workspace: Optional[str] = None) -> Path:
        """Return the absolute cache directory path."""
        if workspace:
            return Path(workspace) / ".broca" / "tool_result_cache"
        return Path(os.getcwd()) / ".broca" / "tool_result_cache"

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

    def _post_process_result(
        self, result: ToolResult, workspace: Optional[str] = None
    ) -> ToolResult:
        if len(result.content) > self.max_content_length:
            content = result.content
            cache_file = None
            if self.name != "read_file":
                cache_dir = self._get_cache_dir(workspace)
                cleanup_tool_result_cache()
                cache_dir.mkdir(parents=True, exist_ok=True)
                cache_file = cache_dir / (uuid.uuid4().hex + ".txt")
                with open(cache_file, "w") as f:
                    f.write(content)
            half_length = self.max_content_length // 2
            content = content[:half_length] + "..." + content[-half_length:]
            content += "\n**Notice**: The output is too long and has been truncated in the middle."
            if cache_file:
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
        if isinstance(value, bool):
            if isinstance(expected_type, str):
                return expected_type == "boolean"
            elif isinstance(expected_type, list):
                return "boolean" in expected_type
            return False
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

        # Guard against non-dict JSON (e.g. "null", "[1,2,3]", '"string"')
        if not isinstance(args_dict, dict):
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Tool arguments must be a JSON object, got {type(args_dict).__name__}",
            )

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
            return self._post_process_result(result, workspace=context.workspace)
        except asyncio.CancelledError:
            raise
        except BrocaError as e:
            logger.error(f"Tool {self.name} error: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                content=e.to_user_message(),
                error_info=e.info,  # 保留结构化错误信息
            )
        except Exception as e:
            logger.error(f"Error executing tool {self.name}: {e}")
            return ToolResult(
                status=ToolStatus.ERROR, content=f"Error executing tool: {e}"
            )

    def pre_execute_check(
        self, arguments: str, context: ToolCallContext
    ) -> Optional[str]:
        """Pre-execution content-aware security check.

        Called by the executor BEFORE tool execution begins.  Override in
        subclasses that need to inspect the arguments and request user
        permission for dangerous operations.

        **Contract**: This method MUST be idempotent and side-effect-free.
        It may be called multiple times for the same arguments (e.g. once
        during parallel partitioning and once during execution).
        Implementations should cache results internally if expensive.

        Returns:
            A permission prompt message if user approval is required before
            execution, or ``None`` if the tool can proceed safely.

        The default implementation returns ``None`` (no check needed).
        """
        return None

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        return ToolResult(
            status=ToolStatus.SUCCESS,
            content=f"Tool {self.name} does not implement _execute method",
        )
