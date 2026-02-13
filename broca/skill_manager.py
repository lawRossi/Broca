import os

import yaml
from loguru import logger


class SkillManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SkillManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._initialized = True
            self.skill_spec_template = "Base path of skill: {base_path}\nSpecification of {skill_name}:{skill_spec}"
            self._load_all_skills()

    def get_skills(self, skill_names: list[str] | None = None) -> dict[str, dict]:
        if skill_names is not None:
            skills = {}
            for name in skill_names:
                if name not in self.skills:
                    # raise ValueError(f"Skill '{name}' not found.")
                    continue
                skills[name] = self.skills[name]
            return skills
        else:
            return self.skills

    def _load_all_skills(self, skills_dir: str = "skills") -> None:
        skills = {}
        if os.path.exists(skills_dir) and os.path.isdir(skills_dir):
            for dirname in os.listdir(skills_dir):
                if not os.path.isdir(os.path.join(skills_dir, dirname)):
                    continue
                skill_file = os.path.join(skills_dir, dirname, "SKILL.md")
                skill = self._load_skill(skill_file)
                if "name" in skill:
                    skills[skill["name"]] = skill

        self.skills = skills

    def _load_skill(self, skill_file: str) -> dict[str, str]:
        with open(skill_file, encoding="utf-8") as fi:
            content = fi.read()
        parts = content.split("---", 2)
        if len(parts) < 3:
            logger.error(f"Invalid format in {skill_file}.")
            return {}
        header = parts[1].strip()
        spec = parts[2].strip()
        try:
            skill = yaml.safe_load(header)
        except yaml.YAMLError as e:
            logger.error(f"YAML parsing error in {skill_file}: {e}")
            return {}
        if not skill:
            skill = {}
        skill["spec"] = spec
        skill["base_path"] = os.path.dirname(skill_file)
        return skill

    def load_skill_spec(self, skill_name: str) -> str:
        if skill_name in self.skills:
            skill_spec = self.skills[skill_name]["spec"]
            base_path = self.skills[skill_name]["base_path"]
            skill_spec = self.skill_spec_template.format(
                skill_name=skill_name, skill_spec=skill_spec, base_path=base_path
            )
            logger.debug(f"Loaded skill spec for '{skill_name}'.")
            return skill_spec
        else:
            logger.error(f"Skill '{skill_name}' not found.")
            return f"Error: Skill '{skill_name}' not found."
