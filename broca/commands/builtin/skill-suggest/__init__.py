import time
from datetime import datetime, timezone

from broca.commands.base import LocalCommand, CommandContext, CommandResult
from broca.logging_config import get_logger
from broca.tools.skill_evolution import run_skill_sub_agent
from broca.tools.skill_store import SkillStore

logger = get_logger(__name__)

ALLOWED_TOOLS = [
    "load_skill",
    "read_file",
    "glob",
    "grep",
    "list_dir",
    "tree_dir",
    "write_file",
]

SUGGEST_PROMPT_TEMPLATE = """\
Your task is to analyze existing skills and propose improvements.

## Instructions

1. Load and review the following skill(s): {skill_names}
   - Use `load_skill` to read each skill's content

2. Analyze each skill for improvement opportunities:
   - Is the `description` clear and accurate for search matching?
   - Are the steps complete and actionable?
   - Could it be merged with another skill or split into smaller skills?
   - Does this session reveal scenarios the skill should cover but doesn't?

3. Write your improvement suggestions to a file using `write_file`:
   - Path: `plans/skill-suggest-{timestamp}.md`
   - Use the format below

## Output Format

```markdown
# Skill 改进建议: {skill-name}

- **提出时间**: {timestamp}
- **会话**: {session_id}

## 当前问题

{分析当前 Skill 的不足}

## 改进方案

{具体的改进内容}

## 预期效果

{改进后的 Skill 能更好解决什么问题}

## 相关对话摘要

{会话中与改进相关的关键对话点}
```

## Constraints

- **DO NOT** modify any skill files directly
- **DO NOT** call `skill_manage` or `edit_file` on skill directories
- Only use `write_file` to write the suggestion document to the `plans/` directory
- Be constructive and specific in your suggestions
"""


class SkillSuggestCommand(LocalCommand):
    """提出 Skill 改进建议"""

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        skill_name = args.strip() if args.strip() else ""

        if skill_name in ("--help", "-h"):
            return CommandResult(
                type="text",
                value="""## /skill-suggest — 提出 Skill 改进建议

**用法**: `/skill-suggest [skill-name]`

- 不带参数：分析所有 Skill
- 指定名称：只分析该 Skill

子 Agent 会将改进建议输出到 `plans/skill-suggest-*.md`，不会直接修改任何 Skill。""",
            )

        # 确定要分析的 Skill 名称
        store = SkillStore()
        if skill_name:
            # 验证 Skill 是否存在
            meta = store.get(skill_name)
            if meta is None:
                # 检查目录
                skill_dir = store.skills_dir / skill_name
                if not skill_dir.exists():
                    return CommandResult(
                        type="error",
                        value=f"Skill '{skill_name}' not found.",
                    )
            skill_names = skill_name
        else:
            # 分析所有 active 的 Skill
            all_skills = store.list_all_skills()
            active_skills = [s for s in all_skills if s.get("state") == "active"]
            if not active_skills:
                return CommandResult(
                    type="text", value="No active skills found to analyze."
                )
            skill_names = ", ".join(s["name"] for s in active_skills)

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
        session_id = ctx.session_id or "unknown"

        prompt = SUGGEST_PROMPT_TEMPLATE.format(
            skill_names=skill_names,
            timestamp=timestamp,
            session_id=session_id,
        )

        success, msg = await run_skill_sub_agent(
            agent=ctx.agent,
            prompt=prompt,
            allowed_tools=ALLOWED_TOOLS,
        )

        if success:
            return CommandResult(
                type="text",
                value=f"✅ Improvement suggestions for '{skill_names}' written to `plans/skill-suggest-{timestamp}.md`.\n{msg}",
            )
        else:
            return CommandResult(
                type="error",
                value=f"❌ Analysis failed: {msg}",
            )
