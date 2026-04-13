import os
from pathlib import Path

import yaml

from broca.logging_config import get_logger

logger = get_logger(__name__)


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
            self._load_installed_skills()

    def get_skills(self, workspace: str, skill_names: str | None) -> dict[str, dict]:
        skills: dict[str, dict] = {}
        if skill_names == "all":
            skills.update(self.skills)
            for skill in self._load_workspace_skills(workspace).values():
                if skill["name"] not in skills:
                    skills[skill["name"]] = skill
                else:
                    logger.warning(f"Duplicate skill ignored: {skill['name']}")
        elif skill_names:
            found = set()
            for name in skill_names.split(","):
                if name in self.skills:
                    skills[name] = self.skills[name]
                    found.add(name)

            not_found = set(skill_names.split(",")) - found
            if not_found:
                workspace_skills = self._load_workspace_skills(workspace)
                for name in not_found:
                    if name in workspace_skills:
                        skills[name] = workspace_skills[name]
                    else:
                        raise ValueError(f"Skill '{name}' not found.")
        return skills

    def _load_installed_skills(self) -> None:
        boostrap_dirs = [
            Path(__file__).parent.parent / "skills",
            Path.home() / ".agents/skills",
        ]

        self.skills: dict[str, dict] = {}
        for skills_dir in boostrap_dirs:
            skills = self._load_batch_skills(skills_dir)
            for name in skills:
                if name not in self.skills:
                    self.skills[name] = skills[name]
                else:
                    logger.warning(f"Duplicate skill ignored: {name}")

    def _load_workspace_skills(self, workspace: str) -> dict[str, dict]:
        boostrap_dirs = [
            Path(workspace) / "skills",
            Path(workspace) / ".agents/skills",
        ]
        skills: dict[str, dict] = {}
        for skills_dir in boostrap_dirs:
            for skill in self._load_batch_skills(skills_dir).values():
                if skill["name"] not in skills and skill["name"] not in self.skills:
                    skills[skill["name"]] = skill
                else:
                    logger.warning(f"Duplicate skill ignored: {skill['name']}")
        return skills

    def _load_batch_skills(self, skills_dir) -> dict[str, dict]:
        skills = {}
        if os.path.exists(skills_dir) and os.path.isdir(skills_dir):
            for dirname in os.listdir(skills_dir):
                if not os.path.isdir(os.path.join(skills_dir, dirname)):
                    continue
                skill_file = os.path.join(skills_dir, dirname, "SKILL.md")
                skill = self._load_skill(skill_file)
                if "name" in skill:
                    if skill["name"] not in skills:
                        skills[skill["name"]] = skill
                    else:
                        logger.warning(f"Duplicate skill ignored: {skill['name']}")
        return skills

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

    def load_skill_spec(self, skill_name: str, workspace: str) -> str:
        if skill_name in self.skills:
            return self._wrap_skill(self.skills[skill_name])

        workspace_skills = self._load_workspace_skills(workspace)
        if skill_name in workspace_skills:
            return self._wrap_skill(workspace_skills[skill_name])

        raise ValueError(f"Skill '{skill_name}' not found.")

    def _wrap_skill(self, skill):
        skill_spec = skill["spec"]
        base_path = skill["base_path"]
        skill_spec = self.skill_spec_template.format(
            skill_name=skill["name"], skill_spec=skill_spec, base_path=base_path
        )
        logger.debug(f"Loaded skill spec for '{skill['name']}'.")
        return skill_spec
