import os
from pathlib import Path

from broca.commands.base import LocalCommand, CommandContext, CommandResult
from broca.logging_config import get_logger
from broca.skill.skill_store import SkillStore

logger = get_logger(__name__)


class SkillCommand(LocalCommand):
    """Skill 管理命令：list / view / archive / restore"""

    def __init__(self):
        super().__init__()
        self.store = SkillStore()

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        parts = args.strip().split(None, 1)
        subcommand = parts[0].lower() if parts else ""
        rest = parts[1] if len(parts) > 1 else ""

        if not subcommand or subcommand in ("--help", "-h"):
            return self._show_usage()

        handlers = {
            "list": self._handle_list,
            "view": self._handle_view,
            "archive": self._handle_archive,
            "restore": self._handle_restore,
        }

        handler = handlers.get(subcommand)
        if not handler:
            return CommandResult(
                type="error",
                value=f"Unknown subcommand: '{subcommand}'.\n\n{self._show_usage().value}",
            )

        return await handler(rest, ctx)

    def _show_usage(self) -> CommandResult:
        usage = """## /skill — Skill 管理

**子命令**:

  `list [state]`        列出所有 Skill（可过滤: active / archived）
  `view <name>`         查看 Skill 内容和元数据
  `archive <name>`      归档 Skill（仅 agent-created）
  `restore <name>`      恢复已归档的 Skill

**示例**:

  `/skill list`              列出所有
  `/skill list archived`     只显示已归档
  `/skill view my-skill`     查看 my-skill
  `/skill archive my-skill`  归档 my-skill
  `/skill restore my-skill`  恢复 my-skill
"""
        return CommandResult(type="text", value=usage)

    async def _handle_list(self, rest: str, ctx: CommandContext) -> CommandResult:
        filter_state = rest.strip().lower() if rest else None

        # 从 store 获取数据
        store_data = self.store.read()
        skills_info = self.store.list_all_skills()

        # 过滤
        if filter_state:
            skills_info = [s for s in skills_info if s.get("state") == filter_state]

        if not skills_info:
            msg = "No skills found."
            if filter_state:
                msg = f"No skills with state '{filter_state}'."
            return CommandResult(type="text", value=msg)

        # 格式化输出
        lines = ["## Skills\n"]
        lines.append(f"{'Name':<24} {'State':<10} {'Source':<10} {'Uses':<6} {'Path'}")
        lines.append("-" * 80)
        for s in sorted(skills_info, key=lambda x: x["name"]):
            name = s["name"]
            state = s.get("state", "unknown")
            meta = store_data.get(name, {})
            source = meta.get("created_by", "unknown")
            uses = str(meta.get("use_count", 0))
            path = s.get("path", "-")
            lines.append(f"{name:<24} {state:<10} {source:<10} {uses:<6} {path}")

        return CommandResult(type="text", value="\n".join(lines))

    async def _handle_view(self, rest: str, ctx: CommandContext) -> CommandResult:
        if not rest:
            return CommandResult(type="error", value="Usage: `/skill view <name>`")

        name = rest.strip()
        # 查找 Skill 目录
        skills_dir = self.store.skills_dir
        archive_dir = self.store.archive_dir

        skill_path = None
        for base in [skills_dir, archive_dir]:
            candidate = base / name
            if candidate.exists() and candidate.is_dir():
                skill_path = candidate
                break

        if not skill_path:
            return CommandResult(
                type="error", value=f"Skill '{name}' not found."
            )

        # 读取 SKILL.md
        skill_file = skill_path / "SKILL.md"
        if not skill_file.exists():
            return CommandResult(
                type="error",
                value=f"Skill '{name}' exists but has no SKILL.md.",
            )

        content = skill_file.read_text(encoding="utf-8")

        # 获取元数据
        meta = self.store.get(name) or {}
        meta_lines = [
            "## Skill Metadata",
            f"  State: {meta.get('state', 'unknown')}",
            f"  Source: {meta.get('created_by', 'unknown')}",
            f"  Pinned: {meta.get('pinned', False)}",
            f"  Use count: {meta.get('use_count', 0)}",
            f"  View count: {meta.get('view_count', 0)}",
            f"  Created: {meta.get('created_at', '-')}",
            f"  Path: {skill_path}",
            "",
        ]

        # 记录查看
        if name in self.store.read():
            self.store.record_view(name)

        return CommandResult(
            type="text", value="\n".join(meta_lines) + content
        )

    async def _handle_archive(self, rest: str, ctx: CommandContext) -> CommandResult:
        if not rest:
            return CommandResult(type="error", value="Usage: `/skill archive <name>`")

        name = rest.strip()
        ok, msg = self.store.archive_skill(name)
        if ok:
            # 刷新 SkillManager 索引
            self._refresh_skill_index()
            return CommandResult(type="text", value=f"✅ {msg}")
        else:
            return CommandResult(type="error", value=f"❌ {msg}")

    async def _handle_restore(self, rest: str, ctx: CommandContext) -> CommandResult:
        if not rest:
            return CommandResult(type="error", value="Usage: `/skill restore <name>`")

        name = rest.strip()
        ok, msg = self.store.restore_skill(name)
        if ok:
            self._refresh_skill_index()
            return CommandResult(type="text", value=f"✅ {msg}")
        else:
            return CommandResult(type="error", value=f"❌ {msg}")

    def _refresh_skill_index(self):
        """刷新 SkillManager 的索引。"""
        try:
            from broca.skill.skill_manager import SkillManager
            SkillManager().refresh_index()
        except Exception as e:
            logger.warning(f"Failed to refresh skill index: {e}")
