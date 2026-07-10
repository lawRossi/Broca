"""
持久化记忆提取 Prompt 模板

构建子 Agent 的提取指令 prompt，让子 Agent 能正确判断该存什么、怎么存。
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

    # ── 开场白 ──
    parts.append(
        "You are acting as the persistent memory extraction sub-agent. "
        "Analyze the conversation above and update the persistent memory system.\n"
    )

    # ── 可用工具提示 ──
    parts.append(
        "## Available Tools\n"
        "- Read-only tools: read_file, glob, grep, list_dir, tree_dir\n"
        "- Write tools: edit_file, write_file (only for paths inside the memory directory)\n"
        "- All other tools are DENIED.\n"
        "Efficient strategy: turn 1 — read all files you might update in parallel; "
        "turn 2 — write/edit all files in parallel."
    )

    # ── hint ──
    if hint:
        parts.append(
            f"## Priority Instruction\n"
            f"The main agent specifically asks you to focus on: {hint}\n"
            f"Process this instruction first before making any other decisions."
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

    # ── 记忆类型定义 ──
    parts.append(
        "## Memory Types\n\n"
        "There are 4 discrete types of memory. Use them strictly:\n\n"
        "### user\n"
        "- **What to store**: The user's role, goals, responsibilities, knowledge, "
        "working habits, preferences\n"
        "- **When to save**: When you learn any detail about the user's personal "
        "characteristics\n"
        "- **How to use**: To tailor future behavior to the user's preferences\n\n"
        "### feedback\n"
        "- **What to store**: Guidance the user has given about how to approach work "
        "— both what to avoid and what to keep doing\n"
        "- **When to save**: When the user corrects your approach OR confirms a "
        "non-obvious approach worked\n"
        "- **Body structure**: Rule itself, then **Why:** (reason), then "
        "**How to apply:** (when this kicks in)\n\n"
        "### project\n"
        "- **What to store**: Information about ongoing work, goals, initiatives, "
        "bugs, or incidents NOT derivable from code or git history\n"
        "- **When to save**: When you learn who is doing what, why, or by when\n"
        "- **IMPORTANT**: Always convert relative dates to absolute dates "
        "(e.g., 'next Thursday' → '2026-03-12')\n"
        "- **Body structure**: Fact/decision, then **Why:**, then **How to apply:**\n\n"
        "### reference\n"
        "- **What to store**: Pointers to where information lives in external systems\n"
        "- **When to save**: When you learn about external resources and their purpose\n"
        "- **How to use**: When the user references an external system"
    )

    # ── 不该存什么 ──
    parts.append(
        "## What NOT to Save\n\n"
        "These exclusions apply even when the user explicitly asks you to save. "
        "If they ask you to save PR lists or activity summaries, what's worth saving "
        "is what was *surprising* or *non-obvious*:\n\n"
        "- Code patterns, conventions, architecture, file paths, project structure "
        "(derivable from project state)\n"
        "- Git history, recent changes, who-changed-what "
        "(`git log`/`git blame` are authoritative)\n"
        "- Debugging solutions or fix recipes (the fix is in the code)\n"
        "- Anything already documented in project docs\n"
        "- Ephemeral task details: in-progress work, temporary state, "
        "current conversation context\n"
        "- Raw data dumps or verbose output"
    )

    # ── 保存两步法 ──
    parts.append(
        "## How to Save Memories\n\n"
        "Saving a memory is a two-step process:\n\n"
        "**Step 1** — Write the memory to its own .md file using this frontmatter format:\n"
        "```\n"
        "---\n"
        "name: descriptive_name\n"
        "description: One-sentence summary\n"
        "type: user | feedback | project | reference\n"
        "created: YYYY-MM-DD\n"
        "updated: YYYY-MM-DD\n"
        "---\n\n"
        "<memory content here>\n"
        "```\n\n"
        "**Step 2** — Update `MEMORY.md` index:\n"
        "Format: `- [Title](filename.md) — one-line hook (YYYY-MM-DD)`\n"
        "- Each entry: one line, under ~150 characters\n"
        "- Do NOT write memory content directly into MEMORY.md — it's an index only\n"
        "- MEMORY.md is always loaded in context, so keep it concise\n"
        "- The date in the index line is the 'updated' date from the frontmatter\n\n"
        "**Rules:**\n"
        "- Organize by topic, not chronologically\n"
        "- Update or remove outdated memories\n"
        "- Do not write duplicates — check existing first\n"
        "- Keep frontmatter up-to-date with content"
    )

    # ── 约束提醒 ──
    parts.append(
        "## Constraints\n"
        "- You ONLY have data from the recent messages above. \n"
        "- If nothing worth saving was said, do nothing and stop.\n"
        "- Make all edits in parallel where possible, then stop.\n"
        "- Do not continue after the edits."
    )

    return "\n\n".join(parts)
