"""E2E 子进程验证：确认用户命令子进程的环境确实干净。

这些测试是本次修复的核心验收标准——直接验证"用户命令子进程
不再收到 PYTHONPATH=仓库根 / PYTHONSAFEPATH / BROCA_RUNNER_CHILD"，
而非仅验证 env 字典构造正确。

场景：
- A: 核心 bug — build_runner_env 污染 → build_user_env 清理 →
  子进程 PYTHONSAFEPATH 不存在 + sys.path[0] 为 ''（cwd 重新生效）
- B: venv 适配 — workspace 有 .venv → 子进程 VIRTUAL_ENV 指向 workspace venv
- C: ProcessManager 路径 — 真正调用 pm.start_process() 验证子进程 env
- D: 注入点断言 — mock create_subprocess_shell 验证 env= 参数被传递
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch as mock_patch

import pytest

from broca.session_runner.manager import build_runner_env
from broca.utils.env import build_user_env


# ---------------------------------------------------------------------------
# 场景 A: 核心 bug 验证
# ---------------------------------------------------------------------------


class TestE2ECleanEnvironment:
    """build_runner_env 污染 → build_user_env 清理 → 子进程环境干净。"""

    def test_subprocess_has_no_polluted_vars(self, monkeypatch, tmp_path):
        """子进程不再收到 PYTHONSAFEPATH / BROCA_RUNNER_CHILD，sys.path[0] 为 ''。"""
        # 1. 构造 runner 污染环境并注入 os.environ（模拟 runner 进程）
        polluted = build_runner_env()
        for key, value in polluted.items():
            monkeypatch.setenv(key, value)
        assert os.environ.get("PYTHONSAFEPATH") == "1", "前置条件：污染环境已设置"

        # 2. 用 build_user_env 构建干净 env
        clean_env = build_user_env(str(tmp_path))

        # 3. 静态验证：干净 env 不含污染变量
        assert "PYTHONSAFEPATH" not in clean_env
        assert "BROCA_RUNNER_CHILD" not in clean_env
        assert "LITELLM_LOCAL_MODEL_COST_MAP" not in clean_env
        assert not any(k.startswith("_BROCA_ORIG_") for k in clean_env)

        # 4. E2E：启动子进程，验证实际环境
        #    用 sentinel 值避免空行 strip 问题
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import os,sys;"
                "print('PS=' + os.environ.get('PYTHONSAFEPATH', 'ABSENT'));"
                "print('RC=' + os.environ.get('BROCA_RUNNER_CHILD', 'ABSENT'));"
                "print('SP0=[' + sys.path[0] + ']')",
            ],
            capture_output=True,
            text=True,
            env=clean_env,
            cwd=str(tmp_path),
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        lines = result.stdout.strip().split("\n")
        assert len(lines) == 3, f"Expected 3 lines, got {len(lines)}: {lines}"
        assert lines[0] == "PS=ABSENT", f"PYTHONSAFEPATH leaked: {lines[0]}"
        assert lines[1] == "RC=ABSENT", f"BROCA_RUNNER_CHILD leaked: {lines[1]}"
        # sys.path[0] 应为 ''（cwd 重新生效，因为 PYTHONSAFEPATH 已不存在）
        assert lines[2] == "SP0=[]", f"sys.path[0] should be '' (cwd): {lines[2]}"

    def test_pythonpath_restored(self, monkeypatch, tmp_path):
        """supervisor 原始 PYTHONPATH 被正确还原，仓库根不再污染。"""
        monkeypatch.setenv("PYTHONPATH", "/custom/original/path")
        # 模拟 build_runner_env 的效果
        polluted = build_runner_env()
        for key, value in polluted.items():
            monkeypatch.setenv(key, value)

        clean_env = build_user_env(str(tmp_path))
        assert clean_env.get("PYTHONPATH") == "/custom/original/path"

        # E2E：子进程 sys.path 应包含 /custom/original/path
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys;"
                "found = any('/custom/original/path' in p for p in sys.path);"
                "print('FOUND' if found else 'NOT_FOUND')",
            ],
            capture_output=True,
            text=True,
            env=clean_env,
            cwd=str(tmp_path),
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert "FOUND" in result.stdout


# ---------------------------------------------------------------------------
# 场景 B: venv 适配验证
# ---------------------------------------------------------------------------


class TestE2EVenvAdaptation:
    """workspace 有 .venv → 子进程 VIRTUAL_ENV / PATH 指向 workspace venv。"""

    def test_subprocess_uses_workspace_venv(self, monkeypatch, tmp_path):
        """.venv/bin/python (symlink) → 子进程 VIRTUAL_ENV 指向 workspace venv。"""
        # 创建最小 venv 结构：.venv/bin/python → 真实 python 的 symlink
        venv_bin = tmp_path / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        os.symlink(sys.executable, str(venv_bin / "python"))

        # 清除可能的污染
        monkeypatch.delenv("PYTHONPATH", raising=False)
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)

        clean_env = build_user_env(str(tmp_path))

        # 静态验证
        path_entries = clean_env["PATH"].split(os.pathsep)
        assert path_entries[0] == str(venv_bin)
        assert clean_env["VIRTUAL_ENV"] == str(tmp_path / ".venv")
        assert clean_env["VIRTUAL_ENV_PROMPT"] == ".venv"

        # E2E：子进程验证 VIRTUAL_ENV 和 PATH
        result = subprocess.run(
            [
                "python",
                "-c",
                "import os,sys;"
                "print('VE=' + os.environ.get('VIRTUAL_ENV', 'ABSENT'));"
                "print('VFP=' + os.environ.get('VIRTUAL_ENV_PROMPT', 'ABSENT'));",
            ],
            capture_output=True,
            text=True,
            env=clean_env,
            cwd=str(tmp_path),
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        lines = result.stdout.strip().split("\n")
        assert len(lines) == 2, f"Expected 2 lines, got: {lines}"
        assert f"VE={tmp_path / '.venv'}" in lines[0], f"VIRTUAL_ENV wrong: {lines[0]}"
        assert "VFP=.venv" in lines[1], f"VIRTUAL_ENV_PROMPT wrong: {lines[1]}"

    def test_no_venv_uses_fallback_python(self, monkeypatch, tmp_path):
        """workspace 无 venv → python 仍可用（服务 venv 兜底或系统 python）。"""
        monkeypatch.delenv("PYTHONPATH", raising=False)
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)

        clean_env = build_user_env(str(tmp_path))

        result = subprocess.run(
            ["python", "-c", "import sys; print('OK')"],
            capture_output=True,
            text=True,
            env=clean_env,
            cwd=str(tmp_path),
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert "OK" in result.stdout


# ---------------------------------------------------------------------------
# 场景 C: ProcessManager 路径 — 真正调用 pm.start_process()
# ---------------------------------------------------------------------------


class TestE2EProcessManager:
    """M3: 真正调用 ProcessManager.start_process() 验证子进程 env 干净。

    通过 monkeypatch OUTPUT_DIR 到 tmp_path 解决相对路径问题。
    """

    @pytest.mark.asyncio
    async def test_start_process_clean_env(self, monkeypatch, tmp_path):
        """pm.start_process() 执行的子进程不含 PYTHONSAFEPATH / BROCA_RUNNER_CHILD。"""
        from broca.process_manager import ProcessManager

        # 将 OUTPUT_DIR 指向 tmp_path 下的绝对路径，避免相对路径与 cwd 不匹配
        output_dir = tmp_path / "process_outputs"
        output_dir.mkdir()
        monkeypatch.setattr(ProcessManager, "OUTPUT_DIR", output_dir)

        # 模拟 runner 环境的污染
        monkeypatch.setenv("PYTHONSAFEPATH", "1")
        monkeypatch.setenv("BROCA_RUNNER_CHILD", "1")
        monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "true")

        pm = ProcessManager()
        cmd = (
            "python -c "
            "\"import os; "
            "print('PS=' + os.environ.get('PYTHONSAFEPATH', 'ABSENT')); "
            "print('RC=' + os.environ.get('BROCA_RUNNER_CHILD', 'ABSENT'))\""
        )
        info = await pm.start_process(cmd, cwd=str(tmp_path))

        # 等待进程结束
        await info._process.wait()

        # 读取 stdout（重定向到文件）
        stdout_content = ""
        if info.stdout_path and info.stdout_path.exists():
            stdout_content = info.stdout_path.read_text()

        lines = stdout_content.strip().split("\n")
        assert len(lines) >= 2, f"Expected 2+ lines, got: {stdout_content!r}"
        assert "PS=ABSENT" in lines[0], f"PYTHONSAFEPATH leaked: {lines[0]}"
        assert "RC=ABSENT" in lines[1], f"BROCA_RUNNER_CHILD leaked: {lines[1]}"

    @pytest.mark.asyncio
    async def test_start_process_none_cwd(self, monkeypatch, tmp_path):
        """M3: Scheduler 路径 — cwd=None → os.getcwd() → env 干净。"""
        from broca.process_manager import ProcessManager

        output_dir = tmp_path / "process_outputs2"
        output_dir.mkdir()
        monkeypatch.setattr(ProcessManager, "OUTPUT_DIR", output_dir)

        # 模拟 runner 环境的污染
        monkeypatch.setenv("PYTHONSAFEPATH", "1")
        monkeypatch.setenv("BROCA_RUNNER_CHILD", "1")

        # 切换到 workspace 目录（模拟 runner cwd = workspace）
        monkeypatch.chdir(tmp_path)

        pm = ProcessManager()
        cmd = (
            "python -c "
            "\"import os; "
            "print('PS=' + os.environ.get('PYTHONSAFEPATH', 'ABSENT'))\""
        )
        # cwd=None（Scheduler 不传 cwd）
        info = await pm.start_process(cmd)
        await info._process.wait()

        stdout_content = ""
        if info.stdout_path and info.stdout_path.exists():
            stdout_content = info.stdout_path.read_text()

        assert "PS=ABSENT" in stdout_content, (
            f"PYTHONSAFEPATH leaked via None-cwd path: {stdout_content!r}"
        )


# ---------------------------------------------------------------------------
# 场景 D: 注入点断言 — 验证 env= 参数确实被传递给 create_subprocess_shell
# ---------------------------------------------------------------------------


class TestInjectionPointAssertions:
    """M2: 验证 bash.py / process_manager.py 确实将 env= 传给 create_subprocess_shell。

    若删除 env=env 参数，以下测试将失败。
    """

    @pytest.mark.asyncio
    async def test_bash_run_code_async_passes_env(self, monkeypatch, tmp_path):
        """M2: bash._run_code_async 向 create_subprocess_shell 传递 env= 参数。

        若删除 bash.py 中的 env=env，此测试将失败。
        """
        # 构造污染环境
        monkeypatch.setenv("PYTHONSAFEPATH", "1")

        # mock create_subprocess_shell，捕获调用参数
        mock_shell = AsyncMock()
        mock_process = MagicMock()
        mock_process.wait = AsyncMock(return_value=0)
        mock_process.returncode = 0
        mock_process.pid = 12345
        mock_shell.return_value = mock_process

        with mock_patch(
            "asyncio.create_subprocess_shell",
            mock_shell,
        ):
            from broca.tools.bash import Bash

            tool = Bash()
            await tool._run_code_async("echo hi", timeout=5, workspace=str(tmp_path))

        # 断言 create_subprocess_shell 被调用且 env= 参数存在
        assert mock_shell.called, "create_subprocess_shell was not called"
        call_kwargs = mock_shell.call_args.kwargs
        assert "env" in call_kwargs, (
            "env= parameter not passed to create_subprocess_shell in bash.py"
        )
        # 断言 env 是干净的环境（不含 PYTHONSAFEPATH）
        env = call_kwargs["env"]
        assert "PYTHONSAFEPATH" not in env, "PYTHONSAFEPATH present in env passed to bash"

    @pytest.mark.asyncio
    async def test_process_manager_passes_env(self, monkeypatch, tmp_path):
        """M2: ProcessManager.start_process 向 create_subprocess_shell 传递 env= 参数。

        若删除 process_manager.py 中的 env=env，此测试将失败。
        """
        from broca.process_manager import ProcessManager

        # 将 OUTPUT_DIR 指向 tmp_path
        output_dir = tmp_path / "pm_outputs"
        output_dir.mkdir()
        monkeypatch.setattr(ProcessManager, "OUTPUT_DIR", output_dir)

        # 污染环境
        monkeypatch.setenv("PYTHONSAFEPATH", "1")

        # mock create_subprocess_shell
        mock_shell = AsyncMock()
        mock_process = MagicMock()
        mock_process.wait = AsyncMock(return_value=0)
        mock_process.returncode = 0
        mock_process.pid = 12345  # int，供 _write_meta JSON 序列化
        mock_shell.return_value = mock_process

        pm = ProcessManager()
        # mock 内部副作用方法，避免后台任务干扰
        monkeypatch.setattr(pm, "_wait_process", AsyncMock())
        monkeypatch.setattr(pm, "_write_meta", MagicMock())
        monkeypatch.setattr(pm, "_ensure_cleanup_task", MagicMock())

        with mock_patch("asyncio.create_subprocess_shell", mock_shell):
            await pm.start_process("echo hi", cwd=str(tmp_path))

        assert mock_shell.called, "create_subprocess_shell was not called"
        call_kwargs = mock_shell.call_args.kwargs
        assert "env" in call_kwargs, (
            "env= parameter not passed to create_subprocess_shell in process_manager.py"
        )
        env = call_kwargs["env"]
        assert "PYTHONSAFEPATH" not in env, (
            "PYTHONSAFEPATH present in env passed to process_manager"
        )
