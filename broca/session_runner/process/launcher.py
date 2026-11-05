"""Runner 子进程启动。

argv 契约（唯一来源，``broca/tests/test_runner_launcher.py`` 长期守卫）::

    --session-id / --workspace / --log-file / --log-level / --config

必须与 ``broca.session_runner.runner.parse_args`` 逐项一致。

设计要点：
- **argv 列表** 而非 shell 字符串：workspace 含空格时不会参数错位，
  也不存在命令注入面；
- **``sys.executable``** 而非裸 ``"python"``：保证子进程跑在当前 venv；
- **``start_new_session=True``** 而非 ``preexec_fn=os.setsid``：多线程进程里
  ``preexec_fn`` 有文档化的死锁风险；
- **``PYTHONPATH`` 首位必须是仓库根**：``Popen(cwd=workspace)`` 下
  ``-m broca.session_runner.runner`` 会优先命中 site-packages 里的旧副本。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional
from broca.logging_config import get_logger

logger = get_logger(__name__)

RUNNER_MODULE = "broca.session_runner.runner"


def repo_root() -> Path:
    """仓库根目录（broca/session_runner/process/launcher.py → 上溯四层）。"""
    return Path(__file__).resolve().parents[3]


def build_runner_argv(
    session_id: str,
    workspace: Optional[str] = None,
    log_file: Optional[str] = None,
    config_path: Optional[str] = None,
    log_level: str = "INFO",
) -> list[str]:
    """构造 runner 子进程的 argv（列表形式，绝不拼接字符串）。"""
    argv = [sys.executable, "-m", RUNNER_MODULE, "--session-id", session_id]
    if workspace:
        argv += ["--workspace", workspace]
    if log_file:
        argv += ["--log-file", log_file]
    argv += ["--log-level", log_level]
    if config_path:
        argv += ["--config", config_path]
    return argv


def build_runner_env() -> dict[str, str]:
    """构造子进程环境变量（仓库根置于 ``PYTHONPATH`` 首位）。"""
    env = os.environ.copy()
    root = str(repo_root())
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = root + (os.pathsep + existing if existing else "")
    # 使用 sys.executable 启动后无需污染 VIRTUAL_ENV
    env.pop("VIRTUAL_ENV", None)
    env.pop("VIRTUAL_ENV_PROMPT", None)
    # 标识 runner 子进程：logging_config.get_logger() 据此自动切换为
    # stdlib 后端（而非 loguru），确保 per-session 日志文件隔离。
    env["BROCA_RUNNER_CHILD"] = "1"
    # 跳过 litellm 远程 model cost map 拉取（避免 5s SSL 超时）
    env["LITELLM_LOCAL_MODEL_COST_MAP"] = "true"
    # 防止 cwd (workspace) 被加入 sys.path[0]：
    # python -m 默认把 cwd 放在 sys.path 首位，若 workspace 恰好包含
    # 同名包（如仓库根目录的 broca/），会遮蔽 site-packages 里的代码。
    env["PYTHONSAFEPATH"] = "1"
    return env


def platform_popen_kwargs() -> dict[str, Any]:
    """平台相关的 Popen 参数。"""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


class RunnerLauncher:
    """Runner 子进程启动器。"""

    def spawn(
        self,
        session_id: str,
        workspace: Optional[str] = None,
        log_file: Optional[str] = None,
        config_path: Optional[str] = None,
        log_level: str = "INFO",
    ) -> subprocess.Popen:
        """启动 runner 子进程并返回 ``Popen``。"""
        argv = build_runner_argv(
            session_id=session_id,
            workspace=workspace,
            log_file=log_file,
            config_path=config_path,
            log_level=log_level,
        )
        env = build_runner_env()

        logger.info(f"Starting runner for session {session_id}: {argv!r}")

        # stdout/stderr → DEVNULL:
        # - 避免子进程 stderr 污染 supervisor 的 backend.err.log
        # - 子进程日志通过 init_logging() 配置的 TimedRotatingFileHandler
        #   写入 per-session 的 runner.log 文件（即使 log_file=None 也有
        #   StreamHandler(stderr) 兜底，日志不会丢失）
        return subprocess.Popen(
            argv,
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            cwd=workspace,
            **platform_popen_kwargs(),
        )
