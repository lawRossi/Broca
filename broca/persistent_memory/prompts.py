"""
持久化记忆提取 Prompt 模板

构建子 Agent 的提取指令 prompt，让子 Agent 能正确判断该存什么、怎么存。

主要逻辑：告诉子 Agent 用 load_skill 工具加载持久化记忆提取 Skill，
Skill 中包含详细的记忆类型定义、保存规则、文件管理规范。
"""

from __future__ import annotations

from typing import Optional


def build_extraction_prompt(
    existing_index_content: str,
    hint: Optional[str] = None,
) -> str:
    """
    构建持久化记忆提取子 Agent 的 user prompt。

    Args:
        existing_index_content: 当前 MEMORY.md 的内容（含条目和老化总览）
        hint: 主 Agent 提供的可选提示，引导关注点

    Returns:
        格式化的提取指令文本
    """
    parts: list[str] = []

    # ── 开场白 + 加载 Skill 指令 ──
    parts.append(
        "You are acting as the persistent memory extraction sub-agent. "
        "Analyze the conversation above and update the persistent memory system.\n\n"
        "**First step: use `load_skill` to load the `persistent-memory-extraction` skill if it's not already loaded.**\n"
        "This skill contains all the detailed rules about memory types, what to save, "
        "how to organize files, and how to update the memory index. "
        "Follow the skill's instructions strictly."
    )

    # ── 可用工具提示 ──
    parts.append(
        "## Available Tools\n"
        "- Read-only tools: read_file, glob, grep, list_dir, tree_dir\n"
        "- Write tools: edit_file, write_file (only for paths inside the memory directory)\n"
        "- Skill tools: load_skill (load the `persistent-memory-extraction` skill)\n"
        "- All other tools are DENIED.\n"
        "Efficient strategy: turn 1 — load the skill + read all files you might update in parallel; "
        "turn 2 — write/edit all files in parallel."
    )

    # ── hint ──
    if hint:
        parts.append(
            f"## Priority Instruction\n"
            f"The main agent specifically asks you to focus on: {hint}\n"
        )

    # ── 现有记忆清单 ──
    if existing_index_content.strip():
        parts.append(
            "## Existing Memory Index\n"
            f"{existing_index_content}\n\n"
            "Check this list BEFORE writing — update an existing file rather than "
            "creating a duplicate. If new information fits an existing entry, "
            "update that file instead of creating a new one."
        )
    else:
        parts.append(
            "## Existing Memory Index\n"
            "The memory index is currently empty. You will be creating the first entries."
        )

    return "\n\n".join(parts)
