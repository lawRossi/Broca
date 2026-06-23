"""
Git 仓库管理模块

管理独立的 Git 仓库，用于存储文件系统快照。
与用户项目 git 完全隔离，位于 ~/.broca/snapshots/ 目录下。

跨进程安全：
  所有 Git 操作通过文件锁保护，确保多进程并发访问安全。
  锁文件位于 Git 仓库目录下的 .snapshot.lock。
  跨平台支持：Unix 使用 fcntl.flock（含网络文件系统 fallback），Windows 使用 msvcrt.locking。
"""

import asyncio
import errno
import hashlib
import os
import shutil
import time
from pathlib import Path
from typing import Optional

import git

from broca.logging_config import get_logger

logger = get_logger(__name__)


class FileLock:
    """跨平台文件锁

    使用策略模式根据平台选择底层锁实现：
    - Unix (Linux/macOS): fcntl.flock，如果文件系统不支持 flock（如 NFS、SMB），
      自动 fallback 到基于 O_EXCL 的 PID 文件锁。
    - Windows: msvcrt.locking
    """

    # flock() 在这些 errno 下说明文件系统不支持，需要 fallback
    _FLOCK_FALLBACK_ERRNOS = frozenset({
        errno.ENOTSUP,    # Operation not supported (常见于 NFS)
        errno.EOPNOTSUPP, # Operation not supported on socket
        errno.EINVAL,     # Invalid argument (常见于 SMB 挂载)
        errno.ENOSYS,     # Function not implemented
    })

    def __init__(self, path: str):
        self._path = Path(path)
        self._fd: Optional[int] = None
        self._count: int = 0
        self._fallback_mode: bool = False  # True 时使用 O_EXCL PID 文件锁

    @property
    def is_held(self) -> bool:
        return self._fd is not None

    def acquire(self, blocking: bool = True) -> bool:
        """获取文件锁（支持重入）"""
        if self._fd is not None:
            self._count += 1
            return True

        self._path.parent.mkdir(parents=True, exist_ok=True)

        if self._fallback_mode:
            return self._fallback_acquire(blocking)

        fd = os.open(str(self._path), os.O_RDWR | os.O_CREAT)
        try:
            self._platform_acquire(fd, blocking)
            self._fd = fd
            self._count = 1
            return True
        except OSError as e:
            os.close(fd)
            # 如果是因为文件系统不支持 flock，切换到 fallback 模式
            if e.errno in self._FLOCK_FALLBACK_ERRNOS:
                logger.warning(
                    f"flock() 不被当前文件系统支持 (errno={e.errno}), "
                    f"切换到 PID 文件锁 fallback 模式"
                )
                self._fallback_mode = True
                return self._fallback_acquire(blocking)
            return False

    def release(self) -> None:
        """释放文件锁（支持重入）"""
        if self._fd is None:
            return
        self._count -= 1
        if self._count > 0:
            return

        if self._fallback_mode:
            self._fallback_release()
        else:
            try:
                self._platform_release(self._fd)
            except OSError:
                pass

        os.close(self._fd)
        self._fd = None
        self._count = 0

    # ---- Fallback：基于 O_EXCL 的 PID 文件锁 ----

    def _fallback_acquire(self, blocking: bool = True) -> bool:
        """
        基于 O_EXCL 的 PID 文件锁 fallback

        适用于 flock() 不可用的文件系统（NFS、SMB 等）。
        通过原子创建 PID 文件来模拟互斥锁，附带僵死锁检测。
        """
        lock_path = self._path.with_suffix(self._path.suffix + ".pidlock")
        while True:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.write(fd, f"{os.getpid()}\n".encode())
                self._fd = fd
                self._fallback_mode = True
                self._count = 1
                return True
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise
                if not blocking:
                    return False
                # 检查是否为僵死锁（持有锁的进程已退出）
                self._clean_stale_lock(lock_path)
                time.sleep(0.05)

    def _fallback_release(self) -> None:
        """释放 PID 文件锁"""
        lock_path = self._path.with_suffix(self._path.suffix + ".pidlock")
        try:
            os.unlink(lock_path)
        except OSError:
            pass

    @staticmethod
    def _clean_stale_lock(lock_path: Path) -> None:
        """
        检测并清理僵死锁

        读取 PID 文件中的进程号，如果该进程已不存在则删除锁文件。
        """
        try:
            content = lock_path.read_text().strip()
            if content:
                pid = int(content)
                try:
                    os.kill(pid, 0)  # 发送空信号检测进程是否存在
                except OSError:
                    # 进程不存在，僵死锁，清理
                    logger.warning(f"清理僵死 PID 文件锁 (pid={pid}): {lock_path}")
                    lock_path.unlink(missing_ok=True)
        except (ValueError, OSError, FileNotFoundError):
            pass

    # ---- 平台相关实现 ----

    @staticmethod
    def _platform_acquire(fd: int, blocking: bool) -> None:
        """根据平台获取文件锁"""
        import sys

        if sys.platform == "win32":
            FileLock._win32_acquire(fd, blocking)
        else:
            FileLock._unix_acquire(fd, blocking)

    @staticmethod
    def _platform_release(fd: int) -> None:
        """根据平台释放文件锁"""
        import sys

        if sys.platform == "win32":
            FileLock._win32_release(fd)
        else:
            FileLock._unix_release(fd)

    @staticmethod
    def _unix_acquire(fd: int, blocking: bool) -> None:
        import fcntl

        flags = fcntl.LOCK_EX
        if not blocking:
            flags |= fcntl.LOCK_NB
        fcntl.flock(fd, flags)

    @staticmethod
    def _unix_release(fd: int) -> None:
        import fcntl

        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass

    @staticmethod
    def _win32_acquire(fd: int, blocking: bool) -> None:
        import msvcrt

        while True:
            try:
                msvcrt.locking(
                    fd, msvcrt.LK_NBLCK if not blocking else msvcrt.LK_LOCK, 1
                )
                return
            except OSError as e:
                if not blocking:
                    raise BlockingIOError from e
                time.sleep(0.01)

    @staticmethod
    def _win32_release(fd: int) -> None:
        import msvcrt

        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass


