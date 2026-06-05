"""
Memory Tool Module - 持久化记忆管理工具

提供跨会话持久化的记忆存储，支持两个存储：
- MEMORY.md: agent 的个人笔记（环境事实、项目约定、工具特性、学到的经验）
- USER.md: agent 对用户的了解（偏好、沟通风格、期望、工作习惯）

条目分隔符: § (section sign)，条目可以跨多行。
字符数限制（非 token），因为字符数计数与模型无关。
"""

import json
from pathlib import Path

from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus
from broca.utils import scan_content_security

# 条目分隔符
ENTRY_DELIMITER = "\n§\n"

# 默认字符数限制
DEFAULT_MEMORY_CHAR_LIMIT = 2200
DEFAULT_USER_CHAR_LIMIT = 1375

# 默认存储路径
DEFAULT_MEMORY_DIR = Path(".broca") / "memories"


class MemoryStore:
    """
    持久化记忆存储，管理 MEMORY.md 和 USER.md 文件。
    维护两个记忆列表，支持添加、替换、删除和读取操作。
    """

    def __init__(
        self,
        memory_dir: Path = None,
        memory_char_limit: int = DEFAULT_MEMORY_CHAR_LIMIT,
        user_char_limit: int = DEFAULT_USER_CHAR_LIMIT,
    ):
        self.memory_dir = memory_dir or DEFAULT_MEMORY_DIR
        self.memory_char_limit = memory_char_limit
        self.user_char_limit = user_char_limit
        self.memory_entries: list[str] = []
        self.user_entries: list[str] = []

    def load(self):
        """从磁盘加载条目"""
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.memory_entries = self._read_file(self.memory_dir / "MEMORY.md")
        self.user_entries = self._read_file(self.memory_dir / "USER.md")
        # 去重（保留顺序，保留首次出现）
        self.memory_entries = list(dict.fromkeys(self.memory_entries))
        self.user_entries = list(dict.fromkeys(self.user_entries))

    def _entries_for(self, target: str) -> list[str]:
        if target == "user":
            return self.user_entries
        return self.memory_entries

    def _path_for(self, target: str) -> Path:
        if target == "user":
            return self.memory_dir / "USER.md"
        return self.memory_dir / "MEMORY.md"

    def _char_limit(self, target: str) -> int:
        if target == "user":
            return self.user_char_limit
        return self.memory_char_limit

    def _char_count(self, target: str) -> int:
        entries = self._entries_for(target)
        if not entries:
            return 0
        return len(ENTRY_DELIMITER.join(entries))

    def add(self, target: str, content: str) -> dict:
        """添加新条目"""
        content = content.strip()
        if not content:
            return {"success": False, "error": "内容不能为空。"}

        # 安全扫描
        scan_error = scan_content_security(content)
        if scan_error:
            return {"success": False, "error": scan_error}

        entries = self._entries_for(target)
        limit = self._char_limit(target)

        # 拒绝完全重复的条目
        if content in entries:
            return self._success_response(target, "条目已存在（未添加重复项）。")

        # 计算添加后的总字符数
        new_entries = entries + [content]
        new_total = len(ENTRY_DELIMITER.join(new_entries))
        if new_total > limit:
            current = self._char_count(target)
            return {
                "success": False,
                "error": (
                    f"记忆已达 {current:,}/{limit:,} 字符。"
                    f"添加此条目 ({len(content)} 字符) 将超出限制。"
                    f"请先替换或删除已有条目。"
                ),
                "usage": f"{current:,}/{limit:,}",
            }

        entries.append(content)
        self._save(target)
        return self._success_response(target, "条目已添加。")

    def replace(self, target: str, old_text: str, new_content: str) -> dict:
        """查找包含 old_text 子串的条目，替换为 new_content"""
        old_text = old_text.strip()
        new_content = new_content.strip()

        if not old_text:
            return {"success": False, "error": "old_text 不能为空。"}
        if not new_content:
            return {
                "success": False,
                "error": "new_content 不能为空。如需删除请使用 remove 操作。",
            }

        # 安全扫描替换内容
        scan_error = scan_content_security(new_content)
        if scan_error:
            return {"success": False, "error": scan_error}

        entries = self._entries_for(target)
        matches = [(i, e) for i, e in enumerate(entries) if old_text in e]

        if not matches:
            return {"success": False, "error": f"未找到包含 '{old_text}' 的条目。"}

        if len(matches) > 1:
            unique_texts = set(e for _, e in matches)
            if len(unique_texts) > 1:
                previews = [e[:80] + ("..." if len(e) > 80 else "") for _, e in matches]
                return {
                    "success": False,
                    "error": f"多个条目匹配 '{old_text}'，请提供更精确的匹配文本。",
                    "matches": previews,
                }

        idx = matches[0][0]
        limit = self._char_limit(target)

        test_entries = entries.copy()
        test_entries[idx] = new_content
        new_total = len(ENTRY_DELIMITER.join(test_entries))
        if new_total > limit:
            return {
                "success": False,
                "error": (
                    f"替换后记忆将达 {new_total:,}/{limit:,} 字符。"
                    f"请缩短新内容或先删除其他条目。"
                ),
            }

        entries[idx] = new_content
        self._save(target)
        return self._success_response(target, "条目已替换。")

    def remove(self, target: str, old_text: str) -> dict:
        """删除包含 old_text 子串的条目"""
        old_text = old_text.strip()
        if not old_text:
            return {"success": False, "error": "old_text 不能为空。"}

        entries = self._entries_for(target)
        matches = [(i, e) for i, e in enumerate(entries) if old_text in e]

        if not matches:
            return {"success": False, "error": f"未找到包含 '{old_text}' 的条目。"}

        if len(matches) > 1:
            unique_texts = set(e for _, e in matches)
            if len(unique_texts) > 1:
                previews = [e[:80] + ("..." if len(e) > 80 else "") for _, e in matches]
                return {
                    "success": False,
                    "error": f"多个条目匹配 '{old_text}'，请提供更精确的匹配文本。",
                    "matches": previews,
                }

        idx = matches[0][0]
        entries.pop(idx)
        self._save(target)
        return self._success_response(target, "条目已删除。")

    def read(self, target: str) -> dict:
        """读取并返回条目列表"""
        return self._success_response(target)

    # -- 内部辅助方法 --

    def _success_response(self, target: str, message: str = None) -> dict:
        entries = self._entries_for(target)
        current = self._char_count(target)
        limit = self._char_limit(target)
        pct = min(100, int((current / limit) * 100)) if limit > 0 else 0
        resp = {
            "success": True,
            "target": target,
            "usage": f"{pct}% — {current:,}/{limit:,} chars",
            "entry_count": len(entries),
        }
        if message:
            resp["message"] = message
        return resp

    def _save(self, target: str):
        """将条目持久化到磁盘"""
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self._write_file(self._path_for(target), self._entries_for(target))

    @staticmethod
    def _read_file(path: Path) -> list[str]:
        """读取记忆文件并拆分为条目列表"""
        if not path.exists():
            return []
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, IOError):
            return []
        if not raw.strip():
            return []
        entries = [e.strip() for e in raw.split(ENTRY_DELIMITER)]
        return [e for e in entries if e]

    @staticmethod
    def _write_file(path: Path, entries: list[str]):
        """将条目列表写入记忆文件"""
        content = ENTRY_DELIMITER.join(entries) if entries else ""
        try:
            path.write_text(content, encoding="utf-8")
        except (OSError, IOError) as e:
            raise RuntimeError(f"写入记忆文件 {path} 失败: {e}")


