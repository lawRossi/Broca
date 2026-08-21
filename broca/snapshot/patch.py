"""
Patch 计算模块

计算两个快照之间的差异，生成 patch 信息。
"""

from typing import Any, Dict, List, Optional

import re

import git

from .git_manager import GitManager

# 匹配 git 输出中的路径 token：带引号的 C 转义路径 或 普通 token
_GIT_PATH_TOKEN_RE = re.compile(r'"(?:[^"\\]|\\.)*"|\S+')


def _unquote_git_path(path: str) -> str:
    """还原 git 输出中被引号包裹的转义路径。

    git 默认 (core.quotepath=true) 会把非 ASCII 文件名输出为
    "a/\\344\\270\\255\\346\\226\\207.txt" 形式，此函数将其还原为原始 UTF-8 路径。
    """
    if not (len(path) >= 2 and path.startswith('"') and path.endswith('"')):
        return path
    body = path[1:-1]
    out = bytearray()
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt in ("\\", '"'):
                out.extend(nxt.encode("utf-8"))
                i += 2
                continue
            if nxt == "t":
                out.append(0x09)
                i += 2
                continue
            if nxt == "n":
                out.append(0x0A)
                i += 2
                continue
            m = re.match(r"[0-7]{1,3}", body[i + 1 :])
            if m:
                out.append(int(m.group(0), 8))
                i += 1 + len(m.group(0))
                continue
        out.extend(ch.encode("utf-8"))
        i += 1
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError:
        return out.decode("utf-8", errors="replace")


def _strip_diff_prefix(path: str) -> str:
    """去掉 diff 路径的 a/ 或 b/ 前缀（仅一层），/dev/null 原样返回。"""
    if path in ("/dev/null", "dev/null"):
        return path
    if path[:2] in ("a/", "b/"):
        return path[2:]
    return path


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

    async def calculate_patch(
        self, from_hash: str, to_hash: Optional[str] = None
    ) -> Dict[str, Any]:
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
        changed_files = await self._get_changed_files(from_hash, to_hash)

        return {
            "snapshot_hash": from_hash,
            "files": changed_files,
        }

    async def _get_changed_files(
        self, from_hash: str, to_hash: Optional[str] = None
    ) -> List[str]:
        """获取变更文件列表（在文件锁保护下原子执行）"""
        self.git_manager.acquire_lock(blocking=True)
        try:
            if to_hash:
                # 比较两个树对象，使用树对象语法
                result = (
                    await self.git_manager._run_git_command(
                        "diff-tree",
                        "--no-commit-id",
                        "--name-only",
                        "-r",
                        from_hash,
                        to_hash,
                    )
                ).strip()
            else:
                # 比较树对象和当前工作区
                # 首先将树对象写入索引
                await self.git_manager._run_git_command("read-tree", from_hash)
                # 然后比较索引和工作区
                result = (
                    await self.git_manager._run_git_command(
                        "diff", "--name-only", "HEAD", "--", "."
                    )
                ).strip()
                # 重置索引
                await self.git_manager._run_git_command("reset", "--mixed")

            if result:
                return [f.strip() for f in result.split("\n") if f.strip()]
            return []
        except git.GitCommandError as e:
            # 如果 from_hash 不存在（可能是空树），返回空列表
            if "bad object" in str(e) and from_hash:
                # 尝试检查 from_hash 是否为空树
                try:
                    await self.git_manager._run_git_command("cat-file", "-t", from_hash)
                    # 如果成功，说明对象存在但不是树
                    return []
                except git.GitCommandError:
                    # 对象不存在，返回空列表
                    return []
            raise
        finally:
            self.git_manager.release_lock()

    async def calculate_diff(
        self,
        from_hash: str,
        to_hash: str,
        file_path: Optional[str] = None,
    ) -> str:
        """
        计算两个快照之间的差异（unified diff 格式）

        Args:
            from_hash: 起始快照的 Git 树哈希
            to_hash: 结束快照的 Git 树哈希，如果为 None 则使用当前暂存区
            file_path: 可选的过滤路径，只返回指定文件的 diff

        Returns:
            unified diff 格式的差异
        """
        self.git_manager.ensure_initialized()

        try:
            # 比较两个树对象
            cmd = ["diff-tree", "--no-commit-id", "-r", "-p", "-U3", from_hash, to_hash]
            if file_path:
                cmd.extend(["--", file_path])
            return await self.git_manager._run_git_command(*cmd)
        except git.GitCommandError as e:
            raise e

    def get_diff_summary(self, diff_content: str) -> Dict[str, Any]:
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

        for line in lines:
            if line.startswith("diff --git"):
                # 新文件开始。路径可能含空格或被引号包裹（非 ASCII 文件名），
                # 用 token 正则提取而非简单 split
                tokens = _GIT_PATH_TOKEN_RE.findall(line[len("diff --git ") :])
                if len(tokens) >= 2:
                    # 提取文件名，格式为 "a/path/to/file" 或 "b/path/to/file"
                    file_a = _strip_diff_prefix(_unquote_git_path(tokens[0]))
                    file_b = _strip_diff_prefix(_unquote_git_path(tokens[1]))

                    # 暂存文件名，等看到 new/deleted file mode 行再确定类型
                    current_file = (
                        file_a
                        if file_a != "/dev/null" and file_a != "dev/null"
                        else file_b
                    )

            elif line.startswith("new file mode"):
                # 新增文件
                if current_file and current_file not in files_added:
                    files_added.append(current_file)

            elif line.startswith("deleted file mode"):
                # 删除文件
                if current_file and current_file not in files_deleted:
                    files_deleted.append(current_file)

            elif line.startswith("--- ") and not line.startswith("--- /dev/null"):
                # 修改文件（没有 new/deleted file mode 标记）。
                # 注意：非 ASCII 路径会被引号包裹（--- "a/中文.txt"），
                # 因此只检查 "--- " 前缀而非 "--- a/"
                if (
                    current_file
                    and current_file not in files_added
                    and current_file not in files_deleted
                    and current_file not in files_modified
                ):
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
