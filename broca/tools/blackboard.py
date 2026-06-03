"""
Blackboard 工具模块

为 Agent 提供读写共享黑板的工具，实现 Agent 间解耦共享状态。
- read_blackboard: 读取黑板中的值（支持命名空间）
- write_blackboard: 写入黑板中的值（支持命名空间）
- list_blackboard: 列出当前命名空间下的所有黑板键

命名空间机制：
- 每个 key 与一个命名空间绑定，实际存储为 "{namespace}.{key}"
- Agent 默认使用当前 Crew 的命名空间（由编排器设定），无需感知
- Agent 可通过 namespace 参数读取其他 Crew 的数据
- 黑板按 (session_id, execution_id) 索引，同一 session 的不同执行互不干扰
"""

from typing import Optional, Tuple

from broca.logging_config import get_logger
from broca.orchestration.blackboard import Blackboard
from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus

logger = get_logger(__name__)

# 全局黑板注册表，用于在编排执行期间存储黑板实例
# key: (session_id, execution_id), value: Blackboard 实例
_blackboard_registry: dict = {}


def _registry_key(session_id: str, execution_id: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """构造注册表索引 key"""
    return (session_id, execution_id)


def get_blackboard(session_id: str, execution_id: Optional[str] = None) -> Optional[Blackboard]:
    """获取指定 session+execution 的黑板实例。execution_id 为 None 时返回该 session 的最新黑板。"""
    # 优先精确匹配 (session_id, execution_id)
    if execution_id:
        key = _registry_key(session_id, execution_id)
        bb = _blackboard_registry.get(key)
        if bb:
            return bb
    # fallback: 匹配该 session 下 execution_id 为 None 的黑板
    fallback_key = _registry_key(session_id, None)
    return _blackboard_registry.get(fallback_key)


def set_blackboard(session_id: str, execution_id: Optional[str] = None, blackboard: Blackboard = None) -> None:
    """设置指定 session+execution 的黑板实例"""
    key = _registry_key(session_id, execution_id)
    _blackboard_registry[key] = blackboard


def remove_blackboard(session_id: str, execution_id: Optional[str] = None) -> None:
    """移除指定 session+execution 的黑板实例"""
    key = _registry_key(session_id, execution_id)
    _blackboard_registry.pop(key, None)


def _resolve_namespace(arguments: dict, context: ToolCallContext) -> str:
    """解析命名空间：优先取参数的 namespace，否则取 context.namespace，否则返回空字符串（无前缀）。"""
    return arguments.get("namespace") or context.namespace or ""


def _internal_key(namespace: str, key: str) -> str:
    """构造内部存储 key：有命名空间时加前缀，否则原样返回。"""
    return f"{namespace}.{key}" if namespace else key


def _strip_namespace(namespace: str, internal_key: str) -> str:
    """从内部 key 中剥离命名空间前缀，返回用户可见的 key。"""
    if namespace and internal_key.startswith(f"{namespace}."):
        return internal_key[len(namespace) + 1:]
    return internal_key


# ============================================================================
# ReadBlackboard
# ============================================================================


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
            "By default, reads from your Crew's namespace. "
            "Use the optional 'namespace' parameter to read from another Crew's namespace.\n\n"
            "Examples:\n"
            '  read_blackboard({"key": "topic"})\n'
            '  read_blackboard({"key": ["topic", "discussion_history"]})\n'
            '  read_blackboard({"key": "result", "namespace": "sub_crew.analysis"})'
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Multiple keys to read at once(Supports dot-separated nested paths). Returns all values in a single response.",
                },
                "namespace": {
                    "type": "string",
                    "description": "Optional. Read from a different Crew's namespace. "
                    "If not provided, uses your Crew's default namespace.",
                },
            },
            "required": ["key"],
        }

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        raw_key = arguments.get("key", "")
        namespace = _resolve_namespace(arguments, context)

        session_id = context.session_id
        execution_id = context.execution_id
        blackboard = get_blackboard(session_id, execution_id)
        if blackboard is None:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="No active Blackboard found for this session. "
                "Blackboard is only available during Crew orchestration execution.",
            )

        try:
            import json

            def read_single(k: str):
                internal = _internal_key(namespace, k)
                val = blackboard.get(internal)  # 注意：get 是 async，需要 await
                return val, internal
            # 上面这个 def 不能直接 await，用内联写法

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
                    internal = _internal_key(namespace, k)
                    val = await blackboard.get(internal)
                    exists = await blackboard.exists(internal) if val is None else True
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
                internal = _internal_key(namespace, key)
                value = await blackboard.get(internal)
                if value is None:
                    exists = await blackboard.exists(internal)
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


