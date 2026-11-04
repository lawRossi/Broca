"""Runner 子进程真实启动集成测试（P0-2 / P0-3）

用真实子进程验证「workspace 含空格」的完整链路：
起一个真实 ``IPCServer`` → 用 ``build_runner_argv`` 生成的 argv 以
``cwd=<含空格的 workspace>`` 启动真实子进程 → 断言子进程成功连上 IPC，
且 stderr 中不出现 argparse 报错。

这替代了原计划里的「手工跑一次含空格路径」。

通过 ``BROCA_RUN_INTEGRATION=1`` 启用，默认 skip（CI 中设置该环境变量）。
不需要 LLM / DB 数据：子进程在 IPC 连上之后才会去恢复 Agent。
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import subprocess
import sys
import uuid

import pytest

from broca.session_runner.ipc import IPCServer
from broca.session_runner.manager import (
    build_runner_argv,
    build_runner_env,
    platform_popen_kwargs,
)

pytestmark = pytest.mark.integration

_INTEGRATION_ENABLED = os.environ.get("BROCA_RUN_INTEGRATION") == "1"


@pytest.mark.skipif(
    not _INTEGRATION_ENABLED, reason="set BROCA_RUN_INTEGRATION=1 to run"
)
def test_session_lifecycle_with_spaced_workspace(tmp_path: pathlib.Path) -> None:
    """含空格 workspace 下子进程必须能正常启动并连上 IPC。"""
    workspace = tmp_path / "My Project" / "demo"
    workspace.mkdir(parents=True)

    session_id = f"itest-{uuid.uuid4().hex[:8]}"
    log_file = tmp_path / "runner.log"

    server = IPCServer(session_id)
    asyncio.run(server.start())
    proc: subprocess.Popen | None = None

    try:
        argv = build_runner_argv(
            session_id=session_id,
            workspace=str(workspace),
            log_file=str(log_file),
        )
        proc = subprocess.Popen(
            argv,
            cwd=str(workspace),
            env=build_runner_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            **platform_popen_kwargs(),
        )

        # 子进程必须在 60s 内连上 IPC（首包为 EVT_READY 或 EVT_ERROR）
        assert server.accept(timeout=60.0) is True

        try:
            proc.wait(timeout=60.0)
        except subprocess.TimeoutExpired:  # pragma: no cover - 卡死时兜底
            proc.kill()
            raise

        stdout, stderr = proc.communicate(timeout=30.0)
    finally:
        if proc is not None and proc.poll() is None:  # pragma: no cover
            proc.kill()
            proc.communicate(timeout=30.0)
        server.close()

    combined = f"{stdout or ''}\n{stderr or ''}"
    assert "IPC client connected" in combined, (
        f"子进程未成功连接 IPC（含空格 workspace 启动失败）\n"
        f"argv={argv}\ncwd={workspace}\n--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}"
    )
    assert "unrecognized arguments" not in combined, combined
    assert "No such file or directory" not in combined, combined
    assert "No module named" not in combined, combined