class GitManager:
    """Git 仓库管理器（每个 workspace 只有一个实例）"""

    _instances: dict[str, "GitManager"] = {}

    def __new__(cls, workspace_path: str):
        normalized = str(Path(workspace_path).resolve())
        if normalized not in cls._instances:
            instance = super().__new__(cls)
            instance._initialized = False
            cls._instances[normalized] = instance
        return cls._instances[normalized]

    def __init__(self, workspace_path: str):
        if self._initialized:
            return
        self._initialized = True
        self.workspace_path = Path(workspace_path).resolve()
        self.repo_path = self._get_repo_path()
        self.repo: Optional[git.Repo] = None
        self._file_lock: Optional[FileLock] = None

    @property
    def _lock(self) -> FileLock:
        """获取或创建文件锁实例"""
        if self._file_lock is None:
            self._file_lock = FileLock(str(self.repo_path / ".snapshot.lock"))
        return self._file_lock

    def _get_repo_path(self) -> Path:
        """
        获取 Git 仓库路径

        Returns:
            Git 仓库路径
        """
        # 计算工作空间哈希
        workspace_str = str(self.workspace_path)
        workspace_hash = hashlib.sha256(workspace_str.encode()).hexdigest()[:16]

        snapshot_home = os.environ.get(
            "BROCA_SNAPSHOT_HOME", os.path.expanduser("~/.broca/snapshots")
        )
        repo_dir = Path(snapshot_home) / workspace_hash

        return repo_dir

    def initialize(self) -> None:
        """初始化 Git 仓库"""
        self._lock.acquire(blocking=True)
        try:
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
        finally:
            self._lock.release()

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

    def ensure_initialized(self) -> None:
        """确保 Git 仓库已初始化"""
        if not self.repo_path.exists():
            self.initialize()
        elif not self.repo:
            self._lock.acquire(blocking=True)
            try:
                self.repo = git.Repo(self.repo_path)
            finally:
                self._lock.release()

    def acquire_lock(self, blocking: bool = True) -> bool:
        """
        获取文件锁（跨进程安全，跨平台，支持重入）

        委托给 FileLock 实现，根据平台选择底层锁机制：
        - Unix (Linux/macOS): fcntl.flock
        - Windows: msvcrt.locking

        Args:
            blocking: 是否阻塞等待锁。

        Returns:
            是否成功获取锁。
        """
        return self._lock.acquire(blocking=blocking)

    def release_lock(self) -> None:
        """释放文件锁（支持重入）"""
        self._lock.release()

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

        self._lock.acquire(blocking=True)
        try:
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
                ".broca/",
            ]

            ignore_content.extend(default_ignores)

            # 添加额外的忽略模式
            if ignore_patterns:
                ignore_content.extend(ignore_patterns)

            # 写入 exclude 文件
            with open(exclude_file, "w", encoding="utf-8") as f:
                f.write("\n".join(ignore_content))
        finally:
            self._lock.release()

    async def _run_git_command(self, *args, **kwargs) -> str:
        """
        执行Git命令，设置正确的环境变量

        自动获取文件锁保护 Git 操作，确保跨进程安全。
        如果外部已持锁（通过 acquire_lock），则不再重复加锁，避免重入开销。

        Args:
            *args: Git命令参数
            **kwargs: 额外参数

        Returns:
            命令输出
        """
        already_locked = self._lock.is_held
        if not already_locked:
            self._lock.acquire(blocking=True)
        try:
            return await self._run_git_command_no_lock(*args, **kwargs)
        finally:
            if not already_locked:
                self._lock.release()

    async def _run_git_command_no_lock(self, *args, **kwargs) -> str:
        """
        执行Git命令（不获取锁），设置正确的环境变量

        Args:
            *args: Git命令参数
            **kwargs: 额外参数

        Returns:
            命令输出
        """
        # 设置环境变量
        env = os.environ.copy()
        env["GIT_DIR"] = str(self.repo_path / ".git")
        env["GIT_WORK_TREE"] = str(self.workspace_path)

        # 构建命令字符串
        cmd_str = "git " + " ".join(args)

        # 执行命令
        process = await asyncio.create_subprocess_shell(
            cmd_str,
            cwd=str(self.workspace_path),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **kwargs,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise git.GitCommandError(cmd_str, process.returncode, stderr.decode())

        return stdout.decode()

    async def is_ignored(self, file_path: str) -> bool:
        """
        检查文件是否被忽略

        Args:
            file_path: 文件路径

        Returns:
            是否被忽略
        """
        self.ensure_initialized()

        try:
            result = await self._run_git_command("check-ignore", file_path)
            return result.strip() != ""
        except git.GitCommandError:
            # 如果命令失败，说明文件不被忽略
            return False

    async def get_tree_files(self, tree_hash: str) -> list[str]:
        """
        获取快照中的所有文件列表

        Args:
            tree_hash: Git 树哈希

        Returns:
            文件路径列表
        """
        self.ensure_initialized()

        try:
            result = await self._run_git_command(
                "ls-tree", "-r", "--name-only", tree_hash
            )
            if result:
                return [f.strip() for f in result.splitlines() if f.strip()]
            return []
        except git.GitCommandError:
            # 如果树哈希无效，返回空列表
            return []

    async def remove_cached_files(self, files: list[str]) -> None:
        """
        移除缓存文件

        Args:
            files: 文件路径列表
        """
        if not files:
            return

        self.ensure_initialized()

        # git rm --cached -f --ignore-unmatch
        try:
            await self._run_git_command(
                "rm",
                "--cached",
                "-f",
                "--ignore-unmatch",
                *files,
            )
        except git.GitCommandError as e:
            logger.error(f"Failed to remove cached files: {e}")
