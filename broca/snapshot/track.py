"""
快照捕获模块

捕获文件系统快照，生成 Git 树哈希。
"""

import os
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import git

from .git_manager import GitManager


class SnapshotTracker:
    """快照捕获器"""

    def __init__(self, workspace_path: str):
        """
        初始化快照捕获器

        Args:
            workspace_path: 工作空间路径
        """
        self.workspace_path = Path(workspace_path).resolve()
        self.git_manager = GitManager(str(self.workspace_path))
        self.lock = threading.Semaphore(1)  # 并发控制锁

    def track(self, ignore_patterns: Optional[list[str]] = None) -> str:
        """
        捕获快照

        Args:
            ignore_patterns: 额外的忽略模式列表

        Returns:
            Git 树哈希
        """
        with self.lock:
            return self._track_snapshot(ignore_patterns)

    def _track_snapshot(self, ignore_patterns: Optional[list[str]] = None) -> str:
        """实际执行快照捕获"""
        # 确保 Git 仓库已初始化
        self.git_manager.ensure_initialized()

        # 同步忽略规则
        self.git_manager.sync_ignore_rules(ignore_patterns)

        repo = self.git_manager.get_repo()

        # 发现变更文件
        changed_files = self._discover_changed_files(repo)
        print("变更文件:", changed_files)

        # 过滤大文件和忽略文件
        filtered_files = self._filter_files(changed_files)

        if not filtered_files:
            # 如果没有变更文件，返回当前 HEAD 的树哈希
            try:
                return repo.head.commit.tree.hexsha
            except ValueError:
                # 如果还没有提交，创建一个空的树
                return self._create_empty_tree(repo)

        print("变更文件:", filtered_files)

        # 暂存变更文件
        self._stage_files(repo, filtered_files)

        # 写入 Git 树
        tree_hash = self.git_manager._run_git_command("write-tree").strip()

        # 创建提交来引用树对象
        if tree_hash:
            try:
                # 尝试创建提交
                commit_message = f"Snapshot at {datetime.now().isoformat()}"
                commit_hash = self.git_manager._run_git_command(
                    "commit-tree", tree_hash, "-m", commit_message
                ).strip()

                # 更新引用
                self.git_manager._run_git_command(
                    "update-ref", "refs/heads/snapshot", commit_hash
                )
            except git.GitCommandError:
                # 如果创建提交失败，仍然返回树哈希
                pass

        # 重置暂存区
        self.git_manager._run_git_command("reset", "--mixed")

        return tree_hash

    def _discover_changed_files(self, repo) -> List[str]:
        """发现变更文件"""
        changed_files = []

        # 获取已跟踪文件的变更
        try:
            diff_files = self.git_manager._run_git_command(
                "diff-files", "--name-only", "-z", "--", "."
            ).strip()
            if diff_files:
                changed_files.extend(diff_files.split("\x00"))
        except git.GitCommandError:
            pass

        # 获取未跟踪文件
        try:
            untracked_files = self.git_manager._run_git_command(
                "ls-files", "--others", "--exclude-standard", "-z", "--", "."
            ).strip()
            if untracked_files:
                changed_files.extend(untracked_files.split("\x00"))
        except git.GitCommandError:
            pass

        return changed_files

    def _filter_files(self, file_paths: List[str]) -> List[str]:
        """过滤文件"""
        filtered_files = []

        for file_path in file_paths:
            # 检查是否被忽略
            if self.git_manager.is_ignored(file_path):
                continue

            # 检查文件大小
            full_path = self.workspace_path / file_path
            if full_path.is_file():
                try:
                    file_size = full_path.stat().st_size
                    # 跳过大于 2MB 的文件
                    if file_size > 2 * 1024 * 1024:  # 2MB
                        continue
                except (OSError, FileNotFoundError):
                    continue

            filtered_files.append(file_path)

        return filtered_files

    def _stage_files(self, repo, file_paths: List[str]) -> None:
        """暂存文件"""
        if not file_paths:
            return

        # 创建临时文件列表
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            for file_path in file_paths:
                if file_path:  # 确保不是空字符串
                    f.write(f"{file_path}\n")
            temp_file = f.name

        try:
            # 检查临时文件是否为空
            if os.path.getsize(temp_file) > 0:
                # 使用临时文件进行稀疏添加
                self.git_manager._run_git_command(
                    "add", "--all", "--sparse", f"--pathspec-from-file={temp_file}"
                )
        finally:
            # 清理临时文件
            os.unlink(temp_file)

    def _create_empty_tree(self, repo) -> str:
        """创建空的 Git 树"""
        return "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
