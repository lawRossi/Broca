"""用户命令执行环境构建工具。

``build_user_env()`` 在 runner 子进程执行用户命令（bash 工具 /
ProcessManager / Scheduler）前重建"干净"的环境：

1. **剥离** runner 内部标记变量（``PYTHONSAFEPATH``、``BROCA_RUNNER_CHILD``、
   ``LITELLM_LOCAL_MODEL_COST_MAP``）和全部 ``_BROCA_ORIG_*`` 前缀变量。
2. **恢复** supervisor 进程原始值（从 ``_BROCA_ORIG_PYTHONPATH``、
   ``_BROCA_ORIG_VIRTUAL_ENV``、``_BROCA_ORIG_VIRTUAL_ENV_PROMPT`` 还原）。
3. **适配** workspace venv：若存在有效 venv（``.venv`` / ``venv`` / ``env``
   等），将其 bin 目录加入 ``PATH`` 首位并设置 ``VIRTUAL_ENV``。

``_BROCA_ORIG_*`` 跨进程契约
-----------------------------
``build_runner_env()``（launcher.py）在修改 supervisor 环境变量之前保存原始值::

    _BROCA_ORIG_PYTHONPATH          ← 原始 PYTHONPATH（仅当原值非空时）
    _BROCA_ORIG_VIRTUAL_ENV         ← 原始 VIRTUAL_ENV（仅当原值存在时）
    _BROCA_ORIG_VIRTUAL_ENV_PROMPT  ← 原始 VIRTUAL_ENV_PROMPT（仅当原值存在时）

``build_user_env()`` 在构造用户命令 env 时消费并 pop 掉这些变量，
确保用户命令子进程看不到内部标记。

Known limitations
-----------------
1. **Supervisor 自身 PYTHONPATH 污染**：supervisor 进程（``broca service``
   CLI）自身的 ``PYTHONPATH`` 不受此模块管理。若用户在 ``~/.broca`` 外的
   shell 环境中手动设置了 ``PYTHONPATH``，supervisor 启动时即已携带该值，
   ``build_runner_env`` 会保存它，``build_user_env`` 会如实还原。
2. **无 venv 时 PATH 残留服务 venv**：当 workspace 无有效 venv 时，
   ``PATH`` 仍包含 runner 服务 venv 的 ``bin/`` 目录（来自 supervisor
   环境），此时 ``python`` 命令会解析到服务 venv 的 python 而非系统 python。
   这是预期行为——服务 venv 提供了 broca 运行时依赖，用户命令通常需要它。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from broca.logging_config import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Runner 内部标记变量 — 需要从用户命令环境中剥离
# ---------------------------------------------------------------------------
_RUNNER_INTERNAL_VARS: tuple[str, ...] = (
    "PYTHONSAFEPATH",
    "BROCA_RUNNER_CHILD",
    "LITELLM_LOCAL_MODEL_COST_MAP",
)

_BROCA_ORIG_PREFIX = "_BROCA_ORIG_"

# venv 候选目录名（公共 API，agent_manager 等模块可复用）
VENV_CANDIDATES: tuple[str, ...] = (
    ".venv",
    "venv",
    "env",
    ".env",
    "virtualenv",
)

# 向后兼容：旧私有名保留为别名
_VENV_CANDIDATES = VENV_CANDIDATES


def _venv_bin_dir(venv_root: Path, platform: str = "posix") -> Path:
    """返回 venv 中 bin/Scripts 目录路径。"""
    if platform == "nt":
        return venv_root / "Scripts"
    return venv_root / "bin"


def validate_venv_dir(venv_dir: Path, platform: str = "posix") -> bool:
    """检查 venv 目录是否有效（含 python 可执行文件）。

    校验优先级：
    - posix: ``bin/python`` → ``bin/python3``
    - nt:    ``Scripts/python.exe``

    Args:
        venv_dir: venv 根目录。
        platform: ``"posix"`` 或 ``"nt"``，默认 posix。
    """
    if platform == "nt":
        return (venv_dir / "Scripts" / "python.exe").exists()

    return (venv_dir / "bin" / "python").exists() or (
        venv_dir / "bin" / "python3"
    ).exists()


# 向后兼容：旧私有名
_validate_venv_dir = validate_venv_dir


def find_workspace_venv(workspace: str) -> Optional[Path]:
    """在 workspace 中查找第一个有效的 Python venv 目录。

    按优先级检查候选目录：``.venv`` → ``venv`` → ``env`` → ``.env``
    → ``virtualenv``。校验 ``bin/python``（posix）或 ``Scripts/python.exe``
    （nt）存在。

    Args:
        workspace: workspace 根目录路径。若为相对路径或空，自动转为绝对路径。

    Returns:
        venv 根目录 Path，未找到返回 None。
    """
    ws = Path(workspace) if workspace else Path.cwd()
    ws = Path(os.path.abspath(str(ws)))

    if not ws.is_dir():
        return None

    platform = "nt" if sys.platform == "win32" else "posix"

    for name in VENV_CANDIDATES:
        venv_dir = ws / name
        if venv_dir.is_dir() and validate_venv_dir(venv_dir, platform):
            return venv_dir

    return None


def _filter_broca_service_paths(pythonpath: str) -> str:
    """从 PYTHONPATH 中移除 ``~/.broca/`` 前缀的服务内部路径。

    supervisor（web backend / CLI）的 PYTHONPATH 常指向 ``~/.broca/web/backend``
    等服务内部目录，这些路径对用户命令无意义且可能意外导入服务模块。
    用户自定义的其他路径正常保留。
    """
    home = os.path.expanduser("~")
    broca_prefixes = (
        os.path.join(home, ".broca") + os.path.sep,
    )
    entries = [p for p in pythonpath.split(os.pathsep) if p]
    filtered = [p for p in entries if not any(p.startswith(pf) for pf in broca_prefixes)]
    return os.pathsep.join(filtered) if filtered else ""


def _strip_and_restore(env: dict[str, str]) -> dict[str, str]:
    """剥离 runner 内部变量，从 ``_BROCA_ORIG_*`` 恢复 supervisor 原始值。

    操作顺序：
    1. 剥离 4 个 runner 内部标记变量
    2. 恢复 PYTHONPATH（从 ``_BROCA_ORIG_PYTHONPATH``，过滤 ``~/.broca/`` 路径）
    3. 恢复 VIRTUAL_ENV / VIRTUAL_ENV_PROMPT（从 ``_BROCA_ORIG_*``）
    4. pop 掉所有 ``_BROCA_ORIG_*`` 前缀变量
    """
    # -- 1. 剥离 runner 内部标记 --
    for var in _RUNNER_INTERNAL_VARS:
        env.pop(var, None)

    # -- 2. 恢复 PYTHONPATH（过滤 ~/.broca/ 服务内部路径） --
    orig_pythonpath = env.get("_BROCA_ORIG_PYTHONPATH")
    if orig_pythonpath is not None:
        filtered = _filter_broca_service_paths(orig_pythonpath)
        if filtered:
            env["PYTHONPATH"] = filtered
        else:
            env.pop("PYTHONPATH", None)
    else:
        env.pop("PYTHONPATH", None)

    # -- 3. 恢复 VIRTUAL_ENV / VIRTUAL_ENV_PROMPT --
    orig_ve = env.get("_BROCA_ORIG_VIRTUAL_ENV")
    if orig_ve is not None:
        env["VIRTUAL_ENV"] = orig_ve
    else:
        env.pop("VIRTUAL_ENV", None)

    orig_vep = env.get("_BROCA_ORIG_VIRTUAL_ENV_PROMPT")
    if orig_vep is not None:
        env["VIRTUAL_ENV_PROMPT"] = orig_vep
    else:
        env.pop("VIRTUAL_ENV_PROMPT", None)

    # -- 4. pop 掉所有 _BROCA_ORIG_* 前缀变量 --
    for key in list(env):
        if key.startswith(_BROCA_ORIG_PREFIX):
            env.pop(key, None)

    return env


def build_user_env(workspace: str | None = None) -> dict[str, str]:
    """构建用户命令执行的干净环境变量。

    三层逻辑：
    1. 剥离 runner 内部标记 + ``_BROCA_ORIG_*``
    2. 从 ``_BROCA_ORIG_*`` 恢复 supervisor 进程原始 PYTHONPATH/VIRTUAL_ENV
    3. 若 workspace 存在有效 venv，PATH 前置 venv/bin 并设置 VIRTUAL_ENV

    **调用约束**：本函数设计用于 **runner 子进程**内部调用。
    在 supervisor 进程中调用会剥离该进程自身的 ``VIRTUAL_ENV``/
    ``PYTHONPATH``（无 ``_BROCA_ORIG_*`` 时一律 pop），
    导致 supervisor 后续操作丢失环境。

    Args:
        workspace: workspace 根目录（绝对路径）。None 时使用 ``os.getcwd()``
            （runner 进程的 cwd 即 workspace）。

    Returns:
        干净的环境变量字典，可直接传给 ``create_subprocess_shell(env=...)``。

    Raises:
        无。内部异常均被捕获并 log warning，始终返回可用的 env 字典。
    """
    try:
        ws = os.path.abspath(workspace) if workspace else os.getcwd()
    except (TypeError, ValueError) as e:
        logger.warning(f"build_user_env: workspace 路径无效 ({type(e).__name__}: {e})，回退到 cwd")
        ws = os.getcwd()

    env = os.environ.copy()

    # 层 1 + 2：剥离 + 恢复（纯字典操作，不会抛异常）
    try:
        _strip_and_restore(env)
    except Exception as e:
        logger.warning(f"build_user_env: strip/restore 失败（使用原始 env）: {e}")

    # 层 3：workspace venv 适配
    try:
        venv_dir = find_workspace_venv(ws)
        if venv_dir is not None:
            _apply_workspace_venv(env, venv_dir)
    except Exception as e:
        logger.warning(
            f"build_user_env: workspace venv 适配失败（已跳过）: {e}"
        )

    return env


def _apply_workspace_venv(env: dict[str, str], venv_dir: Path) -> None:
    """将 workspace venv 的 bin 目录加入 PATH 首位并设置 VIRTUAL_ENV。"""
    platform = "nt" if sys.platform == "win32" else "posix"
    venv_bin = os.path.normpath(str(_venv_bin_dir(venv_dir, platform)))

    # PATH 前置（去重：normpath 归一化后比较，避免尾斜杠/symlink 变体重复）
    existing_path = env.get("PATH", "")
    path_entries = [p for p in existing_path.split(os.pathsep) if p]
    normalized_existing = [os.path.normpath(p) for p in path_entries]
    if venv_bin not in normalized_existing:
        env["PATH"] = venv_bin + (os.pathsep + existing_path if existing_path else "")

    # VIRTUAL_ENV（第 3 层优先级高于第 2 层：workspace venv 覆盖服务进程 venv）
    env["VIRTUAL_ENV"] = str(venv_dir)
    env["VIRTUAL_ENV_PROMPT"] = venv_dir.name
