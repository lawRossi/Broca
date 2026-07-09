"""
Phase-level integration tests for Phase 2: Agent Skill Operations
Phase AC: skill_manage(action="create") 可创建 Skill
Phase AC: run_skill_sub_agent() 正确创建子 Agent 并执行
Phase AC: /skill-create 通过子 Agent 创建 Skill
Phase AC: /skill-suggest 输出改进文档到 plans/
"""

import asyncio
import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from broca.tools.skill import SkillManage
from broca.tools.tool import ToolCallContext, ToolStatus
from broca.tools.skill_store import SkillStore

ROOT = Path(__file__).parents[4]


def _load_skill_create_mod():
    init_path = ROOT / "broca" / "commands" / "builtin" / "skill-create" / "__init__.py"
    spec = importlib.util.spec_from_file_location("skill_create_integ", init_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["skill_create_integ"] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_skill_suggest_mod():
    init_path = ROOT / "broca" / "commands" / "builtin" / "skill-suggest" / "__init__.py"
    spec = importlib.util.spec_from_file_location("skill_suggest_integ", init_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["skill_suggest_integ"] = mod
    spec.loader.exec_module(mod)
    return mod


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def env():
    """Phase 2 测试环境。"""
    tmp_dir = Path(tempfile.mkdtemp())
    store = SkillStore(skills_dir=tmp_dir)
    manage = SkillManage()
    manage.store = store
    yield store, manage, tmp_dir
    shutil.rmtree(tmp_dir, ignore_errors=True)


def fake_tool_context():
    ctx = ToolCallContext()
    ctx.workspace = "/tmp"
    ctx.session_id = "test-session"
    return ctx


def test_phase_ac01_skill_manage_create_skill(env):
    """Phase AC: skill_manage(action="create") 可创建 Skill"""
    store, manage, tmp_dir = env

    content = """---
name: phase-test-skill
description: Integration test skill
---
# Integration Test
Test content for phase integration.
"""
    result = _run(manage._handle_create(
        {"name": "phase-test-skill", "content": content},
        fake_tool_context(),
    ))
    assert result.status == ToolStatus.SUCCESS
    assert (tmp_dir / "phase-test-skill" / "SKILL.md").exists()
    assert store.get("phase-test-skill")["created_by"] == "agent"


def test_phase_ac02_skill_manage_full_lifecycle(env):
    """Phase AC: SkillManage 完整生命周期：create → patch → delete"""
    store, manage, tmp_dir = env

    # 1. Create
    content = "---\nname: lifecycle\n---\nOriginal"
    _run(manage._handle_create({"name": "lifecycle", "content": content}, fake_tool_context()))
    assert (tmp_dir / "lifecycle").exists()

    # 2. Patch
    updated = "---\nname: lifecycle\n---\nUpdated"
    result = _run(manage._handle_patch({"name": "lifecycle", "content": updated}, fake_tool_context()))
    assert result.status == ToolStatus.SUCCESS
    assert (tmp_dir / "lifecycle" / "SKILL.md").read_text(encoding="utf-8") == updated

    # 3. Write file
    result = _run(manage._handle_write_file(
        {"name": "lifecycle", "file_path": "scripts/test.sh", "file_content": "echo test"},
        fake_tool_context(),
    ))
    assert result.status == ToolStatus.SUCCESS
    assert (tmp_dir / "lifecycle" / "scripts" / "test.sh").exists()

    # 4. Archive (delete)
    result = _run(manage._handle_delete({"name": "lifecycle"}, fake_tool_context()))
    assert result.status == ToolStatus.SUCCESS
    assert not (tmp_dir / "lifecycle").exists()
    assert (tmp_dir / ".archive" / "lifecycle").exists()


def test_phase_ac03_name_cleaning_and_path_traversal(env):
    """Phase AC: 名称清洗与路径穿越防护"""
    store, manage, tmp_dir = env

    # 创建带特殊字符的名称
    content = "---\nname: safe\n---\nOk"
    result = _run(manage._handle_create(
        {"name": "  UNSAFE!!! Name   ", "content": content},
        fake_tool_context(),
    ))
    assert result.status == ToolStatus.SUCCESS
    # 名称被清洗
    assert (tmp_dir / "unsafe-name").exists()
    assert not (tmp_dir / "  UNSAFE!!! Name   ").exists()

    # 路径穿越被拦截
    result = _run(manage._handle_write_file(
        {"name": "unsafe-name", "file_path": "../../../etc/hack", "file_content": "x"},
        fake_tool_context(),
    ))
    assert result.status == ToolStatus.ERROR
    assert "escapes" in result.content


def test_phase_ac04_skill_create_command_structure():
    """Phase AC: /skill-create 命令结构完整"""
    create_mod = _load_skill_create_mod()
    assert hasattr(create_mod.SkillCreateCommand, "execute")
    # Prompt 模板包含必需内容
    assert "skill_manage" in create_mod.CREATE_PROMPT_TEMPLATE
    assert "{name}" in create_mod.CREATE_PROMPT_TEMPLATE
    assert "SKILL.md" in create_mod.CREATE_PROMPT_TEMPLATE


def test_phase_ac05_skill_suggest_command_structure():
    """Phase AC: /skill-suggest 命令结构完整"""
    suggest_mod = _load_skill_suggest_mod()
    assert hasattr(suggest_mod.SkillSuggestCommand, "execute")
    # Prompt 模板包含必需内容
    assert "当前问题" in suggest_mod.SUGGEST_PROMPT_TEMPLATE
    assert "改进方案" in suggest_mod.SUGGEST_PROMPT_TEMPLATE
    assert "预期效果" in suggest_mod.SUGGEST_PROMPT_TEMPLATE
    # 不包含修改工具
    assert "skill_manage" not in suggest_mod.ALLOWED_TOOLS
    assert "edit_file" not in suggest_mod.ALLOWED_TOOLS
