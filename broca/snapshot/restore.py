"""
快照恢复模块

将工作空间恢复到指定的快照状态。
"""

import asyncio
import shutil
from pathlib import Path
from typing import Any

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

    async def restore(self, tree_hash: str) -> None:
        """
        恢复到指定的快照

        Args:
            tree_hash: Git 树哈希
        """
        self.git_manager.ensure_initialized()

        try:
            # 使用 --reset 选项先重置索引，再读取树对象
            await self.git_manager._run_git_command("read-tree", "--reset", tree_hash)

            # 检出索引到工作区
            await self.git_manager._run_git_command("checkout-index", "-a", "-f")
        except git.GitCommandError as e:
            logger.error(f"恢复快照失败: {e}")
            raise

    async def revert_patches(self, patches: list[dict[str, Any]]) -> None:
        """
        反向应用多个 patch

        Args:
            patches: patch 信息字典列表
        """
        if not patches:
            return

        file_snapshot_mapping = {}
        for patch in patches:
            snapshot_hash = patch.get("snapshot_hash")
            files = patch.get("files", [])
            if snapshot_hash and files:
                for file_path in files:
                    if file_path not in file_snapshot_mapping:
                        file_snapshot_mapping[file_path] = snapshot_hash

        for file, snapshot_hash in file_snapshot_mapping.items():
            await self.restore_file(snapshot_hash, file)

    async def restore_file(self, tree_hash: str, file_path: str) -> None:
        """
        恢复单个文件到指定的快照状态

        Args:
            tree_hash: Git 树哈希
            file_path: 文件路径（相对路径）
        """
        self.git_manager.ensure_initialized()

        try:
            await self.git_manager._run_git_command("checkout", tree_hash, "--", file_path)
        except git.GitCommandError:
            logger.info(f"文件检出失败：{file_path}")
            # 判断文件是否存在，使用ls-tree命令
            try:
                result = await self.git_manager._run_git_command(
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
