"""
Patch 计算模块

计算两个快照之间的差异，生成 patch 信息。
"""

from typing import Dict, List, Optional

import git

from .git_manager import GitManager


class PatchCalculator:
    """Patch 计算器"""

    def __init__(self, workspace_path: str):
        """
        初始化 Patch 计算器

        Args:
            workspace_path: 工作空间路径
        """
        self.workspace_path = workspace_path
        self.git_manager = GitManager(workspace_path)

    def calculate_patch(
        self, from_hash: str, to_hash: Optional[str] = None
    ) -> Dict[str, any]:
        """
        计算两个快照之间的 patch

        Args:
            from_hash: 起始快照的 Git 树哈希
            to_hash: 结束快照的 Git 树哈希，如果为 None 则使用当前暂存区

        Returns:
            patch 信息字典
        """
        self.git_manager.ensure_initialized()

        # 获取变更文件列表
        changed_files = self._get_changed_files(from_hash, to_hash)

        return {
            "snapshot_hash": from_hash,
            "files": changed_files,
        }

    def _get_changed_files(
        self, from_hash: str, to_hash: Optional[str] = None
    ) -> List[str]:
        """获取变更文件列表"""
        try:
            if to_hash:
                # 比较两个树对象，使用树对象语法
                result = self.git_manager._run_git_command(
                    "diff-tree",
                    "--no-commit-id",
                    "--name-only",
                    "-r",
                    from_hash,
                    to_hash,
                ).strip()
            else:
                # 比较树对象和当前工作区
                # 首先将树对象写入索引
                self.git_manager._run_git_command("read-tree", from_hash)
                # 然后比较索引和工作区
                result = self.git_manager._run_git_command(
                    "diff", "--name-only", "HEAD", "--", "."
                ).strip()
                # 重置索引
                self.git_manager._run_git_command("reset", "--mixed")

            if result:
                return [f.strip() for f in result.split("\n") if f.strip()]
            return []
        except git.GitCommandError as e:
            # 如果 from_hash 不存在（可能是空树），返回空列表
            if "bad object" in str(e) and from_hash:
                # 尝试检查 from_hash 是否为空树
                try:
                    self.git_manager._run_git_command("cat-file", "-t", from_hash)
                    # 如果成功，说明对象存在但不是树
                    return []
                except git.GitCommandError:
                    # 对象不存在，返回空列表
                    return []
            raise

    def calculate_diff(self, from_hash: str, to_hash: Optional[str] = None) -> str:
        """
        计算两个快照之间的差异（unified diff 格式）

        Args:
            from_hash: 起始快照的 Git 树哈希
            to_hash: 结束快照的 Git 树哈希，如果为 None 则使用当前暂存区

        Returns:
            unified diff 格式的差异
        """
        self.git_manager.ensure_initialized()

        try:
            if to_hash:
                # 比较两个树对象
                return self.git_manager._run_git_command(
                    "diff-tree", "--no-commit-id", "-p", "-U3", from_hash, to_hash
                )
            else:
                # 比较树对象和当前工作区
                # 首先将树对象写入索引
                self.git_manager._run_git_command("read-tree", from_hash)
                # 然后比较索引和工作区
                diff = self.git_manager._run_git_command(
                    "diff", "-U3", "HEAD", "--", "."
                )
                # 重置索引
                self.git_manager._run_git_command("reset", "--mixed")
                return diff
        except git.GitCommandError as e:
            # 如果 from_hash 不存在，返回空差异
            if "bad object" in str(e) and from_hash:
                try:
                    self.git_manager._run_git_command("cat-file", "-t", from_hash)
                    # 对象存在但不是树
                    return ""
                except git.GitCommandError:
                    # 对象不存在
                    return ""
            raise

    def get_diff_summary(self, diff_content: str) -> Dict[str, any]:
        """
        获取差异统计信息

        Args:
            diff_content: unified diff 内容

        Returns:
            差异统计信息
        """
        if not diff_content:
            return {
                "total_files": 0,
                "total_additions": 0,
                "total_deletions": 0,
                "files_added": [],
                "files_deleted": [],
                "files_modified": [],
            }

        lines = diff_content.split("\n")
        files_added = []
        files_deleted = []
        files_modified = []
        total_additions = 0
        total_deletions = 0

        current_file = None
        file_mode = None  # 'A', 'D', 'M'

        for line in lines:
            if line.startswith("diff --git"):
                # 新文件开始
                parts = line.split()
                if len(parts) >= 3:
                    # 提取文件名，格式为 "a/path/to/file" 或 "b/path/to/file"
                    file_a = parts[2][2:]  # 去掉 "a/"
                    file_b = parts[3][2:] if len(parts) > 3 else ""  # 去掉 "b/"

                    if file_a == "/dev/null":
                        # 新文件
                        current_file = file_b
                        files_added.append(current_file)
                    elif file_b == "/dev/null":
                        # 删除文件
                        current_file = file_a
                        files_deleted.append(current_file)
                    else:
                        # 修改文件
                        current_file = file_a
                        if current_file not in files_modified:
                            files_modified.append(current_file)

            elif line.startswith("+") and not line.startswith("+++"):
                total_additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                total_deletions += 1

        return {
            "total_files": len(files_added) + len(files_deleted) + len(files_modified),
            "total_additions": total_additions,
            "total_deletions": total_deletions,
            "files_added": files_added,
            "files_deleted": files_deleted,
            "files_modified": files_modified,
        }
