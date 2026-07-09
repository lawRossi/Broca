from broca.commands.base import LocalCommand, CommandContext, CommandResult
from broca.logging_config import get_logger
from broca.tools.skill_evolution import run_skill_sub_agent

logger = get_logger(__name__)

ALLOWED_TOOLS = [
    "skill_manage",
    "load_skill",
    "read_file",
    "glob",
    "grep",
    "list_dir",
    "tree_dir",
    "web_fetch",
    "web_search",
    "bash",
    "ask_user",
]

CREATE_PROMPT_TEMPLATE = """\
Your task is to create a new Skill based on the conversation above.

## Instructions

1. Analyze the conversation history above and identify patterns, workflows, or processes that would be valuable to reuse as a Skill.

2. Create a new Skill using the `skill_manage` tool with action="create":
   - name: "{name}" (will be auto-cleaned to slug format)
   - content: Full SKILL.md content following the format below

## SKILL.md Format

The SKILL.md must have YAML frontmatter and a body:

```markdown
---
name: {name}
description: One-sentence description of what this skill does (used for search matching)
---

## When to Use
(Describe when this skill should be invoked)

## Steps
1. ...
2. ...
3. ...

## Notes
- ...
```

## Quality Checklist

- The `description` field must be clear and specific for search matching
- Steps must be concrete and actionable
- Include all necessary context for someone (or another Agent) to execute the skill
- Do NOT create a skill that duplicates existing functionality
- Check existing skills via `load_skill` if needed
- Do NOT reference session-specific details (message IDs, timestamps) in the skill

## Constraints

- Only use the `skill_manage` tool to create the skill
- If name "{name}" already exists, report it and stop
- Create exactly ONE skill per invocation
"""


class SkillCreateCommand(LocalCommand):
    """创建新 Skill"""

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        parts = args.strip().split(None, 1)
        name = parts[0] if parts else ""

        if not name or name in ("--help", "-h"):
            return CommandResult(
                type="text",
                value="""## /skill-create — 创建新 Skill

**用法**: `/skill-create <skill-name> [description]`

**示例**: `/skill-create code-review "Generate code review checklist"`

创建一个新的 Skill，子 Agent 会分析当前会话并自动生成 SKILL.md。""",
            )

        description = parts[1] if len(parts) > 1 else ""
        prompt = CREATE_PROMPT_TEMPLATE.format(name=name, description=description)

        # 通过子 Agent 执行
        success, msg = await run_skill_sub_agent(
            agent=ctx.agent,
            prompt=prompt,
            allowed_tools=ALLOWED_TOOLS,
        )

        if success:
            return CommandResult(
                type="text",
                value=f"✅ Skill '{name}' creation completed.\n{msg}",
            )
        else:
            return CommandResult(
                type="error",
                value=f"❌ Skill creation failed: {msg}",
            )
