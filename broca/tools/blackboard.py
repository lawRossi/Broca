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
            "Read value(s) from the shared Blackboard. "
            "The Blackboard is a shared state space that all agents in the same Crew can read and write. "
            "Accepts either a single key (string) or multiple keys (array) to batch-read in one call. "
            "Supports dot-separated nested key paths (e.g., 'config.model').\n\n"
            "Examples:\n"
            '  read_blackboard({"key": "topic"})\n'
            '  read_blackboard({"key": ["topic", "discussion_history"]})'
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "oneOf": [
                        {"type": "string", "description": "A single key to read."},
                        {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Multiple keys to read at once. Returns all values in a single response.",
                        },
                    ],
                    "description": "Key or array of keys to read. Supports dot-separated nested paths.",
                },
            },
            "required": ["key"],
        }

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        raw_key = arguments.get("key", "")
        session_id = context.session_id

        blackboard = get_blackboard(session_id)
        if blackboard is None:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="No active Blackboard found for this session. "
                        "Blackboard is only available during Crew orchestration execution.",
            )

        try:
            import json

            # 支持批量读取：单个 key（string）或多个 key（list）
            if isinstance(raw_key, list):
                if not raw_key:
                    return ToolResult(
                        status=ToolStatus.SUCCESS,
                        content="Empty key list provided.",
                    )
                results = []
                missing = []
                for k in raw_key:
                    val = await blackboard.get(k)
                    exists = await blackboard.exists(k) if val is None else True
                    if val is None and not exists:
                        missing.append(k)
                    else:
                        try:
                            formatted = json.dumps(val, ensure_ascii=False, indent=2)
                        except (TypeError, ValueError):
                            formatted = str(val)
                        results.append(f"  [{k}]: {formatted}")

                lines = [f"Batch read {len(raw_key)} key(s):"]
                lines.extend(results)
                if missing:
                    lines.append(f"\nKeys not found: {missing}")

                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    content="\n".join(lines),
                )
            else:
                # 单个 key
                key = str(raw_key)
                value = await blackboard.get(key)
                if value is None:
                    exists = await blackboard.exists(key)
                    if not exists:
                        return ToolResult(
                            status=ToolStatus.SUCCESS,
                            content=f"Key '{key}' does not exist in the Blackboard.",
                        )

                try:
                    content = json.dumps(value, ensure_ascii=False, indent=2)
                except (TypeError, ValueError):
                    content = str(value)

                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    content=f"Blackboard['{key}'] = {content}",
                )

        except Exception as e:
            logger.error(f"Error reading blackboard: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Error reading blackboard: {e}",
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
        return (
            "List all keys currently available in the shared Blackboard, "
            "with their types, version numbers, last update time, and who wrote them. "
            "Use this first to discover available information before reading specific keys."
        )

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
            version = await blackboard.get_version()
            if not keys:
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    content=f"Blackboard is empty (global version={version}).",
                )

            # 获取每个 key 的类型和版本信息
            entries_info = [f"Blackboard (global version={version}):"]
            for key in sorted(keys):
                entry = await blackboard.get_entry(key)
                if entry:
                    val_type = type(entry.value).__name__
                    val_preview = str(entry.value)[:60].replace("\n", " ")
                    ts = entry.updated_at.strftime("%H:%M:%S")
                    entries_info.append(
                        f"  • {key} ({val_type}, v{entry.version}) "
                        f"[by {entry.producer} @ {ts}]: {val_preview}"
                    )
                else:
                    entries_info.append(f"  • {key}")

            return ToolResult(status=ToolStatus.SUCCESS, content="\n".join(entries_info))

        except Exception as e:
            logger.error(f"Error listing blackboard keys: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Error listing blackboard keys: {e}",
            )


class BlackboardChanges(Tool):
    """黑板变更查询工具"""

    @property
    def name(self) -> str:
        return "blackboard_changes"

    @property
    def description(self) -> str:
        return (
            "Get recent changes to the Blackboard since a given version number. "
            "Use this to find out what new information has been added since you last checked. "
            "Returns a list of changed keys, who changed them, and their new values. "
            "If you don't know the version, use list_blackboard first to see the current version."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "since_version": {
                    "type": "integer",
                    "description": "Return changes after this version number. "
                                   "Use list_blackboard to find the current global version, "
                                   "then pass it here on your next call to get only new changes.",
                    "default": 0,
                },
            },
            "required": [],
        }

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        session_id = context.session_id
        since_version = arguments.get("since_version", 0)

        blackboard = get_blackboard(session_id)
        if blackboard is None:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="No active Blackboard found for this session. "
                        "Blackboard is only available during Crew orchestration execution.",
            )

        try:
            current_version = await blackboard.get_version()
            changes = await blackboard.get_changes(since_version=since_version)

            if not changes:
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    content=f"No changes since version {since_version}. "
                            f"Current global version: {current_version}.",
                )

            lines = [f"Changes since version {since_version} (current: {current_version}):"]
            for c in changes:
                val_str = str(c["value"])[:100].replace("\n", " ")
                lines.append(
                    f"  [{c['event_type']}] {c['key']} "
                    f"(by {c['producer']} @ {c['timestamp'][11:19]}): {val_str}"
                )
            lines.append(f"\nTotal: {len(changes)} change(s). "
                         f"Use list_blackboard to see all keys.")

            return ToolResult(status=ToolStatus.SUCCESS, content="\n".join(lines))

        except Exception as e:
            logger.error(f"Error querying blackboard changes: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Error querying blackboard changes: {e}",
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
