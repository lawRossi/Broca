from broca.skill_manager import SkillManager
from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus


class LoadSkill(Tool):
    def __init__(self, skill_manager: SkillManager):
        self.skill_manager = skill_manager

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
            result = self.skill_manager.load_skill_spec(skill_name)
            return ToolResult(status=ToolStatus.SUCCESS, content=result)
        except ValueError:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"Skill '{skill_name}' not found"
            )
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"Error loading skill: {e}"
            )
