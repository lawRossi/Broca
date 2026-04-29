"""
Memory Tool Module - 持久化记忆管理工具

提供跨会话持久化的记忆存储，支持两个存储：
- MEMORY.md: agent 的个人笔记（环境事实、项目约定、工具特性、学到的经验）
- USER.md: agent 对用户的了解（偏好、沟通风格、期望、工作习惯）

条目分隔符: § (section sign)，条目可以跨多行。
字符数限制（非 token），因为字符数计数与模型无关。

简化设计：无文件锁、无注入检测、始终反映最新状态。
"""

from pathlib import Path

from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus

# 条目分隔符
ENTRY_DELIMITER = "\n§\n"

# 默认字符数限制
DEFAULT_MEMORY_CHAR_LIMIT = 2200
DEFAULT_USER_CHAR_LIMIT = 1375

# 默认存储路径
DEFAULT_MEMORY_DIR = Path.home() / ".broca" / "memories"


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
                "current_entries": entries,
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

        entries = self._entries_for(target)
        matches = [(i, e) for i, e in enumerate(entries) if old_text in e]

        if not matches:
            return {"success": False, "error": f"未找到包含 '{old_text}' 的条目。"}

        if len(matches) > 1:
            unique_texts = set(e for _, e in matches)
            if len(unique_texts) > 1:
                previews = [
                    e[:80] + ("..." if len(e) > 80 else "") for _, e in matches
                ]
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
                previews = [
                    e[:80] + ("..." if len(e) > 80 else "") for _, e in matches
                ]
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
            "entries": entries,
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
            "持久化记忆管理工具。将重要信息保存到跨会话持久化的记忆中。\n\n"
            "何时保存（主动保存，无需等待用户要求）：\n"
            "- 用户纠正你或说'记住这个'/'别再这样做了'\n"
            "- 用户分享偏好、习惯或个人细节（名字、角色、时区、编程风格）\n"
            "- 你发现关于环境的信息（OS、已安装工具、项目结构）\n"
            "- 你学到了特定于该用户设置的约定、API特点或工作流程\n"
            "- 你识别出在未来会话中会再次有用的稳定事实\n\n"
            "优先级：用户偏好和纠正 > 环境事实 > 流程知识。\n"
            "最有价值的记忆能防止用户重复说明。\n\n"
            "两个存储目标：\n"
            "- 'user'：用户是谁——名字、角色、偏好、沟通风格、习惯\n"
            "- 'memory'：你的笔记——环境事实、项目约定、工具特性、学到的经验\n\n"
            "操作：\n"
            "- add：添加新条目\n"
            "- replace：更新已有条目（通过 old_text 子串匹配定位）\n"
            "- remove：删除条目（通过 old_text 子串匹配定位）\n"
            "- read：读取当前所有条目\n\n"
            "不要保存任务进度、会话结果、已完成的工作日志或临时 TODO 状态到记忆中。"
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "replace", "remove", "read"],
                    "description": "要执行的操作：add（添加）、replace（替换）、remove（删除）、read（读取）",
                },
                "target": {
                    "type": "string",
                    "enum": ["memory", "user"],
                    "description": "目标存储：'memory' 为个人笔记，'user' 为用户档案",
                },
                "content": {
                    "type": "string",
                    "description": "条目内容。add 和 replace 操作必需。",
                },
                "old_text": {
                    "type": "string",
                    "description": "用于定位要替换或删除的条目的短唯一子串。replace 和 remove 操作必需。",
                },
            },
            "required": ["action", "target"],
        }

    async def _execute(self, parameters: dict, context: ToolCallContext) -> ToolResult:
        try:
            action = parameters.get("action")
            target = parameters.get("target", "memory")
            content = parameters.get("content")
            old_text = parameters.get("old_text")

            if target not in ("memory", "user"):
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content=f"无效的 target '{target}'，请使用 'memory' 或 'user'。",
                )

            store = _get_store()

            if action == "add":
                if not content:
                    return ToolResult(
                        status=ToolStatus.ERROR,
                        content="add 操作需要提供 content 参数。",
                    )
                result = store.add(target, content)
            elif action == "replace":
                if not old_text:
                    return ToolResult(
                        status=ToolStatus.ERROR,
                        content="replace 操作需要提供 old_text 参数。",
                    )
                if not content:
                    return ToolResult(
                        status=ToolStatus.ERROR,
                        content="replace 操作需要提供 content 参数。",
                    )
                result = store.replace(target, old_text, content)
            elif action == "remove":
                if not old_text:
                    return ToolResult(
                        status=ToolStatus.ERROR,
                        content="remove 操作需要提供 old_text 参数。",
                    )
                result = store.remove(target, old_text)
            elif action == "read":
                result = store.read(target)
            else:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content=f"未知操作 '{action}'，请使用：add, replace, remove, read。",
                )

            import json

            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=json.dumps(result, ensure_ascii=False, indent=2),
            )

        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"记忆工具执行失败: {str(e)}",
            )
