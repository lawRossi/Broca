"""Tests for FileSkillManager (default SkillManager implementation)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from broca.components.skill_manager import SkillManager
from broca.skill.skill_manager import FileSkillManager, SkillManager as SkillManagerAlias


class TestFileSkillManagerABC:
    """Verify FileSkillManager satisfies the SkillManager ABC."""

    def test_issubclass(self):
        assert issubclass(FileSkillManager, SkillManager)

    def test_no_abstract_methods(self):
        assert FileSkillManager.__abstractmethods__ == frozenset()

    def test_alias(self):
        assert SkillManagerAlias is FileSkillManager


class TestFileSkillManagerBehavior:
    """Test basic FileSkillManager behavior."""

    @pytest.fixture
    def manager(self):
        return FileSkillManager()

    def test_load_skill_unknown_returns_none(self, manager):
        """Loading a non-existent skill returns None without raising."""
        result = manager.load_skill("nonexistent-skill-xyz")
        assert result is None

    def test_list_skills_returns_list(self, manager, tmp_path):
        """list_skills returns a list (possibly empty)."""
        skills = manager.list_skills(str(tmp_path))
        assert isinstance(skills, list)

    def test_get_skills_returns_dict(self, manager, tmp_path):
        """get_skills returns a dict."""
        skills = manager.get_skills(str(tmp_path), "all")
        assert isinstance(skills, dict)
