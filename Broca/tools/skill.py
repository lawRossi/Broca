from Broca.skill_manager import SkillManager
from Broca.tools.tool import Tool, ToolCallContext


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

    async def _execute(self, arguments: dict, context: ToolCallContext):
        skill_name = arguments["skill_name"]
        return self.skill_manager.load_skill_spec(skill_name)
