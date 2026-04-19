"""
快照恢复模块

将工作空间恢复到指定的快照状态。
"""

import os
import shutil
from pathlib import Path

import git

from .git_manager import GitManager


class SnapshotRestorer:
    """快照恢复器"""

    def __init__(self, workspace_path: str):
        """
        初始化快照恢复器

        Args:
            workspace_path: 工作空间路径
        """
        self.workspace_path = Path(workspace_path).resolve()
        self.git_manager = GitManager(str(self.workspace_path))

    def restore(self, tree_hash: str) -> None:
        """
        恢复到指定的快照

        Args:
            tree_hash: Git 树哈希
        """
        self.git_manager.ensure_initialized()

        # 读取树对象到索引
        self.git_manager._run_git_command("read-tree", tree_hash)

        # 检出索引到工作区
        self.git_manager._run_git_command("checkout-index", "-a", "-f")

        # 清理未跟踪的文件（在快照中不存在的文件）
        self._cleanup_untracked_files(tree_hash)

    def restore_file(self, tree_hash: str, file_path: str) -> None:
        """
        恢复单个文件到指定的快照状态

        Args:
            tree_hash: Git 树哈希
            file_path: 文件路径（相对路径）
        """
        self.git_manager.ensure_initialized()

        try:
            # 尝试从树中检出文件
            self.git_manager._run_git_command("checkout", tree_hash, "--", file_path)
        except git.GitCommandError as e:
            # 如果文件在快照中不存在，删除它
            if "did not match any file(s) known to git" in str(e):
                full_path = self.workspace_path / file_path
                if full_path.exists():
                    if full_path.is_file():
                        full_path.unlink()
                    elif full_path.is_dir():
                        shutil.rmtree(full_path)
            else:
                raise

    def _cleanup_untracked_files(self, tree_hash: str) -> None:
        """清理未跟踪的文件"""
        # 获取快照中的所有文件
        try:
            tree_files_result = self.git_manager._run_git_command(
                "ls-tree", "-r", "--name-only", tree_hash
            )
            tree_files = set(tree_files_result.splitlines())
        except git.GitCommandError:
            # 如果树哈希无效，使用空集合
            tree_files = set()

        # 获取当前工作区的所有文件
        workspace_files = set()
        for root, dirs, files in os.walk(self.workspace_path):
            # 跳过 .git 目录
            if ".git" in dirs:
                dirs.remove(".git")

            for file in files:
                rel_path = Path(root).relative_to(self.workspace_path) / file
                workspace_files.add(str(rel_path))

        # 删除在快照中不存在的文件
        files_to_delete = workspace_files - tree_files

        for file_path in files_to_delete:
            full_path = self.workspace_path / file_path
            if full_path.exists():
                try:
                    if full_path.is_file():
                        full_path.unlink()
                    elif full_path.is_dir():
                        shutil.rmtree(full_path)
                except (OSError, PermissionError):
                    # 忽略删除失败的文件
                    pass

    def get_tree_files(self, tree_hash: str) -> list[str]:
        """
        获取快照中的所有文件列表

        Args:
            tree_hash: Git 树哈希

        Returns:
            文件路径列表
        """
        self.git_manager.ensure_initialized()

        try:
            result = self.git_manager._run_git_command(
                "ls-tree", "-r", "--name-only", tree_hash
            )
            if result:
                return [f.strip() for f in result.splitlines() if f.strip()]
            return []
        except git.GitCommandError:
            # 如果树哈希无效，返回空列表
            return []