# ============================================================================
# WriteBlackboard
# ============================================================================


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
            "All agents in the same Crew will be able to read this value.\n\n"
            "By default, writes to your Crew's namespace. "
            "Use the optional 'namespace' parameter to write to another Crew's namespace."
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
                "namespace": {
                    "type": "string",
                    "description": "Optional. Write to a different Crew's namespace. "
                    "If not provided, uses your Crew's default namespace.",
                },
            },
            "required": ["key", "value"],
        }

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        key = arguments.get("key", "")
        value = arguments.get("value")
        namespace = _resolve_namespace(arguments, context)

        session_id = context.session_id
        execution_id = context.execution_id
        blackboard = get_blackboard(session_id, execution_id)
        if blackboard is None:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="No active Blackboard found for this session. "
                "Blackboard is only available during Crew orchestration execution.",
            )

        agent_name = context.agent.name if context.agent else "unknown"
        internal = _internal_key(namespace, key)

        try:
            event = await blackboard.set(internal, value, producer=agent_name)
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


# ============================================================================
# ListBlackboard
# ============================================================================


class ListBlackboard(Tool):
    """列出黑板键工具（按命名空间过滤）"""

    @property
    def name(self) -> str:
        return "list_blackboard"

    @property
    def description(self) -> str:
        return (
            "List all keys in the shared Blackboard that belong to your Crew's namespace, "
            "with their types, version numbers, last update time, and who wrote them. "
            "Use this first to discover available information before reading specific keys.\n\n"
            "By default, shows only keys from your Crew's namespace. "
            "Use the optional 'namespace' parameter to see another Crew's keys."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "Optional. Show keys from a different Crew's namespace. "
                    "If not provided, shows your Crew's namespace.",
                },
            },
            "required": [],
        }

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        namespace = _resolve_namespace(arguments, context)
        session_id = context.session_id
        execution_id = context.execution_id

        blackboard = get_blackboard(session_id, execution_id)
        if blackboard is None:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="No active Blackboard found for this session. "
                "Blackboard is only available during Crew orchestration execution.",
            )

        try:
            all_keys = await blackboard.keys()
            version = await blackboard.get_version()

            # 按命名空间过滤
            prefix = f"{namespace}." if namespace else ""
            filtered = []
            for k in sorted(all_keys):
                if namespace and not k.startswith(prefix):
                    continue
                filtered.append(k)

            if not filtered:
                ns_info = f"namespace '{namespace}'" if namespace else "default namespace"
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    content=f"No keys found in {ns_info} (global version={version}).",
                )

            entries_info = [f"Blackboard namespace '{namespace or '(default)'}' (global version={version}):"]
            for internal_key in filtered:
                entry = await blackboard.get_entry(internal_key)
                if entry:
                    val_type = type(entry.value).__name__
                    ts = entry.updated_at.strftime("%H:%M:%S")
                    # 对用户展示时去掉命名空间前缀
                    display_key = _strip_namespace(namespace, internal_key)
                    entries_info.append(
                        f"  • {display_key} ({val_type}, v{entry.version}) "
                        f"[by {entry.producer} @ {ts}]"
                    )
                else:
                    entries_info.append(f"  • {internal_key}")

            return ToolResult(
                status=ToolStatus.SUCCESS, content="\n".join(entries_info)
            )

        except Exception as e:
            logger.error(f"Error listing blackboard keys: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Error listing blackboard keys: {e}",
            )


