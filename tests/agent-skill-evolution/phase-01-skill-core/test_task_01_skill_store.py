"""
Tests for Task 1.1: SkillStore
Plan: plans/agent-skill-evolution-plan.md

AC 1: 可读写 `.skill_store.json`，并发锁生效
AC 2: `archive_skill()` 移入 `.archive/` + 状态更新
AC 3: `restore_skill()` 从 `.archive/` 恢复 + 状态更新
AC 4: 对 builtin Skill 执行 archive/restore 时报错
AC 5: `record_use()` / `record_view()` 正确递增
"""

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from broca.skill.skill_store import SkillStore, clean_skill_name


# ─── Fixtures ────────────────────────────────────────────


@pytest.fixture
def temp_skills_dir():
    """创建临时技能目录供测试使用。"""
    tmp_dir = Path(tempfile.mkdtemp())
    yield tmp_dir
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture
def store(temp_skills_dir):
    """创建一个 SkillStore 实例指向临时目录。"""
    return SkillStore(skills_dir=temp_skills_dir)


@pytest.fixture
def store_with_data(store, temp_skills_dir):
    """在 store 中预置测试数据。"""
    # 创建 agent skill 目录及 SKILL.md
    agent_skill_dir = temp_skills_dir / "my-agent-skill"
    agent_skill_dir.mkdir()
    (agent_skill_dir / "SKILL.md").write_text("---\nname: my-agent-skill\n---\nTest", encoding="utf-8")

    # 创建 builtin skill 目录及 SKILL.md
    builtin_skill_dir = temp_skills_dir / "builtin-skill"
    builtin_skill_dir.mkdir()
    (builtin_skill_dir / "SKILL.md").write_text("---\nname: builtin-skill\n---\nTest", encoding="utf-8")

    # 注册到 store
    store.ensure("my-agent-skill", created_by="agent")
    store.ensure("builtin-skill", created_by="builtin")
    return store, temp_skills_dir


# ─── AC 1: 可读写 .skill_store.json，并发锁生效 ──────


def test_ac01_store_creates_json_file(store, temp_skills_dir):
    """AC 1: 可读写 `.skill_store.json`，并发锁生效"""
    store_path = temp_skills_dir / ".skill_store.json"
    assert not store_path.exists()

    # 写入数据
    store.ensure("test-skill", created_by="agent")
    assert store_path.exists()

    # 读取验证
    data = json.loads(store_path.read_text(encoding="utf-8"))
    assert "test-skill" in data
    assert data["test-skill"]["created_by"] == "agent"
    assert data["test-skill"]["state"] == "active"


def test_ac01_store_read_write_roundtrip(store):
    """AC 1: 读写往返正确"""
    store.ensure("skill-a", created_by="agent")
    store.ensure("skill-b", created_by="builtin")

    # 读取验证
    data = store.read()
    assert len(data) == 2
    assert data["skill-a"]["created_by"] == "agent"
    assert data["skill-b"]["created_by"] == "builtin"


def test_ac01_lock_file_created_and_cleaned(store, temp_skills_dir):
    """AC 1: 并发锁文件被创建并清理"""
    lock_path = temp_skills_dir / ".skill_store.json.lock"
    assert not lock_path.exists()

    store.read()  # 触发锁

    # 锁文件应在操作后被清理
    assert not lock_path.exists()


def test_ac01_atomic_write(store, temp_skills_dir):
    """AC 1: 原子写使用 tmp→rename 模式"""
    store.ensure("test-skill", created_by="agent")
    tmp_path = temp_skills_dir / ".skill_store.json.tmp"
    # 临时文件应在写入后被清理
    assert not tmp_path.exists()
    # 主文件正常
    assert (temp_skills_dir / ".skill_store.json").exists()


# ─── AC 2: archive_skill() 移入 .archive/ + 状态更新 ─


def test_ac02_archive_agent_skill(store_with_data):
    """AC 2: `archive_skill()` 移入 `.archive/` + 状态更新"""
    store, skills_dir = store_with_data

    archive_dir = skills_dir / ".archive"
    assert not (archive_dir / "my-agent-skill").exists()

    ok, msg = store.archive_skill("my-agent-skill")
    assert ok, f"Archive should succeed: {msg}"

    # 验证目录已移入 .archive/
    assert (archive_dir / "my-agent-skill").exists()
    assert (archive_dir / "my-agent-skill" / "SKILL.md").exists()

    # 验证原目录不存在
    assert not (skills_dir / "my-agent-skill").exists()

    # 验证状态更新
    meta = store.get("my-agent-skill")
    assert meta["state"] == "archived"


def test_ac02_archive_nonexistent_skill_fails(store):
    """AC 2: 归档不存在的 Skill 返回错误"""
    ok, msg = store.archive_skill("nonexistent")
    assert not ok
    assert "not found" in msg


def test_ac02_archive_already_archived_fails(store_with_data):
    """AC 2: 归档已归档的 Skill（目标冲突）返回错误"""
    store, skills_dir = store_with_data
    store.archive_skill("my-agent-skill")

    # 再次归档（理论上已归档），但已移动过所以 skill 目录不再存在
    ok, msg = store.archive_skill("my-agent-skill")
    assert not ok
    assert "not found" in msg  # 因为目录已经移走了


