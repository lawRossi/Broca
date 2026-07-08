"""
Persistent Memory 包

提供基于独立 .md 文件 + YAML frontmatter 的持久化记忆管理。
每条记忆一个文件，MEMORY.md 做索引，支持新鲜度标注和自动提取。
"""

from .types import (
    MemoryType,
    MemoryEntry,
    MemoryIndexEntry,
    INDEX_LINE_RE,
    parse_frontmatter,
    build_frontmatter,
    parse_memory_file,
    build_memory_file,
    days_old,
    freshness_label,
    freshness_warning,
)
from .store import MemoryStore
from .state import PersistentMemoryState
from .manager import PersistentMemoryManager
from .prompts import build_extraction_prompt

__all__ = [
    "MemoryType",
    "MemoryEntry",
    "MemoryIndexEntry",
    "INDEX_LINE_RE",
    "MemoryStore",
    "PersistentMemoryState",
    "PersistentMemoryManager",
    "build_extraction_prompt",
    "parse_frontmatter",
    "build_frontmatter",
    "parse_memory_file",
    "build_memory_file",
    "days_old",
    "freshness_label",
    "freshness_warning",
]