# 全局单例 store
_store: MemoryStore = None


def _get_store() -> MemoryStore:
    """获取全局 MemoryStore 单例"""
    global _store
    if _store is None:
        _store = MemoryStore()
        _store.load()
    return _store


class MemoryTool(Tool):
    """持久化记忆管理工具"""

    def __init__(self):
        super().__init__(max_content_length=30000)

    @property
    def name(self) -> str:
        return "memory"

    @property
    def description(self) -> str:
        return (
            "Save durable information to persistent memory that survives across sessions. "
            "Memory is injected into future turns, so keep it compact and focused on facts "
            "that will still matter later.\n\n"
            "WHEN TO SAVE:\n"
            "- User corrects you or says 'remember this' / 'don't do that again'\n"
            "- User shares a preference, habit, or personal detail (name, role, timezone, coding style)\n"
            "- You discover something about the environment (OS, installed tools, project structure)\n"
            "- You learn a convention, API quirk, or workflow specific to this user's setup\n"
            "- You identify a stable fact that will be useful again in future sessions\n\n"
            "PRIORITY: User preferences and corrections > environment facts > procedural knowledge. "
            "The most valuable memory prevents the user from having to repeat themselves.\n\n"
            "SKIP: trivial/obvious info, things easily re-discovered, raw data dumps, and temporary task state."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "replace", "remove"],
                    "description": "the action to perform",
                },
                "target": {
                    "type": "string",
                    "enum": ["memory", "user"],
                    "description": "memory for personal notes, user for user profile",
                },
                "content": {
                    "type": "string",
                    "description": "the content to add or remove",
                },
                "old_text": {
                    "type": "string",
                    "description": "the text to find and replace, required for replace action",
                },
            },
            "required": ["action", "target", "content"],
        }

    async def _execute(self, parameters: dict, context: ToolCallContext) -> ToolResult:
        try:
            action = parameters.get("action")
            target = parameters.get("target", "memory")
            content = parameters.get("content")
            old_text = parameters.get("old_text")

            store = _get_store()

            if action == "add":
                if not content:
                    return ToolResult(
                        status=ToolStatus.ERROR,
                        content="content is required for 'add' action.",
                    )
                result = store.add(target, content)
            elif action == "replace":
                if not old_text:
                    return ToolResult(
                        status=ToolStatus.ERROR,
                        content="old_text is required for 'replace' action.",
                    )
                if not content:
                    return ToolResult(
                        status=ToolStatus.ERROR,
                        content="content is required for 'replace' action.",
                    )
                result = store.replace(target, old_text, content)
            elif action == "remove":
                if not content:
                    return ToolResult(
                        status=ToolStatus.ERROR,
                        content="content is required for 'remove' action.",
                    )
                result = store.remove(target, content)

            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=json.dumps(result, ensure_ascii=False, indent=2),
            )

        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"记忆工具执行失败: {str(e)}",
            )
