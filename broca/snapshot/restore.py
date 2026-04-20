"""
快照恢复模块

将工作空间恢复到指定的快照状态。
"""

import shutil
from pathlib import Path

import git

from broca.logging_config import get_logger
from .git_manager import GitManager

logger = get_logger(__name__)


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

    def restore_file(self, tree_hash: str, file_path: str) -> None:
        """
        恢复单个文件到指定的快照状态

        Args:
            tree_hash: Git 树哈希
            file_path: 文件路径（相对路径）
        """
        self.git_manager.ensure_initialized()

        try:
            self.git_manager._run_git_command("checkout", tree_hash, "--", file_path)
        except git.GitCommandError:
            logger.info(f"文件检出失败：{file_path}")
            # 判断文件是否存在，使用ls-tree命令
            try:
                result = self.git_manager._run_git_command(
                    "ls-tree", "-r", "--name-only", tree_hash, file_path
                )
                if result.strip() == "":
                    logger.info(f"文件不存在：{file_path}")
                    full_path = self.workspace_path / file_path
                    if full_path.exists():
                        if full_path.is_file():
                            full_path.unlink()
                        elif full_path.is_dir():
                            shutil.rmtree(full_path)
            except git.GitCommandError as e:
                logger.error(f"文件检出失败{file_path}：{e}")

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
