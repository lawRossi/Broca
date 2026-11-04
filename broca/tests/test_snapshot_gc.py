"""
gc_snapshots() 回归测试

覆盖：
- 通道 A: .workspace 元数据检测（workspace 已删除 / 仍存在）
- 通道 B: hash 对比 DB workspace 集合（匹配 / 不匹配）
- dry-run 模式（不删除）
- force 模式（调用 delete_fn）
- 边界：snapshot_home 不存在 / 为空 / 无子目录
- 容错：删除失败不阻塞后续
- initialize() 写入 .workspace 元数据
"""

import hashlib
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from broca.snapshot.git_manager import gc_snapshots, _default_delete


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_snapshot_dir(home: Path, name: str, workspace: str | None = None) -> Path:
    """创建一个模拟 snapshot 目录，可选写入 .workspace 文件"""
    d = home / name
    d.mkdir(parents=True, exist_ok=True)
    if workspace is not None:
        (d / ".workspace").write_text(workspace, encoding="utf-8")
    return d


def _hash_of(ws: str) -> str:
    """与 GitManager._get_repo_path() 一致的 hash 计算"""
    return hashlib.sha256(str(Path(ws).resolve()).encode()).hexdigest()[:16]


# ------------------------------------------------------------------
# 通道 A: .workspace 元数据检测
# ------------------------------------------------------------------


class TestChannelAWorkspaceMetadata:
    """通道 A：通过 .workspace 文件检测 workspace 是否仍存在"""

    def test_workspace_deleted_is_orphan(self, tmp_path):
        """workspace 路径不存在 → 判定孤儿"""
        home = tmp_path / "snapshots"
        home.mkdir()
        # 创建一个指向不存在路径的 snapshot 目录
        _make_snapshot_dir(home, "abc123", workspace="/nonexistent/path")

        orphans = gc_snapshots(
            str(home), dry_run=True,
            valid_workspace_hashes=set(),
        )
        assert len(orphans) == 1
        assert orphans[0]["name"] == "abc123"
        assert orphans[0]["reason"] == "workspace_deleted"
        assert orphans[0]["workspace"] == "/nonexistent/path"

    def test_workspace_exists_is_not_orphan(self, tmp_path):
        """workspace 路径存在 → 非孤儿"""
        home = tmp_path / "snapshots"
        home.mkdir()
        ws_dir = tmp_path / "my-project"
        ws_dir.mkdir()
        _make_snapshot_dir(home, "abc123", workspace=str(ws_dir))

        orphans = gc_snapshots(
            str(home), dry_run=True,
            valid_workspace_hashes=set(),
        )
        assert orphans == []

    def test_workspace_file_unreadable_skips(self, tmp_path):
        """.workspace 文件内容损坏 → 视为孤儿（workspace=None）"""
        home = tmp_path / "snapshots"
        home.mkdir()
        d = _make_snapshot_dir(home, "def456")
        (d / ".workspace").write_text("\x00\x01\x02", encoding="utf-8", errors="replace")

        orphans = gc_snapshots(
            str(home), dry_run=True,
            valid_workspace_hashes=set(),
        )
        # 二进制内容 strip 后可能是空或非有效路径
        # 关键是不抛异常
        assert isinstance(orphans, list)


# ------------------------------------------------------------------
# 通道 B: hash 对比 DB workspace 集合
# ------------------------------------------------------------------


