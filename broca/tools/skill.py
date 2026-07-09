from broca.tools.skill_store import SkillStore, clean_skill_name
from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus


class LoadSkill(Tool):
    def __init__(self):
        super().__init__(max_content_length=45000)
        from broca.skill_manager import SkillManager

        self.skill_manager = SkillManager()

    @property
    def name(self) -> str:
        return "load_skill"

    @property
    def description(self) -> str:
        return "Use this tool to load a skill."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "the name of the skill to load",
                }
            },
            "required": ["skill_name"],
        }

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        skill_name = arguments["skill_name"]
        try:
            result = self.skill_manager.load_skill_spec(skill_name, context.workspace)
            return ToolResult(status=ToolStatus.SUCCESS, content=result)
        except ValueError:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"Skill '{skill_name}' not found"
            )
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"Error loading skill: {e}"
            )


class SkillManage(Tool):
    """Agent 可调用的 Skill 管理工具：create / patch / delete / write_file / remove_file"""

    def __init__(self):
        super().__init__(max_content_length=20000)
        self.store = SkillStore()

    @property
    def name(self) -> str:
        return "skill_manage"

    @property
    def description(self) -> str:
        return (
            "Manage skills: create a new skill, patch an existing one, "
            "delete (archive) a skill, list all skills, "
            "or manage files under its references/templates/scripts directory. "
            "Use this when the user asks you to create, modify, or list skills."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "The operation to perform",
                    "enum": ["create", "patch", "delete", "list", "write_file", "remove_file"],
                },
                "name": {
                    "type": "string",
                    "description": "Skill name (will be auto-cleaned to slug format for 'create'). Not required for 'list'.",
                },
                "content": {
                    "type": "string",
                    "description": "Full SKILL.md content (required for create/patch)",
                },
                "file_path": {
                    "type": "string",
                    "description": "Relative path under references/templates/scripts (for write_file/remove_file)",
                },
                "file_content": {
                    "type": "string",
                    "description": "File content (for write_file)",
                },
                "absorbed_into": {
                    "type": "string",
                    "description": "When deleting, declare which umbrella skill this is being merged into",
                },
            },
            "required": ["action"],
        }

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        action = arguments["action"]

        handlers = {
            "create": self._handle_create,
            "patch": self._handle_patch,
            "delete": self._handle_delete,
            "list": self._handle_list,
            "write_file": self._handle_write_file,
            "remove_file": self._handle_remove_file,
        }

        handler = handlers.get(action)
        if not handler:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Unknown action: '{action}'. Valid: create, patch, delete, list, write_file, remove_file",
            )

        return await handler(arguments, context)

    async def _handle_create(self, args: dict, context: ToolCallContext) -> ToolResult:
        name = args["name"]
        content = args.get("content", "")

        if not content:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="'content' is required for create action.",
            )

        slug = clean_skill_name(name)
        if not slug:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Invalid skill name '{name}' after cleaning.",
            )

        skill_dir = self.store.skills_dir / slug
        if skill_dir.exists():
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Skill '{slug}' already exists at {skill_dir}.",
            )

        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

        # 注册 store
        self.store.ensure(slug, created_by="agent")

        # 刷新 SkillManager 索引
        self._refresh_index()

        return ToolResult(
            status=ToolStatus.SUCCESS,
            content=f"Skill '{slug}' created at {skill_dir}.",
        )

    async def _handle_patch(self, args: dict, context: ToolCallContext) -> ToolResult:
        name = args["name"]
        content = args.get("content", "")

        if not content:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="'content' is required for patch action.",
            )

        skill_dir = self.store.skills_dir / name
        skill_file = skill_dir / "SKILL.md"

        if not skill_file.exists():
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Skill '{name}' not found at {skill_dir}.",
            )

        if not self.store.is_registered(name):
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Skill '{name}' is not in store (may be builtin). Cannot patch.",
            )

        skill_file.write_text(content, encoding="utf-8")
        # 刷新索引以便新内容生效
        self._refresh_index()

        return ToolResult(
            status=ToolStatus.SUCCESS,
            content=f"Skill '{name}' patched successfully.",
        )

    async def _handle_delete(self, args: dict, context: ToolCallContext) -> ToolResult:
        name = args["name"]
        absorbed = args.get("absorbed_into", "")

        ok, msg = self.store.archive_skill(name)
        if not ok:
            return ToolResult(status=ToolStatus.ERROR, content=msg)

        result = f"Skill '{name}' archived."
        if absorbed:
            result += f" Absorbed into: {absorbed}."
        result += " It can be restored with '/skill restore {name}'."

        self._refresh_index()
        return ToolResult(status=ToolStatus.SUCCESS, content=result)

    async def _handle_list(self, args: dict, context: ToolCallContext) -> ToolResult:
        """列出所有 Skill 及其状态。"""
        skills_info = self.store.list_all_skills()
        store_data = self.store.read()

        if not skills_info:
            return ToolResult(
                status=ToolStatus.SUCCESS, content="No skills found."
            )

        lines = ["Available skills:\n"]
        for s in sorted(skills_info, key=lambda x: x["name"]):
            name = s["name"]
            state = s.get("state", "unknown")
            meta = store_data.get(name, {})
            source = meta.get("created_by", "unknown")
            uses = meta.get("use_count", 0)
            lines.append(f"  - {name}  (state={state}, source={source}, uses={uses})")

        return ToolResult(
            status=ToolStatus.SUCCESS, content="\n".join(lines)
        )

    async def _handle_write_file(
        self, args: dict, context: ToolCallContext
    ) -> ToolResult:
        return self._handle_subfile("write", args)

    async def _handle_remove_file(
        self, args: dict, context: ToolCallContext
    ) -> ToolResult:
        return self._handle_subfile("remove", args)

    def _handle_subfile(self, action: str, args: dict) -> ToolResult:
        name = args["name"]
        file_path = args.get("file_path", "")

        if not file_path:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="'file_path' is required.",
            )

        skill_dir = self.store.skills_dir / name
        if not skill_dir.exists():
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Skill '{name}' directory not found.",
            )

        # 路径穿越防护
        target = (skill_dir / file_path).resolve()
        if not str(target).startswith(str(skill_dir.resolve())):
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Path '{file_path}' escapes skill directory.",
            )

        if action == "write":
            file_content = args.get("file_content", "")
            if not file_content:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content="'file_content' is required for write_file.",
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(file_content, encoding="utf-8")
            rel = target.relative_to(skill_dir)
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"Written to {rel}.",
            )
        else:  # remove
            if not target.exists():
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content=f"File '{file_path}' not found.",
                )
            target.unlink()
            rel = target.relative_to(skill_dir)
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"Removed {rel}.",
            )

    def _refresh_index(self):
        try:
            from broca.skill_manager import SkillManager

            SkillManager().refresh_index()
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning(f"Failed to refresh skill index: {e}")
