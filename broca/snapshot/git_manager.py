"""
Git 仓库管理模块

管理独立的 Git 仓库，用于存储文件系统快照。
与用户项目 git 完全隔离，位于 ~/.local/share/broca/snapshot/ 目录下。
"""

import hashlib
import os
import shutil
from pathlib import Path
from typing import Optional

import git


class GitManager:
    """Git 仓库管理器"""

    def __init__(self, workspace_path: str):
        """
        初始化 Git 管理器

        Args:
            workspace_path: 工作空间路径
        """
        self.workspace_path = Path(workspace_path).resolve()
        self.repo_path = self._get_repo_path()
        self.repo: Optional[git.Repo] = None

    def _get_repo_path(self) -> Path:
        """
        获取 Git 仓库路径

        Returns:
            Git 仓库路径
        """
        # 计算工作空间哈希
        workspace_str = str(self.workspace_path)
        workspace_hash = hashlib.sha256(workspace_str.encode()).hexdigest()[:16]

        # XDG 数据目录
        xdg_data_home = os.environ.get(
            "XDG_DATA_HOME", os.path.expanduser("~/.local/share")
        )
        repo_dir = Path(xdg_data_home) / "broca" / "snapshot" / workspace_hash

        return repo_dir

    def initialize(self) -> None:
        """初始化 Git 仓库"""
        # 创建目录
        self.repo_path.mkdir(parents=True, exist_ok=True)

        # 初始化 Git 仓库
        try:
            self.repo = git.Repo.init(self.repo_path)
        except git.exc.InvalidGitRepositoryError:
            self.repo = git.Repo(self.repo_path)

        # 配置 Git
        self._configure_git()

        # 设置工作树（通过环境变量）
        custom_env = {
            "GIT_WORK_TREE": str(self.workspace_path),
            "GIT_DIR": str(self.repo.git_dir),
        }
        self.repo.git.custom_environment(**custom_env)

    def _configure_git(self) -> None:
        """配置 Git 仓库"""
        if not self.repo:
            return

        # 设置 Git 配置
        with self.repo.config_writer() as config:
            config.set_value("core", "autocrlf", "false")
            config.set_value("core", "longpaths", "true")
            config.set_value("core", "symlinks", "true")
            config.set_value("core", "fsmonitor", "false")
            config.set_value("core", "sparseCheckout", "true")

    def ensure_initialized(self) -> None:
        """确保 Git 仓库已初始化"""
        if not self.repo_path.exists():
            self.initialize()
        elif not self.repo:
            self.repo = git.Repo(self.repo_path)

    def cleanup(self) -> None:
        """清理 Git 仓库"""
        if self.repo_path.exists():
            shutil.rmtree(self.repo_path)

    def get_repo(self) -> git.Repo:
        """获取 Git 仓库实例"""
        self.ensure_initialized()
        return self.repo

    def sync_ignore_rules(self, ignore_patterns: Optional[list[str]] = None) -> None:
        """
        同步忽略规则

        Args:
            ignore_patterns: 额外的忽略模式列表
        """
        self.ensure_initialized()

        # 获取 exclude 文件路径
        exclude_file = Path(
            self.repo.git.rev_parse(
                "--path-format=absolute", "--git-path", "info/exclude"
            )
        )

        # 确保目录存在
        exclude_file.parent.mkdir(parents=True, exist_ok=True)

        # 读取项目 .gitignore
        project_gitignore = self.workspace_path / ".gitignore"
        ignore_content = []

        if project_gitignore.exists():
            with open(project_gitignore, "r", encoding="utf-8") as f:
                ignore_content.extend(f.read().splitlines())

        # 添加默认忽略规则
        default_ignores = [
            ".git/",
            ".broca-snapshot/",
            "node_modules/",
            "__pycache__/",
            "*.pyc",
            "*.pyo",
            "*.pyd",
            ".Python",
            "*.so",
            "*.dylib",
            "*.egg-info/",
            ".eggs/",
            ".tox/",
            ".coverage",
            ".cache",
            ".pytest_cache/",
            ".mypy_cache/",
            ".ruff_cache/",
            ".venv",
            "venv/",
            "env/",
            ".env",
            ".env.local",
            ".env.*.local",
            "*.log",
            "*.sqlite",
            "*.db",
            "*.sqlite3",
        ]

        ignore_content.extend(default_ignores)

        # 添加额外的忽略模式
        if ignore_patterns:
            ignore_content.extend(ignore_patterns)

        # 写入 exclude 文件
        with open(exclude_file, "w", encoding="utf-8") as f:
            f.write("\n".join(ignore_content))

    def _run_git_command(self, *args, **kwargs) -> str:
        """
        执行Git命令，设置正确的环境变量

        Args:
            *args: Git命令参数
            **kwargs: 额外参数

        Returns:
            命令输出
        """
        import subprocess

        # 设置环境变量
        env = os.environ.copy()
        env["GIT_DIR"] = str(self.repo_path / ".git")
        env["GIT_WORK_TREE"] = str(self.workspace_path)

        # 构建命令
        cmd = ["git"] + list(args)

        # 执行命令
        result = subprocess.run(
            cmd,
            cwd=str(self.workspace_path),
            env=env,
            capture_output=True,
            text=True,
            **kwargs,
        )

        if result.returncode != 0:
            raise git.GitCommandError(cmd, result.returncode, result.stderr)

        return result.stdout

    def is_ignored(self, file_path: str) -> bool:
        """
        检查文件是否被忽略

        Args:
            file_path: 文件路径

        Returns:
            是否被忽略
        """
        self.ensure_initialized()

        try:
            result = self._run_git_command("check-ignore", file_path)
            return result.strip() != ""
        except git.GitCommandError:
            # 如果命令失败，说明文件不被忽略
            return False