class TestChannelBHashComparison:
    """通道 B：无 .workspace 文件时，用目录名 hash 对比 DB"""

    def test_hash_in_valid_set_not_orphan(self, tmp_path):
        """目录名在合法 hash 集合中 → 非孤儿"""
        home = tmp_path / "snapshots"
        home.mkdir()
        ws = str(tmp_path / "project")
        Path(ws).mkdir()
        h = _hash_of(ws)
        _make_snapshot_dir(home, h)  # 无 .workspace 文件

        orphans = gc_snapshots(
            str(home), dry_run=True,
            valid_workspace_hashes={h},
        )
        assert orphans == []

    def test_hash_not_in_valid_set_is_orphan(self, tmp_path):
        """目录名不在合法 hash 集合中 → 孤儿（reason=no_session）"""
        home = tmp_path / "snapshots"
        home.mkdir()
        _make_snapshot_dir(home, "deadbeef00000000")

        orphans = gc_snapshots(
            str(home), dry_run=True,
            valid_workspace_hashes={"aabbccdd11112222"},
        )
        assert len(orphans) == 1
        assert orphans[0]["name"] == "deadbeef00000000"
        assert orphans[0]["reason"] == "no_session"
        assert orphans[0]["workspace"] is None

    def test_empty_valid_set_all_dirs_orphan(self, tmp_path):
        """合法集合为空 → 所有无 .workspace 的目录都是孤儿"""
        home = tmp_path / "snapshots"
        home.mkdir()
        _make_snapshot_dir(home, "hash1")
        _make_snapshot_dir(home, "hash2")

        orphans = gc_snapshots(
            str(home), dry_run=True,
            valid_workspace_hashes=set(),
        )
        assert len(orphans) == 2
        assert all(o["reason"] == "no_session" for o in orphans)


# ------------------------------------------------------------------
# dry-run / force 模式
# ------------------------------------------------------------------


class TestDryRunAndForce:
    """dry-run 不删除，force 模式调用 delete_fn"""

    def test_dry_run_does_not_delete(self, tmp_path):
        """dry_run=True 时目录不被删除"""
        home = tmp_path / "snapshots"
        home.mkdir()
        d = _make_snapshot_dir(home, "abc123", workspace="/nonexistent")
        delete_calls = []

        orphans = gc_snapshots(
            str(home), dry_run=True,
            valid_workspace_hashes=set(),
            delete_fn=lambda p: delete_calls.append(p),
        )
        assert len(orphans) == 1
        assert delete_calls == []  # 未调用删除
        assert d.exists()  # 目录仍在

    def test_force_calls_delete_fn(self, tmp_path):
        """dry_run=False 时调用 delete_fn"""
        home = tmp_path / "snapshots"
        home.mkdir()
        _make_snapshot_dir(home, "abc123", workspace="/nonexistent")
        delete_calls = []

        orphans = gc_snapshots(
            str(home), dry_run=False,
            valid_workspace_hashes=set(),
            delete_fn=lambda p: (delete_calls.append(p), p.rmdir()),
        )
        assert len(orphans) == 1
        assert len(delete_calls) == 1

    def test_delete_failure_does_not_block_others(self, tmp_path):
        """某个目录删除失败不影响其他目录"""
        home = tmp_path / "snapshots"
        home.mkdir()
        d1 = _make_snapshot_dir(home, "orphan1", workspace="/nonexistent1")
        d2 = _make_snapshot_dir(home, "orphan2", workspace="/nonexistent2")

        def flaky_delete(p: Path):
            if p.name == "orphan1":
                raise PermissionError("denied")
            shutil.rmtree(p)

        orphans = gc_snapshots(
            str(home), dry_run=False,
            valid_workspace_hashes=set(),
            delete_fn=flaky_delete,
        )
        assert len(orphans) == 2
        # orphan1 删除失败，记录了 error
        failed = [o for o in orphans if o["name"] == "orphan1"]
        assert len(failed) == 1
        assert "error" in failed[0]
        # orphan2 成功删除
        assert not d2.exists()
        # orphan1 仍在
        assert d1.exists()


# ------------------------------------------------------------------
# 边界情况
# ------------------------------------------------------------------


