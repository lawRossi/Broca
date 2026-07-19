"""
持久化记忆系统的核心数据结构和解析/序列化函数。

记忆文件格式：每个记忆一个 .md 文件，包含 YAML frontmatter 和主体内容。
索引文件 (MEMORY.md)：每行一条指针，含新鲜度标注。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from broca.errors import ValidationError

# ──────────────────────────────────────────────
# 记忆类型枚举
# ──────────────────────────────────────────────


class MemoryType(str, Enum):
    """记忆类型——严格四类闭集"""

    USER = "user"
    FEEDBACK = "feedback"
    PROJECT = "project"
    REFERENCE = "reference"

    @classmethod
    def values(cls) -> list[str]:
        return [m.value for m in cls]


# ──────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────


@dataclass
class MemoryEntry:
    """单条记忆的完整数据"""

    name: str
    description: str
    type: MemoryType
    content: str
    created: date = field(default_factory=date.today)
    updated: date = field(default_factory=date.today)


@dataclass
class MemoryIndexEntry:
    """记忆索引条目（对应 MEMORY.md 中的一行）"""

    name: str
    filepath: str
    description: str
    updated: date


# ──────────────────────────────────────────────
# Frontmatter 解析/序列化
# ──────────────────────────────────────────────

YAML_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)

# MEMORY.md 索引行匹配: - [Title](file.md) — description (2025-06-15)
# 日期格式 YYYY-MM-DD 在行尾，可选
INDEX_LINE_RE = re.compile(
    r"^\-\s+\[(.+?)\]\((.+?)\)\s*[—–-]+\s*(.+?)(?:\s*\((\d{4}-\d{2}-\d{2})\))?\s*$"
)

# 允许的 frontmatter 字段
ALLOWED_FRONTMATTER_FIELDS = {
    "name": str,
    "description": str,
    "type": str,
    "created": str,  # date string
    "updated": str,  # date string
}


def parse_frontmatter(text: str) -> dict:
    """
    从文本中解析 YAML frontmatter。

    Args:
        text: 包含 frontmatter 的文本（用 --- 包裹）

    Returns:
        解析后的字段字典。无效或缺失的内容返回空 dict。

    Raises:
        ValidationError: YAML 格式无效时抛出
    """
    match = YAML_FRONTMATTER_RE.match(text)
    if not match:
        raise ValidationError("未找到有效的 YAML frontmatter（需要 --- 包裹）")

    raw = match.group(1).strip()
    if not raw:
        raise ValidationError("frontmatter 内容为空")

    result: dict = {}
    for line in raw.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if key in ALLOWED_FRONTMATTER_FIELDS:
            result[key] = val

    # 必填字段校验
    required = ["name", "description", "type"]
    missing = [f for f in required if f not in result]
    if missing:
        raise ValidationError(f"frontmatter 缺少必填字段: {', '.join(missing)}")

    # type 校验
    if result["type"] not in MemoryType.values():
        raise ValidationError(
            f"无效的记忆类型 '{result['type']}'，"
            f"必须为 {', '.join(MemoryType.values())}"
        )

    return result


def build_frontmatter(
    name: str,
    description: str,
    mem_type: MemoryType,
    created: date | None = None,
    updated: date | None = None,
) -> str:
    """
    构建 YAML frontmatter 字符串。

    Args:
        name: 记忆名称（语义化标识）
        description: 一句话摘要
        mem_type: 记忆类型
        created: 创建日期，默认今天
        updated: 更新日期，默认今天

    Returns:
        格式化后的 frontmatter 字符串（含 --- 包裹）
    """
    created = created or date.today()
    updated = updated or date.today()
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"type: {mem_type.value}\n"
        f"created: {created.isoformat()}\n"
        f"updated: {updated.isoformat()}\n"
        "---"
    )


def parse_memory_file(text: str) -> MemoryEntry:
    """
    解析完整的记忆 .md 文件内容为 MemoryEntry。

    Args:
        text: 完整文件内容（frontmatter + 主体）

    Returns:
        MemoryEntry 实例

    Raises:
        ValueError: 解析失败时抛出
    """
    fm = parse_frontmatter(text)

    # 移除 frontmatter 部分，剩余为主体内容
    body = YAML_FRONTMATTER_RE.sub("", text).strip()

    # 解析日期
    created = _parse_date(fm.get("created"))
    updated = _parse_date(fm.get("updated"))

    return MemoryEntry(
        name=fm["name"],
        description=fm["description"],
        type=MemoryType(fm["type"]),
        content=body,
        created=created,
        updated=updated,
    )


def build_memory_file(entry: MemoryEntry) -> str:
    """
    从 MemoryEntry 构建完整的 .md 文件内容。

    Args:
        entry: MemoryEntry 实例

    Returns:
        格式化的完整文件内容
    """
    frontmatter = build_frontmatter(
        name=entry.name,
        description=entry.description,
        mem_type=entry.type,
        created=entry.created,
        updated=entry.updated,
    )
    body = entry.content.strip()
    return f"{frontmatter}\n\n{body}\n"


# ──────────────────────────────────────────────
# 新鲜度辅助函数
# ──────────────────────────────────────────────


def days_old(d: date) -> int:
    """
    计算给定日期距离今天的天数。

    Args:
        d: 要计算的日期

    Returns:
        天数差（今天为 0）
    """
    return (date.today() - d).days


def freshness_label(d: date) -> str:
    """
    生成新鲜度标注文本。

    Args:
        d: 要标注的日期

    Returns:
        标注字符串，如 _(today)_、_(1 day old)_、_(14 days old)_
    """
    days = days_old(d)
    if days <= 0:
        return "_(today)_"
    elif days == 1:
        return "_(1 day old)_"
    else:
        return f"_({days} days old)_"


def freshness_warning(entries: list[MemoryIndexEntry], threshold_days: int) -> str:
    """
    生成老化总览警告。仅在存在超龄记忆时返回非空字符串。

    Args:
        entries: 索引条目列表
        threshold_days: 老化阈值（天）

    Returns:
        老化警告文本，无超龄记忆时返回空字符串
    """
    old_entries = [e for e in entries if days_old(e.updated) > threshold_days]
    if not old_entries:
        return ""

    total = len(entries)
    old_count = len(old_entries)
    lines = [
        "═" * 46,
        f"{old_count}/{total} memory entries are older than {threshold_days} days.",
        "Verify memories against current project state before acting on them —",
        "memories are point-in-time observations, not live state.",
        "═" * 46,
    ]
    return "\n".join(lines)


# ──────────────────────────────────────────────
# 内部辅助
# ──────────────────────────────────────────────


def _parse_date(val: str | None) -> date:
    """解析日期字符串，无效时返回今天"""
    if val:
        try:
            return date.fromisoformat(val)
        except (ValueError, TypeError):
            pass
    return date.today()
