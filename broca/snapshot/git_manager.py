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
import threading
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
    _FLOCK_FALLBACK_ERRNOS = frozenset(
        {
            errno.ENOTSUP,  # Operation not supported (常见于 NFS)
            errno.EOPNOTSUPP,  # Operation not supported on socket
            errno.EINVAL,  # Invalid argument (常见于 SMB 挂载)
            errno.ENOSYS,  # Function not implemented
        }
    )

    def __init__(self, path: str):
        self._path = Path(path)
        self._fd: Optional[int] = None
        self._count: int = 0
        # Sticky 设计：一旦进入 fallback 模式，不再回退到 flock。
        # 原因：NFS 等文件系统不支持 flock 是永久性限制，同一锁文件
        # 始终在同一文件系统上，flock 不可用则永远不可用。
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
                msvcrt.locking(  # type: ignore[attr-defined]
                    fd, msvcrt.LK_NBLCK if not blocking else msvcrt.LK_LOCK, 1  # type: ignore[attr-defined]
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
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
        except OSError:
            pass


class GitManager:
    """Git 仓库管理器（每个 workspace 只有一个实例）

    线程安全：_class_lock 保护 _instances 字典的并发访问；
    每个实例有 _instance_lock 防止并发初始化。
    """

    _instances: dict[str, "GitManager"] = {}
    _class_lock = threading.Lock()

    def __new__(cls, workspace_path: str):
        normalized = str(Path(workspace_path).resolve())
        with cls._class_lock:
            if normalized not in cls._instances:
                instance = super().__new__(cls)
                instance._initialized = False  # type: ignore[has-type]
                instance._instance_lock = threading.Lock()  # type: ignore[has-type]
                cls._instances[normalized] = instance
        return cls._instances[normalized]

    def __init__(self, workspace_path: str):
        if getattr(self, "_initialized", False):
            return
        with self._instance_lock:  # type: ignore[attr-defined]
            if self._initialized:  # type: ignore[attr-defined]  # double-check
                return
            self._initialized = True  # type: ignore[attr-defined]
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

        from broca.configs import get_configs
        snapshot_home = get_configs().snapshot_home or os.path.expanduser("~/.broca/snapshots")
        repo_dir = Path(snapshot_home) / workspace_hash

        return repo_dir

    def initialize(self) -> None:
        """初始化 Git 仓库"""
        # 创建目录
        self.repo_path.mkdir(parents=True, exist_ok=True)

        # 记录 workspace 路径（供 GC 使用）
        workspace_file = self.repo_path / ".workspace"
        if not workspace_file.exists():
            workspace_file.write_text(str(self.workspace_path), encoding="utf-8")

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
            # 关闭非 ASCII 文件名转义，保证中文文件名原样输出
            config.set_value("core", "quotepath", "false")

    def ensure_initialized(self) -> None:
        """确保 Git 仓库已初始化"""
        if not self.repo:
            self.initialize()

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
        # 从单例缓存中移除自身，防止已清理的实例被后续复用
        with type(self)._class_lock:
            normalized = str(self.workspace_path)
            type(self)._instances.pop(normalized, None)

    @classmethod
    def reset(cls, workspace_path: str) -> None:
        """显式清除指定 workspace 的 GitManager 单例。"""
        normalized = str(Path(workspace_path).resolve())
        with cls._class_lock:
            cls._instances.pop(normalized, None)

    def get_repo(self) -> git.Repo:
        """获取 Git 仓库实例"""
        self.ensure_initialized()
        assert self.repo is not None
        return self.repo

    def sync_ignore_rules(self, ignore_patterns: Optional[list[str]] = None) -> None:
        """
        同步忽略规则

        Args:
            ignore_patterns: 额外的忽略模式列表
        """
        self.ensure_initialized()
        assert self.repo is not None

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

    async def _run_git_command_no_lock(
        self, *args, input_data: Optional[bytes] = None, **kwargs
    ) -> str:
        """
        执行Git命令（不获取锁），设置正确的环境变量

        Args:
            *args: Git命令参数
            input_data: 通过 stdin 传给命令的数据（可选）
            **kwargs: 额外参数

        Returns:
            命令输出（stdout）

        Raises:
            git.GitCommandError: 命令返回非零退出码
        """
        # 设置环境变量
        env = os.environ.copy()
        env["GIT_DIR"] = str(self.repo_path / ".git")
        env["GIT_WORK_TREE"] = str(self.workspace_path)

        # 使用 create_subprocess_exec 替代 create_subprocess_shell，
        # 避免 shell 注入风险（文件名含 $、; 等特殊字符时安全）。
        # 注入 -c core.quotepath=false，确保非 ASCII（中文）文件名不被转义。
        # 兜底场景：仓库配置缺失或被外部修改时依然生效。
        process = await asyncio.create_subprocess_exec(
            "git", "-c", "core.quotepath=false", *args,
            cwd=str(self.workspace_path),
            env=env,
            stdin=asyncio.subprocess.PIPE if input_data is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **kwargs,
        )

        stdout, stderr = await process.communicate(input=input_data)

        if process.returncode != 0:
            cmd_display = " ".join(["git", "-c", "core.quotepath=false"] + [str(a) for a in args])
            raise git.GitCommandError(cmd_display, process.returncode, stderr.decode())

        return stdout.decode()

    async def is_ignored(self, file_path: str) -> bool:
        """
        检查文件是否被忽略

        Args:
            file_path: 文件路径

        Returns:
            是否被忽略
        """
        result = await self.is_ignored_batch([file_path])
        return file_path in result

    async def is_ignored_batch(self, file_paths: list[str]) -> set[str]:
        """
        批量检查文件是否被忽略（使用 git check-ignore -z --no-index --stdin）

        通过 stdin 传递路径，避免 shell 转义问题，且只需一次子进程调用。
        --no-index：纯模式匹配，不受索引中已跟踪状态影响。

        Args:
            file_paths: 文件路径列表（相对于工作区根目录）

        Returns:
            被忽略的文件路径集合
        """
        if not file_paths:
            return set()

        self.ensure_initialized()

        # NUL 分隔输入，避免路径中含空格/特殊字符的问题
        input_data = "\x00".join(file_paths).encode("utf-8") + b"\x00"

        try:
            result = await self._run_git_command_no_lock(
                "check-ignore", "-z", "--no-index", "--stdin",
                input_data=input_data,
            )
        except git.GitCommandError:
            # exit 1 = 没有文件被忽略
            return set()

        ignored = set()
        for item in result.split("\x00"):
            if item:
                ignored.add(item)
        return ignored

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


# ---------------------------------------------------------------------------
# GC: 清理孤儿 snapshot 目录
# ---------------------------------------------------------------------------


def _default_delete(repo_dir: Path, workspace_path: str | None = None) -> None:
    """使用 FileLock 保护的默认删除函数"""
    lock = FileLock(str(repo_dir / ".snapshot.lock"))
    lock.acquire(blocking=True)
    try:
        shutil.rmtree(repo_dir, ignore_errors=True)
    finally:
        lock.release()
    # 清理 GitManager 单例缓存，防止已删除 workspace 的实例残留
    if workspace_path:
        GitManager.reset(workspace_path)


def _resolve_valid_hashes(valid_workspace_hashes: set[str] | None) -> set[str]:
    """
    解析合法 workspace hash 集合。

    优先使用调用方传入的值；为 None 时尝试从 DB 查询；
    DB 不可用时返回空集合（仅通道 A 生效）。
    """
    if valid_workspace_hashes is not None:
        return valid_workspace_hashes

    try:
        import asyncio

        async def _query():
            from broca.session.database import db_manager
            from broca.session.models import Session
            from sqlmodel import select

            async with db_manager.get_session() as db_session:
                stmt = select(Session.workspace).where(
                    Session.workspace.isnot(None)
                ).distinct()
                result = await db_session.exec(stmt)
                workspaces: list[str] = result.all()

            return {
                hashlib.sha256(str(Path(w).resolve()).encode()).hexdigest()[:16]
                for w in workspaces
            }

        return asyncio.run(_query())
    except Exception as e:
        logger.warning(f"gc_snapshots: 无法查询 DB workspace 列表: {e}")
        return set()


def gc_snapshots(
    snapshot_home: str | None = None,
    *,
    dry_run: bool = False,
    delete_fn=None,
    valid_workspace_hashes: set[str] | None = None,
) -> list[dict]:
    """
    扫描 snapshot 目录，检测并（可选）删除孤儿 snapshot 目录。

    双通道检测：
    - 通道 A: 存在 .workspace 元数据文件 → 检查 workspace 路径是否存在
    - 通道 B: 无 .workspace 文件 → 用目录名（hash）对比 DB 中的 workspace 集合

    Args:
        snapshot_home: snapshot 根目录，默认从配置读取
        dry_run: True 时只收集不删除
        delete_fn: 自定义删除函数 (repo_dir: Path) -> None，
                   默认使用 FileLock + shutil.rmtree
        valid_workspace_hashes: 合法 workspace hash 集合（通道 B 使用）。
                   为 None 时自动从 DB 查询。

    Returns:
        孤儿列表，每项:
        {"name": "abc123", "workspace": "/path/to/ws" | None, "reason": "workspace_deleted" | "no_session"}
    """
    home = Path(
        snapshot_home
        or __import__("broca.configs", fromlist=["get_configs"]).get_configs().snapshot_home
        or os.path.expanduser("~/.broca/snapshots")
    )
    if not home.exists():
        return []

    if delete_fn is None:
        delete_fn = _default_delete

    valid_hashes = _resolve_valid_hashes(valid_workspace_hashes)

    orphans: list[dict] = []
    for repo_dir in sorted(home.iterdir()):
        if not repo_dir.is_dir():
            continue

        # 通道 A: .workspace 元数据
        ws_file = repo_dir / ".workspace"
        if ws_file.exists():
            try:
                ws_path = Path(ws_file.read_text(encoding="utf-8").strip())
            except OSError:
                ws_path = None

            if ws_path is None or not ws_path.exists():
                orphans.append({
                    "name": repo_dir.name,
                    "workspace": str(ws_path) if ws_path else None,
                    "reason": "workspace_deleted",
                })
                if not dry_run:
                    _do_delete(repo_dir, delete_fn, orphans, str(ws_path) if ws_path else None)
            continue

        # 通道 B: hash 对比 DB
        if repo_dir.name not in valid_hashes:
            orphans.append({
                "name": repo_dir.name,
                "workspace": None,
                "reason": "no_session",
            })
            if not dry_run:
                _do_delete(repo_dir, delete_fn, orphans)

    return orphans


def _do_delete(repo_dir: Path, delete_fn, orphans: list[dict], workspace_path: str | None = None) -> None:
    """执行删除，单项失败不阻塞后续"""
    try:
        if delete_fn is _default_delete:
            delete_fn(repo_dir, workspace_path)
        else:
            delete_fn(repo_dir)
        logger.info(f"Snapshot GC: removed {repo_dir}")
    except Exception as e:
        logger.warning(f"Snapshot GC: failed to remove {repo_dir}: {e}")
        orphans[-1]["error"] = str(e)
