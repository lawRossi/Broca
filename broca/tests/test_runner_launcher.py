"""Runner 子进程启动参数回归测试（P0-2 + P0-3）

覆盖两个阻塞缺陷：

- P0-2：旧实现用 ``shell=True`` + 字符串拼接构造命令。workspace 含空格时
  ``--workspace My Project/demo`` 会被 shell 拆成两个参数，子进程 argparse
  报错并退出，manager 白等 15s 连接超时；同时这也是命令注入面。
- P0-3：旧实现用裸 ``"python"`` 而非 ``sys.executable``，还主动
  ``env.pop("VIRTUAL_ENV")``，导致子进程可能跑在错误的解释器/依赖上。

另外守卫 argv 契约：``build_runner_argv`` 与 ``runner.parse_args`` 必须逐项一致，
避免后续阶段「一边删了 argparse 定义、另一边还在传」的跨阶段断裂。
"""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

import pytest

from broca.session_runner import manager as manager_module
from broca.session_runner.manager import (
    IPCSessionRunner,
    RunnerManagerError,
    build_runner_argv,
    build_runner_env,
    platform_popen_kwargs,
    repo_root,
)

RUNNER_PY = pathlib.Path(__file__).resolve().parents[1] / "session_runner" / "runner.py"

SESSION_ID = "session_launcher_test"


class _PopenAbort(Exception):
    """用于在 Popen 处短路 start_session 的哨兵异常。"""


class _FakeIPCServer:
    """不占用真实 socket 的 IPC server 替身（本文件只关心 argv/env）。"""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.address = f"fake-ipc-{session_id}"
        self.family = "AF_UNIX"
        self.closed = False

    async def start(self) -> None:  # noqa: D401 - 保持与真实实现同签名
        return None

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fresh_manager(monkeypatch, tmp_path):
    """干净的 IPCSessionRunner 实例（绕过单例缓存）。"""
    IPCSessionRunner._instance = None
    mgr = IPCSessionRunner()
    mgr._registry.clear()
    # 日志目录固定到 tmp_path，避免污染 ~/.broca
    monkeypatch.setattr(
        mgr, "_get_runner_log_file", lambda sid: str(tmp_path / f"{sid}.log")
    )
    # 不占用真实 socket：本文件只验证 argv / env / Popen 参数
    monkeypatch.setattr(manager_module, "IPCServer", _FakeIPCServer)
    yield mgr
    mgr._registry.clear()


async def _capture_popen_call(mgr, workspace: str):
    """调用 start_session，在 subprocess.Popen 处短路并返回该次调用记录。"""
    popen_calls: list[dict] = []

    def _fake_popen(*args, **kwargs):
        popen_calls.append({"args": args, "kwargs": kwargs})
        raise _PopenAbort("stop here")

    original = manager_module.subprocess.Popen
    manager_module.subprocess.Popen = _fake_popen
    try:
        with pytest.raises(RunnerManagerError):
            await mgr.start_session(SESSION_ID, workspace=workspace)
    finally:
        manager_module.subprocess.Popen = original

    assert popen_calls, "subprocess.Popen 未被调用"
    return popen_calls[0]


# ---------------------------------------------------------------------------
# P0-2: workspace 含空格
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_argv_quotes_path_with_spaces(fresh_manager, tmp_path):
    """workspace 含空格时必须作为单个 argv 元素传递。"""
    workspace = str(tmp_path / "My Project" / "demo")
    pathlib.Path(workspace).mkdir(parents=True)

    call = await _capture_popen_call(fresh_manager, workspace)

    argv = call["args"][0]
    assert isinstance(argv, list), "argv 必须是列表，不能是拼接后的字符串"
    assert workspace in argv, f"workspace 未作为独立参数出现: {argv}"
    # 相邻两元素构成 --workspace <path>，path 内部不能再被拆开
    idx = argv.index("--workspace")
    assert argv[idx + 1] == workspace


# ---------------------------------------------------------------------------
# P0-3: 解释器与启动方式
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_uses_sys_executable(fresh_manager, tmp_path):
    """argv[0] 必须是当前解释器，而不是裸 'python'。"""
    workspace = str(tmp_path / "ws")
    pathlib.Path(workspace).mkdir()

    call = await _capture_popen_call(fresh_manager, workspace)

    assert call["args"][0][0] == sys.executable