class TestEdgeCases:

    def test_snapshot_home_not_exists(self, tmp_path):
        """snapshot_home 不存在 → 返回空列表"""
        orphans = gc_snapshots(
            str(tmp_path / "nonexistent"), dry_run=True,
            valid_workspace_hashes=set(),
        )
        assert orphans == []

    def test_empty_snapshot_home(self, tmp_path):
        """snapshot_home 存在但无子目录 → 返回空列表"""
        home = tmp_path / "snapshots"
        home.mkdir()
        orphans = gc_snapshots(
            str(home), dry_run=True,
            valid_workspace_hashes=set(),
        )
        assert orphans == []

    def test_non_directory_files_ignored(self, tmp_path):
        """非目录文件被跳过"""
        home = tmp_path / "snapshots"
        home.mkdir()
        (home / "a_file.txt").write_text("not a dir")
        orphans = gc_snapshots(
            str(home), dry_run=True,
            valid_workspace_hashes=set(),
        )
        assert orphans == []

    def test_mixed_channel_a_and_b(self, tmp_path):
        """混合场景：有 .workspace 的走通道 A，没有的走通道 B"""
        home = tmp_path / "snapshots"
        home.mkdir()

        ws = str(tmp_path / "project")
        Path(ws).mkdir()
        h = _hash_of(ws)

        # 通道 A: workspace 已删除
        _make_snapshot_dir(home, "aabb0000", workspace="/deleted/ws")
        # 通道 A: workspace 仍存在
        _make_snapshot_dir(home, "ccdd0000", workspace=ws)
        # 通道 B: hash 匹配
        _make_snapshot_dir(home, h)
        # 通道 B: hash 不匹配
        _make_snapshot_dir(home, "ffff9999")

        orphans = gc_snapshots(
            str(home), dry_run=True,
            valid_workspace_hashes={h},
        )
        assert len(orphans) == 2
        names = {o["name"] for o in orphans}
        assert names == {"aabb0000", "ffff9999"}
        reasons = {o["name"]: o["reason"] for o in orphans}
        assert reasons["aabb0000"] == "workspace_deleted"
        assert reasons["ffff9999"] == "no_session"


# ------------------------------------------------------------------
# initialize() 写入 .workspace 元数据
# ------------------------------------------------------------------


class TestInitializeWritesWorkspaceFile:

    def test_initialize_creates_workspace_file(self, tmp_path):
        """GitManager.initialize() 后 snapshot 目录包含 .workspace 文件"""
        from broca.snapshot.git_manager import GitManager

        workspace = tmp_path / "my-project"
        workspace.mkdir()

        # 将 snapshot_home 指向 tmp_path
        with patch("broca.configs.get_configs") as mock_cfg:
            mock_cfg.return_value.snapshot_home = str(tmp_path / "snapshots")

            # 清除单例缓存
            ws_str = str(workspace.resolve())
            GitManager._instances.pop(ws_str, None)

            gm = GitManager(str(workspace))
            gm.initialize()

            # .workspace 文件应存在且内容正确
            ws_file = gm.repo_path / ".workspace"
            assert ws_file.exists()
            content = ws_file.read_text(encoding="utf-8")
            assert content == str(workspace.resolve())

            # 清理
            gm.cleanup()
            GitManager._instances.pop(ws_str, None)

    def test_initialize_does_not_overwrite_existing_workspace(self, tmp_path):
        """已有 .workspace 文件时不覆盖"""
        from broca.snapshot.git_manager import GitManager

        workspace = tmp_path / "my-project"
        workspace.mkdir()

        with patch("broca.configs.get_configs") as mock_cfg:
            mock_cfg.return_value.snapshot_home = str(tmp_path / "snapshots")

            ws_str = str(workspace.resolve())
            GitManager._instances.pop(ws_str, None)

            gm = GitManager(str(workspace))
            gm.initialize()

            # 手动修改 .workspace 内容
            ws_file = gm.repo_path / ".workspace"
            ws_file.write_text("/custom/override", encoding="utf-8")

            # 再次 initialize 不应覆盖
            gm2 = GitManager(str(workspace))
            gm2.initialize()

            content = ws_file.read_text(encoding="utf-8")
            assert content == "/custom/override"

            gm.cleanup()
            GitManager._instances.pop(ws_str, None)
