"""
快照捕获模块

捕获文件系统快照，生成 Git 树哈希。

跨进程安全：
  所有 Git 操作通过 GitManager 的文件锁保护，确保多进程并发访问安全。
"""

import os
from pathlib import Path
from typing import List, Optional

import git

from broca.logging_config import get_logger
from broca.snapshot.git_manager import GitManager

logger = get_logger(__name__)


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

    async def track(self, ignore_patterns: Optional[list[str]] = None) -> str:
        """
        捕获快照

        将当前工作区的变更写入 Git 树对象，返回树哈希。
        如果没有变更，返回当前 HEAD 的树哈希（或空树哈希）。

        Args:
            ignore_patterns: 额外的忽略模式列表

        Returns:
            Git 树哈希
        """
        return await self._track_snapshot(ignore_patterns)

    async def _track_snapshot(self, ignore_patterns: Optional[list[str]] = None) -> str:
        """实际执行快照捕获（在文件锁保护下原子执行）"""
        self.git_manager.ensure_initialized()

        self.git_manager.acquire_lock(blocking=True)
        try:
            # 同步忽略规则
            self.git_manager.sync_ignore_rules(ignore_patterns)

            # 发现变更文件
            changed_files = await self._discover_changed_files()

            # 过滤大文件和忽略文件
            filtered_files = await self._filter_files(changed_files)

            logger.info("变更文件:" + ",".join(filtered_files)[:200] + "...")

            if not filtered_files:
                # 没有变更，返回当前 HEAD 的 tree hash
                logger.info("无变更，返回当前 HEAD 的 tree hash")
                return await self._get_head_tree_hash()

            # 移除忽略文件
            ignored_files = set(changed_files) - set(filtered_files)
            if ignored_files:
                logger.debug("忽略文件:" + ",".join(ignored_files))
                await self.git_manager.remove_cached_files(list(ignored_files))

            # 暂存变更文件
            if not await self._stage_files(filtered_files):
                logger.info("无法稀疏添加变更文件，跳过提交")
                return await self._get_head_tree_hash()

            # 写入 Git 树
            tree_hash = (await self.git_manager._run_git_command("write-tree")).strip()

            if tree_hash:
                # 将新 tree hash 写入 HEAD，为下一次变更检测做准备
                # 用 commit-tree 创建临时 commit，再用 reset --mixed 更新 HEAD
                commit_hash = (
                    await self.git_manager._run_git_command(
                        "commit-tree", tree_hash, "-m", "snapshot"
                    )
                ).strip()
                await self.git_manager._run_git_command("reset", "--mixed", commit_hash)
                logger.info(f"快照成功: {tree_hash}")
            else:
                logger.warning("write-tree 返回空哈希")
                tree_hash = await self._get_head_tree_hash()

            return tree_hash
        except git.GitCommandError as e:
            logger.error(f"捕获快照失败: {e}")
            raise
        finally:
            self.git_manager.release_lock()

    async def _get_head_tree_hash(self) -> str:
        """获取当前 HEAD 的 tree hash，没有 commit 时返回空树哈希"""
        try:
            repo = self.git_manager.get_repo()
            return repo.head.commit.tree.hexsha
        except ValueError:
            # 如果还没有提交，创建一个空的树
            return "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

    async def _discover_changed_files(self) -> List[str]:
        """发现变更文件"""
        changed_files = []

        # 获取已跟踪文件的变更
        try:
            diff_files = (
                await self.git_manager._run_git_command(
                    "diff-files", "--name-only", "-z", "--", "."
                )
            ).strip()
            if diff_files:
                changed_files.extend(f for f in diff_files.split("\x00") if f)
        except git.GitCommandError:
            pass

        # 获取未跟踪文件
        try:
            untracked_files = (
                await self.git_manager._run_git_command(
                    "ls-files", "--others", "--exclude-standard", "-z", "--", "."
                )
            ).strip()
            if untracked_files:
                changed_files.extend(f for f in untracked_files.split("\x00") if f)
        except git.GitCommandError:
            pass

        return changed_files

    async def _filter_files(self, file_paths: List[str]) -> List[str]:
        """过滤文件"""
        filtered_files = []

        for file_path in file_paths:
            # 检查是否被忽略
            if await self.git_manager.is_ignored(file_path):
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

    async def _stage_files(self, file_paths: List[str]) -> bool:
        """暂存文件"""
        if not file_paths:
            return False

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
                # 使用临时文件进行添加
                await self.git_manager._run_git_command(
                    "add", "--all", f"--pathspec-from-file={temp_file}"
                )
                return True
            else:
                logger.info("临时文件为空，跳过稀疏添加")
                return False
        except git.GitCommandError as e:
            logger.error(f"稀疏添加失败: {e}")
            return False
        finally:
            # 清理临时文件
            os.unlink(temp_file)