@pytest.mark.asyncio
async def test_no_shell_true(fresh_manager, tmp_path):
    """Popen 不得以 shell 模式启动。"""
    workspace = str(tmp_path / "ws")
    pathlib.Path(workspace).mkdir()

    call = await _capture_popen_call(fresh_manager, workspace)

    assert call["kwargs"].get("shell") is False


@pytest.mark.asyncio
async def test_start_new_session_not_preexec_fn(fresh_manager, tmp_path):
    """必须用 start_new_session 而不是 preexec 回调（多线程进程会死锁）。"""
    workspace = str(tmp_path / "ws")
    pathlib.Path(workspace).mkdir()

    call = await _capture_popen_call(fresh_manager, workspace)

    assert "preexec_fn" not in call["kwargs"]
    if sys.platform == "win32":
        assert (
            call["kwargs"].get("creationflags")
            == subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        assert call["kwargs"].get("start_new_session") is True


# ---------------------------------------------------------------------------
# argv 契约：build_runner_argv ⇔ runner.parse_args
# ---------------------------------------------------------------------------


def _argparse_options() -> set[str]:
    """用 AST 提取 runner.parse_args 中定义的所有 ``--xxx`` 选项名。"""
    tree = ast.parse(RUNNER_PY.read_text(encoding="utf-8"))
    options: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "parse_args":
            for call in ast.walk(node):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "add_argument"
                    and call.args
                    and isinstance(call.args[0], ast.Constant)
                    and isinstance(call.args[0].value, str)
                ):
                    flag = call.args[0].value
                    if flag.startswith("--"):
                        options.add(flag)
    return options


def test_argv_matches_runner_argparse():
    """build_runner_argv 的选项集合必须与 runner.parse_args 完全一致。"""
    declared = _argparse_options()
    assert declared, "未能从 runner.parse_args 中解析出任何选项"

    argv = build_runner_argv(
        session_id="sid",
        workspace="/tmp/ws",
        log_file="/tmp/runner.log",
        config_path="/tmp/configs.json",
    )
    built = {item for item in argv if item.startswith("--")}

    assert built == declared, (
        f"argv 与 argparse 契约不一致\n"
        f"  仅 argv 有: {sorted(built - declared)}\n"
        f"  仅 argparse 有: {sorted(declared - built)}"
    )


# ---------------------------------------------------------------------------
# PYTHONPATH：必须指向仓库根（防止跑 site-packages 旧副本）
# ---------------------------------------------------------------------------


