"""
MemoryStore — 持久化记忆存储管理器

管理记忆文件的读写、MEMORY.md 索引维护、新鲜度标注和路径安全。
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from .types import (
    INDEX_LINE_RE,
    MemoryEntry,
    MemoryIndexEntry,
    MemoryType,
    build_memory_file,
    days_old,
    freshness_label,
    freshness_warning,
    parse_memory_file,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 默认路径和约束
# ──────────────────────────────────────────────

DEFAULT_MEMORY_DIR = Path(".broca") / "memories"
INDEX_FILENAME = "MEMORY.md"
MAX_INDEX_LINES = 200


# ──────────────────────────────────────────────
# MemoryStore
# ──────────────────────────────────────────────


class MemoryStore:
    """
    持久化记忆存储管理器。

    管理记忆目录下的所有 .md 文件：
    - 每个记忆一个独立文件（如 user_role.md）
    - MEMORY.md 作为索引（始终加载到上下文）
    - 索引含新鲜度标注和老化总览

    使用方式：
        store = MemoryStore()
        entry = MemoryEntry(name="my_mem", description="...", type=MemoryType.USER, content="...")
        index_entry = store.write_memory(entry)
        index = store.read_index()
    """

    def __init__(
        self,
        memory_dir: Path | None = None,
        freshness_warning_days: int = 7,
    ):
        """
        初始化 MemoryStore。

        Args:
            memory_dir: 记忆目录路径，默认 .broca/memories/
            freshness_warning_days: 新鲜度警告阈值（天），默认 7
        """
        self.memory_dir = (memory_dir or DEFAULT_MEMORY_DIR).resolve()
        self.freshness_warning_days = freshness_warning_days

    @property
    def index_path(self) -> Path:
        """MEMORY.md 索引文件路径"""
        return self.memory_dir / INDEX_FILENAME

    # ────────────────────────────────────────
    # 公共方法
    # ────────────────────────────────────────

    def read_index(self) -> list[MemoryIndexEntry]:
        """
        解析 MEMORY.md，返回索引条目列表。

        每行格式: - [Title](file.md) — one-line hook (2025-06-15)

        Returns:
            按更新时间降序排列的索引列表。文件不存在或为空时返回 []。
        """
        if not self.index_path.exists():
            return []

        raw = self._read_file(self.index_path)
        entries: list[MemoryIndexEntry] = []

        for line in raw.split("\n"):
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("<!--") or line.startswith("═"):
                continue
            match = INDEX_LINE_RE.match(line)
            if not match:
                continue
            name = match.group(1)
            filepath = match.group(2)
            description = match.group(3).strip()
            # 解析日期（可选）
            updated = _parse_date_from_str(match.group(4))
            entries.append(MemoryIndexEntry(
                name=name,
                filepath=filepath,
                description=description,
                updated=updated,
            ))

        entries.sort(key=lambda e: e.updated, reverse=True)
        return entries

    def update_index(self, entry: MemoryIndexEntry) -> None:
        """
        添加或更新索引条目。

        先按 name 查找，存在则替换，不存在则追加。
        然后重新构建并写入 MEMORY.md。

        Args:
            entry: 要添加/更新的索引条目
        """
        entries = self.read_index()
        found = False
        for i, e in enumerate(entries):
            if e.name == entry.name:
                entries[i] = entry
                found = True
                break
        if not found:
            entries.append(entry)

        entries.sort(key=lambda e: e.updated, reverse=True)
        self._write_index_file(entries)

    def remove_index(self, name: str) -> bool:
        """
        从索引中移除指定名称的条目。

        Args:
            name: 要移除的记忆名称

        Returns:
            是否找到并移除了条目
        """
        entries = self.read_index()
        new_entries = [e for e in entries if e.name != name]
        if len(new_entries) == len(entries):
            return False
        self._write_index_file(new_entries)
        return True

    def write_memory(self, entry: MemoryEntry) -> MemoryIndexEntry:
        """
        写入一条记忆：创建/更新 .md 文件 + 更新索引。

        Args:
            entry: 要写入的 MemoryEntry

        Returns:
            生成的索引条目
        """
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        # 写入记忆文件
        filepath = self.memory_dir / f"{entry.name}.md"
        content = build_memory_file(entry)
        self._write_file(filepath, content)

        # 更新索引
        index_entry = MemoryIndexEntry(
            name=entry.name,
            filepath=f"{entry.name}.md",
            description=entry.description,
            updated=entry.updated,
        )
        self.update_index(index_entry)
        return index_entry

    def read_memory(self, name: str) -> Optional[MemoryEntry]:
        """
        读取指定名称的记忆文件。

        Args:
            name: 记忆名称（不含 .md 后缀）

        Returns:
            MemoryEntry 实例，文件不存在时返回 None
        """
        filepath = self.memory_dir / f"{name}.md"
        if not filepath.exists():
            return None
        self._validate_path(filepath)
        content = self._read_file(filepath)
        try:
            return parse_memory_file(content)
        except ValueError as e:
            logger.warning(f"解析记忆文件 {filepath} 失败: {e}")
            return None

    def delete_memory(self, name: str) -> bool:
        """
        删除记忆文件并从索引中移除。

        Args:
            name: 要删除的记忆名称

        Returns:
            是否成功删除
        """
        removed = self.remove_index(name)
        filepath = self.memory_dir / f"{name}.md"
        if filepath.exists():
            self._validate_path(filepath)
            filepath.unlink()
            return True
        return removed

    def list_memories(self) -> list[MemoryIndexEntry]:
        """返回按更新时间降序排列的索引列表。"""
        return self.read_index()

    # ────────────────────────────────────────
    # 内部方法
    # ────────────────────────────────────────

    def _validate_path(self, path: Path) -> None:
        """
        校验路径是否在记忆目录内，防止路径穿越。

        Raises:
            PermissionError: 路径不在记忆目录内
        """
        resolved = path.resolve()
        if not str(resolved).startswith(str(self.memory_dir)):
            raise PermissionError(
                f"路径 {resolved} 不在记忆目录 {self.memory_dir} 内"
            )

    def _build_index_text(self, entries: list[MemoryIndexEntry]) -> str:
        """
        构建 MEMORY.md 的完整文本内容。

        每行格式: - [Title](file.md) — description (2025-06-15)
        包含动态新鲜度标注和老化总览。
        超 200 行时截断并添加注释。
        """
        lines: list[str] = []
        for entry in entries:
            date_str = entry.updated.isoformat()
            line = (
                f"- [{entry.name}]({entry.filepath})"
                f" — {entry.description} ({date_str})"
            )
            lines.append(line)

        # 200 行上限截断
        truncated = False
        if len(lines) > MAX_INDEX_LINES:
            lines = lines[:MAX_INDEX_LINES]
            truncated = True

        result: list[str] = []
        result.extend(lines)
        result.append("")

        if truncated:
            result.append(
                f"<!-- TRUNCATED: index exceeds {MAX_INDEX_LINES} lines, "
                f"only showing the {MAX_INDEX_LINES} most recent entries -->"
            )
            result.append("")

        # 老化总览
        warning = freshness_warning(entries, self.freshness_warning_days)
        if warning:
            result.append(warning)
            result.append("")

        return "\n".join(result)

    def _write_index_file(self, entries: list[MemoryIndexEntry]) -> None:
        """将索引条目列表写入 MEMORY.md"""
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        text = self._build_index_text(entries)
        self._write_file(self.index_path, text)

    @staticmethod
    def _read_file(path: Path) -> str:
        """读取文件内容"""
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, IOError) as e:
            logger.warning(f"读取文件 {path} 失败: {e}")
            return ""

    @staticmethod
    def _write_file(path: Path, content: str) -> None:
        """写入文件内容"""
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(content, encoding="utf-8")
        except (OSError, IOError) as e:
            raise RuntimeError(f"写入文件 {path} 失败: {e}")


# ──────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────


def _parse_date_from_str(val: str | None) -> date:
    """解析字符串日期，无效时返回今天"""
    if val:
        try:
            return date.fromisoformat(val)
        except (ValueError, TypeError):
            pass
    return date.today()
