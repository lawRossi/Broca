"""
Blackboard 工具模块

为 Agent 提供读写共享黑板的工具，实现 Agent 间解耦共享状态。
- read_blackboard: 读取黑板中的值
- write_blackboard: 写入黑板中的值
- list_blackboard: 列出所有黑板键
"""

from broca.logging_config import get_logger
from broca.orchestration.blackboard import Blackboard
from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus

logger = get_logger(__name__)

# 全局黑板注册表，用于在编排执行期间存储黑板实例
# key: session_id, value: Blackboard 实例
_blackboard_registry: dict = {}


def get_blackboard(session_id: str) -> Blackboard:
    """获取指定 session 的黑板实例"""
    return _blackboard_registry.get(session_id)


def set_blackboard(session_id: str, blackboard: Blackboard) -> None:
    """设置指定 session 的黑板实例"""
    _blackboard_registry[session_id] = blackboard


def remove_blackboard(session_id: str) -> None:
    """移除指定 session 的黑板实例"""
    _blackboard_registry.pop(session_id, None)


class ReadBlackboard(Tool):
    """读取黑板工具"""

    @property
    def name(self) -> str:
        return "read_blackboard"

    @property
    def description(self) -> str:
        return (
            "Read a value from the shared Blackboard. "
            "The Blackboard is a shared state space that all agents in the same Crew can read and write. "
            "Supports dot-separated nested key paths (e.g., 'user.name')."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The key to read. Supports dot-separated nested paths (e.g., 'config.model')",
                },
            },
            "required": ["key"],
        }

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        key = arguments.get("key", "")
        session_id = context.session_id

        blackboard = get_blackboard(session_id)
        if blackboard is None:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="No active Blackboard found for this session. "
                        "Blackboard is only available during Crew orchestration execution.",
            )

        try:
            value = await blackboard.get(key)
            if value is None:
                # 检查 key 是否真的不存在
                exists = await blackboard.exists(key)
                if not exists:
                    return ToolResult(
                        status=ToolStatus.SUCCESS,
                        content=f"Key '{key}' does not exist in the Blackboard.",
                    )

            import json
            try:
                content = json.dumps(value, ensure_ascii=False, indent=2)
            except (TypeError, ValueError):
                content = str(value)

            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"Blackboard['{key}'] = {content}",
            )
        except Exception as e:
            logger.error(f"Error reading blackboard key '{key}': {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Error reading blackboard key '{key}': {e}",
            )


class WriteBlackboard(Tool):
    """写入黑板工具"""

    @property
    def name(self) -> str:
        return "write_blackboard"

    @property
    def description(self) -> str:
        return (
            "Write a value to the shared Blackboard. "
            "The Blackboard is a shared state space that all agents in the same Crew can read and write. "
            "Values can be strings, numbers, lists, or objects (dictionaries). "
            "All agents in the same Crew will be able to read this value."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The key to write to",
                },
                "value": {
                    "type": ["string", "number", "boolean", "object", "array"],
                    "description": "The value to store. Can be a string, number, boolean, list, or object.",
                },
            },
            "required": ["key", "value"],
        }

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        key = arguments.get("key", "")
        value = arguments.get("value")
        session_id = context.session_id

        blackboard = get_blackboard(session_id)
        if blackboard is None:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="No active Blackboard found for this session. "
                        "Blackboard is only available during Crew orchestration execution.",
            )

        agent_name = context.agent.name if context.agent else "unknown"

        try:
            event = await blackboard.set(key, value, producer=agent_name)
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"Successfully wrote to Blackboard['{key}']. "
                        f"New version: {event.key}@{event.timestamp.isoformat()}",
            )
        except Exception as e:
            logger.error(f"Error writing blackboard key '{key}': {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Error writing blackboard key '{key}': {e}",
            )


class ListBlackboard(Tool):
    """列出黑板所有键工具"""

    @property
    def name(self) -> str:
        return "list_blackboard"

    @property
    def description(self) -> str:
        return "List all keys currently available in the shared Blackboard."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        session_id = context.session_id

        blackboard = get_blackboard(session_id)
        if blackboard is None:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="No active Blackboard found for this session. "
                        "Blackboard is only available during Crew orchestration execution.",
            )

        try:
            keys = await blackboard.keys()
            if not keys:
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    content="Blackboard is empty (no keys).",
                )

            # 获取每个 key 的类型和版本信息
            entries_info = []
            for key in keys:
                entry = await blackboard.get_entry(key)
                if entry:
                    val_type = type(entry.value).__name__
                    entries_info.append(f"  • {key} ({val_type}, v{entry.version})")
                else:
                    entries_info.append(f"  • {key}")

            content = "Blackboard keys:\n" + "\n".join(entries_info)
            return ToolResult(status=ToolStatus.SUCCESS, content=content)

        except Exception as e:
            logger.error(f"Error listing blackboard keys: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Error listing blackboard keys: {e}",
            )


class DeleteBlackboard(Tool):
    """删除黑板键工具"""

    @property
    def name(self) -> str:
        return "delete_blackboard"

    @property
    def description(self) -> str:
        return "Delete a key from the shared Blackboard."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The key to delete",
                },
            },
            "required": ["key"],
        }

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        key = arguments.get("key", "")
        session_id = context.session_id

        blackboard = get_blackboard(session_id)
        if blackboard is None:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="No active Blackboard found for this session. "
                        "Blackboard is only available during Crew orchestration execution.",
            )

        agent_name = context.agent.name if context.agent else "unknown"

        try:
            event = await blackboard.delete(key, producer=agent_name)
            if event is None:
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    content=f"Key '{key}' did not exist in the Blackboard (nothing to delete).",
                )
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"Successfully deleted Blackboard['{key}'].",
            )
        except Exception as e:
            logger.error(f"Error deleting blackboard key '{key}': {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Error deleting blackboard key '{key}': {e}",
            )