def test_pythonpath_points_to_repo_root():
    """env['PYTHONPATH'] 首项必须是仓库根，且实际 import 解析到仓库内。"""
    env = build_runner_env()
    entries = [p for p in env["PYTHONPATH"].split(manager_module.os.pathsep) if p]
    assert entries, "PYTHONPATH 为空"
    assert pathlib.Path(entries[0]).resolve() == repo_root().resolve()

    result = subprocess.run(
        [sys.executable, "-c", "import broca; print(broca.__file__)"],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    imported = pathlib.Path(result.stdout.strip()).resolve()
    assert repo_root().resolve() in imported.parents, (
        f"import broca 解析到了仓库外: {imported}"
    )


def test_platform_popen_kwargs_selects_correct_branch():
    """平台分支选择逻辑（Windows 需 CI 验证，此处只锁选择逻辑）。"""
    kwargs = platform_popen_kwargs()
    if sys.platform == "win32":
        assert "creationflags" in kwargs
    else:
        assert kwargs == {"start_new_session": True}


# ---------------------------------------------------------------------------
# PYTHONSAFEPATH：防止 cwd 污染 sys.path（回归：main/legacy 代码混用）
# ---------------------------------------------------------------------------


def test_build_runner_env_includes_pythonsafepath():
    """build_runner_env() 必须设置 PYTHONSAFEPATH=1。

    回归场景：legacy runner 用 ``cwd=workspace`` 启动子进程，Python ``-m``
    模式把 cwd 放进 ``sys.path[0]``。若 workspace 恰好是仓库根目录（含
    main 分支的 ``broca/``），``import broca`` 就命中 main 代码而非
    site-packages 的 legacy 代码 → IPC 协议不兼容 → TypeError。
    """
    env = build_runner_env()
    assert env.get("PYTHONSAFEPATH") == "1", (
        "build_runner_env() 未设置 PYTHONSAFEPATH=1，"
        "runner 子进程可能被 cwd 中的同名包劫持"
    )


def test_runner_env_prevents_cwd_broca_shadowing(tmp_path):
    """cwd 下存在同名 broca/ 目录时，runner 子进程仍应加载 PYTHONPATH 指定的包。

    模拟线上事故：workspace（= cwd）是仓库根目录，目录里有 main 分支的
    ``broca/``，而 venv site-packages 里是 legacy 代码。子进程必须加载
    ``PYTHONPATH`` 指向的仓库根，绝不能被 cwd 的 ``broca/`` 抢先。
    """
    # 构造一个"陷阱"目录：包含一个标记用的假 broca 包
    fake_ws = tmp_path / "fake_workspace"
    fake_broca = fake_ws / "broca"
    fake_broca.mkdir(parents=True)
    (fake_broca / "__init__.py").write_text(
        "SHADOWED = True  # if this is imported, cwd leaked into sys.path",
        encoding="utf-8",
    )

    env = build_runner_env()

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "\n".join([
                "import sys",
                "assert sys.path[0] not in ('', '.'), "
                "f'cwd leaked into sys.path[0]: {sys.path[0]!r}'",
                "import broca",
                "assert not hasattr(broca, 'SHADOWED'), "
                "'import broca was shadowed by cwd'",
                "import pathlib",
                "p = pathlib.Path(broca.__file__).resolve()",
                "print(p)",
            ]),
        ],
        capture_output=True,
        text=True,
        cwd=str(fake_ws),
        env=env,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, (
        f"PYTHONSAFEPATH 未生效，cwd 中的 broca/ 劫持了 import\n"
        f"stderr: {result.stderr}"
    )
    imported = pathlib.Path(result.stdout.strip()).resolve()
    assert repo_root().resolve() in imported.parents, (
        f"import broca 未解析到仓库根: {imported}"
    )


# ---------------------------------------------------------------------------
# _BROCA_ORIG_*: supervisor 原始环境变量保存
# ---------------------------------------------------------------------------


def test_broca_orig_pythonpath_saved(monkeypatch):
    """supervisor 有 PYTHONPATH 时，_BROCA_ORIG_PYTHONPATH 正确保存。"""
    monkeypatch.setenv("PYTHONPATH", "/custom/path")
    env = build_runner_env()
    assert env["_BROCA_ORIG_PYTHONPATH"] == "/custom/path"


def test_broca_orig_pythonpath_absent_when_unset(monkeypatch):
    """supervisor 无 PYTHONPATH 时，不设 _BROCA_ORIG_PYTHONPATH。"""
    monkeypatch.delenv("PYTHONPATH", raising=False)
    env = build_runner_env()
    assert "_BROCA_ORIG_PYTHONPATH" not in env


def test_broca_orig_virtual_env_saved(monkeypatch):
    """supervisor 有 VIRTUAL_ENV 时，_BROCA_ORIG_VIRTUAL_ENV 正确保存。"""
    monkeypatch.setenv("VIRTUAL_ENV", "/some/venv")
    env = build_runner_env()
    assert env["_BROCA_ORIG_VIRTUAL_ENV"] == "/some/venv"
    # VIRTUAL_ENV 本身被 pop
    assert "VIRTUAL_ENV" not in env


def test_broca_orig_virtual_env_absent(monkeypatch):
    """supervisor 无 VIRTUAL_ENV 时，不设 _BROCA_ORIG_VIRTUAL_ENV。"""
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    env = build_runner_env()
    assert "_BROCA_ORIG_VIRTUAL_ENV" not in env


def test_broca_orig_virtual_env_prompt_saved(monkeypatch):
    """supervisor 有 VIRTUAL_ENV_PROMPT 时，正确保存。"""
    monkeypatch.setenv("VIRTUAL_ENV_PROMPT", "myenv")
    env = build_runner_env()
    assert env["_BROCA_ORIG_VIRTUAL_ENV_PROMPT"] == "myenv"
    assert "VIRTUAL_ENV_PROMPT" not in env