# ============================================================================
# BlackboardChanges
# ============================================================================


class BlackboardChanges(Tool):
    """黑板变更查询工具（按命名空间过滤）"""

    @property
    def name(self) -> str:
        return "blackboard_changes"

    @property
    def description(self) -> str:
        return (
            "Get recent changes to the Blackboard since a given version number. "
            "Use this to find out what new information has been added since you last checked. "
            "Returns a list of changed keys (in your Crew's namespace), who changed them, and their new values. "
            "If you don't know the version, use list_blackboard first to see the current version.\n\n"
            "By default, shows only changes from your Crew's namespace. "
            "Use the optional 'namespace' parameter to see another Crew's changes."
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
                "namespace": {
                    "type": "string",
                    "description": "Optional. Show changes from a different Crew's namespace.",
                },
            },
            "required": [],
        }

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        namespace = _resolve_namespace(arguments, context)
        session_id = context.session_id
        execution_id = context.execution_id
        since_version = arguments.get("since_version", 0)

        blackboard = get_blackboard(session_id, execution_id)
        if blackboard is None:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="No active Blackboard found for this session. "
                "Blackboard is only available during Crew orchestration execution.",
            )

        try:
            current_version = await blackboard.get_version()
            all_changes = await blackboard.get_changes(since_version=since_version)

            # 按命名空间过滤
            prefix = f"{namespace}." if namespace else ""
            changes = [c for c in all_changes if not namespace or c["key"].startswith(prefix)]

            if not changes:
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    content=f"No changes since version {since_version} "
                    f"(current: {current_version}).",
                )

            ns_info = f"namespace '{namespace}'" if namespace else "default namespace"
            lines = [
                f"Changes in {ns_info} since version {since_version} "
                f"(current: {current_version}):"
            ]
            for c in changes:
                display_key = _strip_namespace(namespace, c["key"])
                val_str = str(c["value"])[:100].replace("\n", " ")
                lines.append(
                    f"  [{c['event_type']}] {display_key} "
                    f"(by {c['producer']} @ {c['timestamp'][11:19]}): {val_str}"
                )
            lines.append(
                f"\nTotal: {len(changes)} change(s). "
                f"Use list_blackboard to see all keys."
            )

            return ToolResult(status=ToolStatus.SUCCESS, content="\n".join(lines))

        except Exception as e:
            logger.error(f"Error querying blackboard changes: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Error querying blackboard changes: {e}",
            )


# ============================================================================
# DeleteBlackboard
# ============================================================================


class DeleteBlackboard(Tool):
    """删除黑板键工具（按命名空间）"""

    @property
    def name(self) -> str:
        return "delete_blackboard"

    @property
    def description(self) -> str:
        return (
            "Delete a key from the shared Blackboard. "
            "By default, deletes from your Crew's namespace. "
            "Use the optional 'namespace' parameter to delete from another Crew's namespace."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The key to delete",
                },
                "namespace": {
                    "type": "string",
                    "description": "Optional. Delete from a different Crew's namespace.",
                },
            },
            "required": ["key"],
        }

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        key = arguments.get("key", "")
        namespace = _resolve_namespace(arguments, context)
        session_id = context.session_id
        execution_id = context.execution_id

        blackboard = get_blackboard(session_id, execution_id)
        if blackboard is None:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="No active Blackboard found for this session. "
                "Blackboard is only available during Crew orchestration execution.",
            )

        agent_name = context.agent.name if context.agent else "unknown"
        internal = _internal_key(namespace, key)

        try:
            event = await blackboard.delete(internal, producer=agent_name)
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