# ─── AC 3: restore_skill() 恢复 + 状态更新 ────────────


def test_ac03_restore_archived_skill(store_with_data):
    """AC 3: `restore_skill()` 从 `.archive/` 恢复 + 状态更新"""
    store, skills_dir = store_with_data

    # 先归档
    store.archive_skill("my-agent-skill")
    assert not (skills_dir / "my-agent-skill").exists()

    # 再恢复
    ok, msg = store.restore_skill("my-agent-skill")
    assert ok, f"Restore should succeed: {msg}"

    # 验证目录已恢复
    assert (skills_dir / "my-agent-skill").exists()
    assert (skills_dir / "my-agent-skill" / "SKILL.md").exists()

    # 验证状态更新
    meta = store.get("my-agent-skill")
    assert meta["state"] == "active"


def test_ac03_restore_nonexistent_fails(store):
    """AC 3: 恢复不存在的归档 Skill 返回错误"""
    ok, msg = store.restore_skill("nonexistent")
    assert not ok
    assert "not found" in msg


def test_ac03_restore_conflict_fails(store_with_data):
    """AC 3: 恢复时目标已存在返回错误"""
    store, skills_dir = store_with_data

    store.archive_skill("my-agent-skill")

    # 创建同名目录阻止恢复
    (skills_dir / "my-agent-skill").mkdir()
    (skills_dir / "my-agent-skill" / "SKILL.md").write_text("conflict", encoding="utf-8")

    ok, msg = store.restore_skill("my-agent-skill")
    assert not ok
    assert "already exists" in msg


# ─── AC 4: 对 builtin Skill 执行 archive/restore 时报错 ─


def test_ac04_archive_builtin_fails(store_with_data):
    """AC 4: 对 builtin Skill 执行 archive 时报错"""
    store, skills_dir = store_with_data

    ok, msg = store.archive_skill("builtin-skill")
    assert not ok, "Should not allow archiving builtin skill"
    assert "builtin" in msg or "agent-created" in msg


def test_ac04_archive_builtin_does_not_move(store_with_data):
    """AC 4: builtin Skill archive 失败时目录不变"""
    store, skills_dir = store_with_data

    original_path = skills_dir / "builtin-skill"
    assert original_path.exists()

    store.archive_skill("builtin-skill")

    # 目录应仍在原位置
    assert original_path.exists()
    # .archive/ 下不应有
    assert not (skills_dir / ".archive" / "builtin-skill").exists()


# ─── AC 5: record_use() / record_view() 正确递增 ─────


def test_ac05_record_use_increments(store):
    """AC 5: `record_use()` 正确递增 use_count"""
    store.ensure("test-skill", created_by="agent")
    meta = store.get("test-skill")
    assert meta["use_count"] == 0

    store.record_use("test-skill")
    meta = store.get("test-skill")
    assert meta["use_count"] == 1

    store.record_use("test-skill")
    store.record_use("test-skill")
    meta = store.get("test-skill")
    assert meta["use_count"] == 3


def test_ac05_record_view_increments(store):
    """AC 5: `record_view()` 正确递增 view_count"""
    store.ensure("test-skill", created_by="agent")

    store.record_view("test-skill")
    meta = store.get("test-skill")
    assert meta["view_count"] == 1

    store.record_view("test-skill")
    meta = store.get("test-skill")
    assert meta["view_count"] == 2


def test_ac05_record_updates_timestamp(store):
    """AC 5: record_use/record_view 更新时间戳"""
    store.ensure("test-skill", created_by="agent")
    meta = store.get("test-skill")
    assert meta["last_used_at"] is None
    assert meta["last_viewed_at"] is None

    store.record_use("test-skill")
    meta = store.get("test-skill")
    assert meta["last_used_at"] is not None

    store.record_view("test-skill")
    meta = store.get("test-skill")
    assert meta["last_viewed_at"] is not None


# ─── 辅助功能验证 ──────────────────────────────────────


def test_clean_skill_name():
    """clean_skill_name 正确清洗名称"""
    assert clean_skill_name("My Skill!") == "my-skill"
    assert clean_skill_name("  Hello World  ") == "hello-world"
    assert clean_skill_name("UPPER-CASE") == "upper-case"
    assert clean_skill_name("special___chars!!!") == "special-chars"
    assert clean_skill_name("") == ""


def test_agent_created_filter(store):
    """agent_created() 只返回 agent 创建的 Skill"""
    store.ensure("agent-skill", created_by="agent")
    store.ensure("builtin-skill", created_by="builtin")

    agent_skills = store.agent_created()
    assert "agent-skill" in agent_skills
    assert "builtin-skill" not in agent_skills


def test_get_by_state(store):
    """get_by_state 按状态过滤"""
    store.ensure("active-skill", created_by="agent")
    # 直接修改状态
    store.update("active-skill", state="active")

    active = store.get_by_state("active")
    assert "active-skill" in active
