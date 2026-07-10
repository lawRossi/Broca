from jinja2 import Template

from broca.commands.base import CommandContext, CommandResult, LocalCommand
from broca.logging_config import get_logger
from broca.skill.skill_evolution import run_skill_sub_agent

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

CREATE_PROMPT_TEMPLATE = Template("""\
user input: {{ user_input }}

## Instructions
Your task is to create a new Skill based on the conversation above and the user‘s input.

1. Analyze the conversation history and identify patterns, workflows, or processes that would be valuable to reuse as a Skill.
2. If user does not specify a name, come up with a concise, descriptive name for the Skill (use 2-4 words, kebab-case).
3. Create the Skill using the `skill_manage` tool with action="create".
   - name: Skill name (will be auto-cleaned to slug format)
   - content: Full SKILL.md content following the format below

## SKILL.md Format

The SKILL.md must have YAML frontmatter and a body:

```markdown
---
name: Skill Name
description: One-sentence description of what this skill does and when to invoke (keep it concise)
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
- Check existing skills via `skill_manage` with action="list"
- Do NOT reference session-specific details (message IDs, timestamps) in the skill

## Constraints

- You must use the `skill_manage` tool to create the skill
""")


class SkillCreateCommand(LocalCommand):
    """创建新 Skill"""

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:

        prompt = CREATE_PROMPT_TEMPLATE.render(user_input=args)

        success, msg = await run_skill_sub_agent(
            agent=ctx.agent,
            prompt=prompt,
            allowed_tools=ALLOWED_TOOLS,
        )

        if success:
            return CommandResult(
                type="text",
                value="✅ Skill creation completed.",
            )
        else:
            return CommandResult(
                type="error",
                value=f"❌ Skill creation failed: {msg}",
            )
