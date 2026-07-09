"""
Tests for Task 1.2: /skill LocalCommand
Plan: plans/agent-skill-evolution-plan.md

AC 1: `/skill list` 列出所有 Skill
AC 2: `/skill list archived` 只显示 archived
AC 3: `/skill view my-skill` 显示内容 + 元数据
AC 4: `/skill archive my-skill` 归档
AC 5: `/skill restore my-skill` 恢复
AC 6: 对内置 Skill archive 时报错
"""

import asyncio
import shutil
import tempfile
from pathlib import Path

import pytest

from broca.commands.builtin.skill import SkillCommand
from broca.commands.base import CommandContext, CommandResult
from broca.skill.skill_store import SkillStore


# ─── Fixtures ────────────────────────────────────────────


@pytest.fixture
def temp_skills_dir():
    """创建临时技能目录。"""
    tmp_dir = Path(tempfile.mkdtemp())
    yield tmp_dir
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture
def store(temp_skills_dir):
    """关联的 SkillStore。"""
    return SkillStore(skills_dir=temp_skills_dir)


@pytest.fixture
def cmd(store, temp_skills_dir):
    """SkillCommand 实例，使用临时目录。"""
    command = SkillCommand()
    command.store = store  # 替换为测试用的 store
    return command


class FakeContext:
    """模拟 CommandContext。"""
    def __init__(self):
        self.agent = None
        self.session_id = "test-session"
        self.workspace = "/tmp/test-workspace"


def _init_skill_dir(base_dir: Path, name: str, extra_content: str = "Test content"):
    """在 base_dir 下创建 Skill 目录 + SKILL.md（name 与目录名一致）。"""
    skill_dir = base_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    content = f"---\nname: {name}\n---\n{extra_content}"
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return skill_dir


def _run(coro):
    """Helper to run async command."""
    return asyncio.run(coro)


# ─── AC 1: /skill list 列出所有 Skill ──────────────────


def test_ac01_list_all_skills(cmd, store, temp_skills_dir):
    """AC 1: `/skill list` 列出所有 Skill"""
    # 准备数据：注意 SKILL.md 中的 name 必须与目录名一致
    _init_skill_dir(temp_skills_dir, "alpha-skill")
    _init_skill_dir(temp_skills_dir, "beta-skill")
    store.ensure("alpha-skill", created_by="agent")
    store.ensure("beta-skill", created_by="agent")

    result = _run(cmd.execute("list", FakeContext()))
    assert isinstance(result, CommandResult)
    output = result.value
    assert "alpha-skill" in output
    assert "beta-skill" in output


# ─── AC 2: /skill list archived 只显示 archived ────────


def test_ac02_list_archived_only(cmd, store, temp_skills_dir):
    """AC 2: `/skill list archived` 只显示 archived"""
    # 准备一个 active 和一个 archived
    _init_skill_dir(temp_skills_dir, "active-skill")
    _init_skill_dir(temp_skills_dir, "archived-skill")
    store.ensure("active-skill", created_by="agent")
    store.ensure("archived-skill", created_by="agent")

    # 手动归档第二个
    store.update("archived-skill", state="archived")

    # 全部列表应包含两个
    result_all = _run(cmd.execute("list", FakeContext()))
    assert "active-skill" in result_all.value
    assert "archived-skill" in result_all.value

    # 只显示 archived
    result_archived = _run(cmd.execute("list archived", FakeContext()))
    assert "archived-skill" in result_archived.value
    assert "active-skill" not in result_archived.value


# ─── AC 3: /skill view my-skill 显示内容 + 元数据 ──────


def test_ac03_view_shows_content_and_metadata(cmd, store, temp_skills_dir):
    """AC 3: `/skill view my-skill` 显示内容 + 元数据"""
    _init_skill_dir(temp_skills_dir, "my-skill", "This is the skill content")
    store.ensure("my-skill", created_by="agent")

    result = _run(cmd.execute("view my-skill", FakeContext()))
    assert isinstance(result, CommandResult)
    output = result.value
    # 应包含元数据
    assert "State:" in output
    assert "Source:" in output
    assert "Use count:" in output
    # 应包含 SKILL.md 内容
    assert "This is the skill content" in output


def test_ac03_view_nonexistent_skill(cmd):
    """AC 3: 查看不存在的 Skill 返回错误"""
    result = _run(cmd.execute("view nonexistent", FakeContext()))
    assert result.type == "error"
    assert "not found" in result.value


def test_ac03_view_records_view_count(cmd, store, temp_skills_dir):
    """AC 3: view 操作记录查看次数"""
    _init_skill_dir(temp_skills_dir, "my-skill")
    store.ensure("my-skill", created_by="agent")

    assert store.get("my-skill")["view_count"] == 0
    _run(cmd.execute("view my-skill", FakeContext()))
    assert store.get("my-skill")["view_count"] == 1


# ─── AC 4: /skill archive my-skill 归档 ────────────────


def test_ac04_archive_agent_skill(cmd, store, temp_skills_dir):
    """AC 4: `/skill archive my-skill` 归档"""
    _init_skill_dir(temp_skills_dir, "my-skill")
    store.ensure("my-skill", created_by="agent")

    result = _run(cmd.execute("archive my-skill", FakeContext()))
    assert result.type == "text"
    assert "✅" in result.value

    # 验证状态
    assert store.get("my-skill")["state"] == "archived"


# ─── AC 5: /skill restore my-skill 恢复 ────────────────


def test_ac05_restore_archived_skill(cmd, store, temp_skills_dir):
    """AC 5: `/skill restore my-skill` 恢复"""
    _init_skill_dir(temp_skills_dir, "my-skill")
    store.ensure("my-skill", created_by="agent")

    # 先归档
    _run(cmd.execute("archive my-skill", FakeContext()))
    assert store.get("my-skill")["state"] == "archived"

    # 再恢复
    result = _run(cmd.execute("restore my-skill", FakeContext()))
    assert result.type == "text"
    assert "✅" in result.value
    assert store.get("my-skill")["state"] == "active"


# ─── AC 6: 对内置 Skill archive 时报错 ─────────────────


def test_ac06_archive_builtin_returns_error(cmd, store, temp_skills_dir):
    """AC 6: 对内置 Skill archive 时报错"""
    _init_skill_dir(temp_skills_dir, "builtin-skill")
    store.ensure("builtin-skill", created_by="builtin")

    result = _run(cmd.execute("archive builtin-skill", FakeContext()))
    assert result.type == "error"
    assert "❌" in result.value or "agent-created" in result.value


# ─── 边界情况 ──────────────────────────────────────────


def test_unknown_subcommand_shows_usage(cmd):
    """未知子命令显示用法"""
    result = _run(cmd.execute("unknown-command", FakeContext()))
    assert result.type == "error"
    assert "/skill" in result.value


def test_empty_args_shows_usage(cmd):
    """空参数显示用法"""
    result = _run(cmd.execute("", FakeContext()))
    assert "/skill" in result.value


def test_view_missing_name_shows_usage(cmd):
    """view 不带名称显示用法"""
    result = _run(cmd.execute("view", FakeContext()))
    assert result.type == "error"
    assert "Usage:" in result.value


def test_archive_missing_name_shows_usage(cmd):
    """archive 不带名称显示用法"""
    result = _run(cmd.execute("archive", FakeContext()))
    assert result.type == "error"
    assert "Usage:" in result.value
