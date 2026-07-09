"""
Tests for Task 2.1: SkillManage Tool
Plan: plans/agent-skill-evolution-plan.md

AC 1: 子 Agent 可调用创建 Skill
AC 2: 名称清洗、来源标记正确
AC 3: 路径穿越防护有效
AC 4: patch/delete/write_file 正常
"""

import asyncio
import shutil
import tempfile
from pathlib import Path

import pytest

from broca.tools.skill import SkillManage
from broca.tools.tool import ToolCallContext, ToolResult, ToolStatus
from broca.skill.skill_store import SkillStore


# ─── Fixtures ────────────────────────────────────────────


@pytest.fixture
def temp_skills_dir():
    tmp_dir = Path(tempfile.mkdtemp())
    yield tmp_dir
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture
def manage(temp_skills_dir):
    """SkillManage 实例指向临时目录。"""
    m = SkillManage()
    m.store = SkillStore(skills_dir=temp_skills_dir)
    return m


def fake_context():
    ctx = ToolCallContext()
    ctx.workspace = "/tmp"
    ctx.session_id = "test-session"
    return ctx


def _run(coro):
    return asyncio.run(coro)


# ─── AC 1: 子 Agent 可调用创建 Skill ────────────────────


def test_ac01_create_skill(manage, temp_skills_dir):
    """AC 1: 子 Agent 可调用创建 Skill"""
    content = """---
name: my-test-skill
description: A test skill
---
# My Test Skill
Simple content
"""
    result = _run(manage._handle_create(
        {"name": "My Test Skill!", "content": content},
        fake_context(),
    ))
    assert result.status == ToolStatus.SUCCESS
    assert "created" in result.content

    # 验证目录和文件存在（名称被清洗）
    slug = "my-test-skill"
    skill_dir = temp_skills_dir / slug
    assert skill_dir.exists()
    assert (skill_dir / "SKILL.md").exists()
    assert (skill_dir / "SKILL.md").read_text(encoding="utf-8") == content


def test_ac01_create_duplicate_fails(manage):
    """AC 1: 创建已存在的 Skill 返回错误"""
    content = "---\nname: dup\n---\nDup"
    # 第一次创建成功
    _run(manage._handle_create({"name": "dup", "content": content}, fake_context()))
    # 第二次应失败
    result = _run(manage._handle_create({"name": "dup", "content": content}, fake_context()))
    assert result.status == ToolStatus.ERROR
    assert "already exists" in result.content


# ─── AC 2: 名称清洗、来源标记正确 ──────────────────────


def test_ac02_name_cleaned_to_slug(manage, temp_skills_dir):
    """AC 2: 名称清洗正确"""
    content = "---\nname: complex name!\n---\nTest"
    result = _run(manage._handle_create(
        {"name": "  Complex Name!!!   ", "content": content},
        fake_context(),
    ))
    assert result.status == ToolStatus.SUCCESS

    # 目录名应为 slug
    assert (temp_skills_dir / "complex-name").exists()
    assert not (temp_skills_dir / "  Complex Name!!!   ").exists()


def test_ac02_source_marked_agent(manage, temp_skills_dir):
    """AC 2: 来源标记为 agent"""
    content = "---\nname: test\n---\nTest"
    _run(manage._handle_create({"name": "test", "content": content}, fake_context()))

    meta = manage.store.get("test")
    assert meta is not None
    assert meta["created_by"] == "agent"
    assert meta["state"] == "active"


# ─── AC 3: 路径穿越防护有效 ────────────────────────────


def test_ac03_path_traversal_write_file(manage, temp_skills_dir):
    """AC 3: write_file 路径穿越防护有效"""
    # 先创建 skill
    content = "---\nname: safe-skill\n---\nTest"
    _run(manage._handle_create({"name": "safe-skill", "content": content}, fake_context()))

    # 尝试路径穿越
    result = _run(manage._handle_write_file(
        {"name": "safe-skill", "file_path": "../../escape.txt", "file_content": "hack"},
        fake_context(),
    ))
    assert result.status == ToolStatus.ERROR
    assert "escapes" in result.content or "escape" in result.content


def test_ac03_path_traversal_remove_file(manage, temp_skills_dir):
    """AC 3: remove_file 路径穿越防护有效"""
    content = "---\nname: safe-skill\n---\nTest"
    _run(manage._handle_create({"name": "safe-skill", "content": content}, fake_context()))

    result = _run(manage._handle_remove_file(
        {"name": "safe-skill", "file_path": "../../etc/passwd"},
        fake_context(),
    ))
    assert result.status == ToolStatus.ERROR
    assert "escapes" in result.content


# ─── AC 4: patch/delete/write_file 正常 ────────────────


def test_ac04_patch_skill(manage, temp_skills_dir):
    """AC 4: patch 更新文件内容"""
    original = "---\nname: patchable\n---\nOriginal content"
    _run(manage._handle_create({"name": "patchable", "content": original}, fake_context()))

    updated = "---\nname: patchable\n---\nUpdated content"
    result = _run(manage._handle_patch(
        {"name": "patchable", "content": updated},
        fake_context(),
    ))
    assert result.status == ToolStatus.SUCCESS

    # 验证内容更新
    skill_file = temp_skills_dir / "patchable" / "SKILL.md"
    assert skill_file.read_text(encoding="utf-8") == updated


def test_ac04_delete_archives_skill(manage, temp_skills_dir):
    """AC 4: delete 归档 Skill"""
    content = "---\nname: deletable\n---\nTest"
    _run(manage._handle_create({"name": "deletable", "content": content}, fake_context()))

    assert (temp_skills_dir / "deletable").exists()

    result = _run(manage._handle_delete(
        {"name": "deletable"},
        fake_context(),
    ))
    assert result.status == ToolStatus.SUCCESS
    assert "archived" in result.content

    # 原目录应移到 .archive/
    assert not (temp_skills_dir / "deletable").exists()
    assert (temp_skills_dir / ".archive" / "deletable").exists()

    # 状态更新
    meta = manage.store.get("deletable")
    assert meta["state"] == "archived"


def test_ac04_write_file_in_skill_dir(manage, temp_skills_dir):
    """AC 4: write_file 在 skill 目录下创建文件"""
    content = "---\nname: test-skill\n---\nTest"
    _run(manage._handle_create({"name": "test-skill", "content": content}, fake_context()))

    result = _run(manage._handle_write_file(
        {"name": "test-skill", "file_path": "references/guide.md", "file_content": "# Guide\nInstructions"},
        fake_context(),
    ))
    assert result.status == ToolStatus.SUCCESS

    target = temp_skills_dir / "test-skill" / "references" / "guide.md"
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "# Guide\nInstructions"


def test_ac04_remove_file_in_skill_dir(manage, temp_skills_dir):
    """AC 4: remove_file 删除 skill 目录下的文件"""
    content = "---\nname: test-skill\n---\nTest"
    _run(manage._handle_create({"name": "test-skill", "content": content}, fake_context()))

    # 先写再删
    _run(manage._handle_write_file(
        {"name": "test-skill", "file_path": "temp.txt", "file_content": "temp"},
        fake_context(),
    ))
    target = temp_skills_dir / "test-skill" / "temp.txt"
    assert target.exists()

    result = _run(manage._handle_remove_file(
        {"name": "test-skill", "file_path": "temp.txt"},
        fake_context(),
    ))
    assert result.status == ToolStatus.SUCCESS
    assert not target.exists()
