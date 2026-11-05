"""Runner 子进程启动。

argv 契约（唯一来源，``broca/tests/test_runner_launcher.py`` 长期守卫）::

    --session-id / --workspace / --log-file / --log-level / --config

必须与 ``broca.session_runner.runner.parse_args`` 逐项一致。

``_BROCA_ORIG_*`` 环境变量契约
------------------------------
``build_runner_env()`` 在修改 supervisor 环境变量之前保存原始值，供
``broca.utils.env.build_user_env()`` 在用户命令执行前恢复::

    _BROCA_ORIG_PYTHONPATH          ← 原始 PYTHONPATH（仅当原值非空时写入）
    _BROCA_ORIG_VIRTUAL_ENV         ← 原始 VIRTUAL_ENV（仅当原值存在时写入）
    _BROCA_ORIG_VIRTUAL_ENV_PROMPT  ← 原始 VIRTUAL_ENV_PROMPT（仅当原值存在时写入）

runner 进程的 ``os.environ`` 保留这些变量（不 pop），
``build_user_env()`` 在构造用户命令 env 时消费并 pop 掉。

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
    """构造子进程环境变量（仓库根置于 ``PYTHONPATH`` 首位）。

    修改环境变量前，将 supervisor 进程原始值保存为 ``_BROCA_ORIG_*``，
    供 ``broca.utils.env.build_user_env()`` 在用户命令执行前恢复。
    """
    env = os.environ.copy()
    root = str(repo_root())

    # ── 保存 PYTHONPATH 原始值（仅在非空时保存，避免空值泄漏） ──
    orig_pythonpath = env.get("PYTHONPATH", "")
    if orig_pythonpath:
        env["_BROCA_ORIG_PYTHONPATH"] = orig_pythonpath
    existing = orig_pythonpath
    env["PYTHONPATH"] = root + (os.pathsep + existing if existing else "")

    # 使用 sys.executable 启动后无需污染 VIRTUAL_ENV
    # 先保存原始值，供 build_user_env() 恢复到用户命令环境
    orig_ve = env.get("VIRTUAL_ENV")
    if orig_ve:
        env["_BROCA_ORIG_VIRTUAL_ENV"] = orig_ve
    env.pop("VIRTUAL_ENV", None)

    orig_vep = env.get("VIRTUAL_ENV_PROMPT")
    if orig_vep:
        env["_BROCA_ORIG_VIRTUAL_ENV_PROMPT"] = orig_vep
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
