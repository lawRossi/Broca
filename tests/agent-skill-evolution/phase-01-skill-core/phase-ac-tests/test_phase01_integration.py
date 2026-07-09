"""
Phase-level integration tests for Phase 1: Skill Core
Phase AC: SkillStore 支持来源标记、状态、使用计数、归档/恢复
Phase AC: 归档/恢复只对 agent-created 生效
Phase AC: /skill list/view/archive/restore 全部可用
"""

import asyncio
import shutil
import tempfile
from pathlib import Path

import pytest

from broca.commands.builtin.skill import SkillCommand
from broca.commands.base import CommandContext, CommandResult
from broca.tools.skill_store import SkillStore


def _run(coro):
    return asyncio.run(coro)


class FakeContext:
    def __init__(self):
        self.agent = None
        self.session_id = "test-session"
        self.workspace = "/tmp/test-workspace"


@pytest.fixture
def env():
    """完整的 Phase 1 测试环境。"""
    tmp_dir = Path(tempfile.mkdtemp())
    store = SkillStore(skills_dir=tmp_dir)

    # 创建测试 skill 目录
    for name in ["skill-a", "skill-b"]:
        (tmp_dir / name).mkdir()
        (tmp_dir / name / "SKILL.md").write_text(f"---\nname: {name}\n---\nContent of {name}", encoding="utf-8")
        store.ensure(name, created_by="agent")

    # 内置 skill
    (tmp_dir / "builtin-tool").mkdir()
    (tmp_dir / "builtin-tool" / "SKILL.md").write_text("---\nname: builtin-tool\n---\nBuiltin", encoding="utf-8")
    store.ensure("builtin-tool", created_by="builtin")

    cmd = SkillCommand()
    cmd.store = store

    yield store, cmd, tmp_dir
    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_phase_ac01_full_flow_list_view_archive_restore(env):
    """Phase AC: 完整的 list → view → archive → restore 流程"""
    store, cmd, tmp_dir = env

    # 1. List — 列出所有
    result = _run(cmd.execute("list", FakeContext()))
    assert "skill-a" in result.value
    assert "skill-b" in result.value
    assert "builtin-tool" in result.value

    # 2. View — 查看特定 skill
    result = _run(cmd.execute("view skill-a", FakeContext()))
    assert "Content of skill-a" in result.value
    assert "State:" in result.value
    assert "Source:" in result.value

    # 3. Archive — 归档 agent skill
    result = _run(cmd.execute("archive skill-a", FakeContext()))
    assert "✅" in result.value
    assert store.get("skill-a")["state"] == "archived"
    assert not (tmp_dir / "skill-a").exists()
    assert (tmp_dir / ".archive" / "skill-a").exists()

    # 4. List archived — 只显示已归档
    result = _run(cmd.execute("list archived", FakeContext()))
    assert "skill-a" in result.value
    assert "skill-b" not in result.value

    # 5. Restore — 恢复
    result = _run(cmd.execute("restore skill-a", FakeContext()))
    assert "✅" in result.value
    assert store.get("skill-a")["state"] == "active"
    assert (tmp_dir / "skill-a").exists()

    # 6. List all — 验证回到完整列表
    result = _run(cmd.execute("list", FakeContext()))
    assert "skill-a" in result.value


def test_phase_ac02_archive_builtin_rejected(env):
    """Phase AC: 归档/恢复只对 agent-created 生效"""
    store, cmd, tmp_dir = env

    result = _run(cmd.execute("archive builtin-tool", FakeContext()))
    assert result.type == "error"
    # builtin skill 仍保留在原位
    assert (tmp_dir / "builtin-tool").exists()


def test_phase_ac03_usage_tracking(env):
    """Phase AC: 使用计数功能正常"""
    store, cmd, tmp_dir = env

    # 初始 use_count = 0
    assert store.get("skill-b")["use_count"] == 0

    # 查看会增加 view_count
    _run(cmd.execute("view skill-b", FakeContext()))
    assert store.get("skill-b")["view_count"] == 1

    # 模拟 record_use
    store.record_use("skill-b")
    assert store.get("skill-b")["use_count"] == 1
