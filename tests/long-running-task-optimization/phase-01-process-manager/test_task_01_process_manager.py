"""
Tests for Task 1.1: ProcessManager 类
Plan: plans/long-running-task-optimization-plan.md

AC 1: start_process("echo hello") → stdout.log 包含 "hello"
AC 2: start_process("sleep 30") → get_status() 返回 RUNNING
AC 3: 进程自然结束后 status=COMPLETED, exit_code=0
AC 4: stop_process(force=False) → SIGTERM 优雅退出
AC 5: stop_process(force=True) → SIGKILL 立即终止
AC 6: meta.json 随状态变化实时更新
AC 7: list_processes() 返回所有活跃进程
"""

import asyncio
import json
import os
import signal
import shutil
import sys
from pathlib import Path

import pytest
import pytest_asyncio

from broca.process_manager import ProcessManager, ProcessStatus


@pytest_asyncio.fixture(autouse=True)
async def reset_pm():
    """每个测试前重置 ProcessManager 状态"""
    pm = ProcessManager()
    await pm.cleanup()
    output_dir = Path(ProcessManager.OUTPUT_DIR)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    yield
    pm = ProcessManager()
    await pm.cleanup()


# ─── AC 1: start_process("echo hello") → stdout.log 包含 "hello" ─────────

@pytest.mark.asyncio
async def test_ac01_stdout_contains_hello():
    """AC 1: start_process("echo hello") → stdout.log 包含 "hello" """
    pm = ProcessManager()
    info = await pm.start_process("echo hello_from_pm")
    await asyncio.sleep(0.5)

    # 验证 stdout 文件内容
    stdout_content = Path(info.stdout_path).read_text().strip()
    assert stdout_content == "hello_from_pm", f"Expected 'hello_from_pm', got: {stdout_content}"

    # 验证进程已完成
    status = pm.get_status(info.process_id)
    assert status is not None
    assert status.status == ProcessStatus.COMPLETED


# ─── AC 2: start_process("sleep 30") → get_status() 返回 RUNNING ─────────

@pytest.mark.asyncio
async def test_ac02_long_running_is_running():
    """AC 2: start_process("sleep 30") → get_status() 返回 RUNNING"""
    pm = ProcessManager()
    info = await pm.start_process("sleep 30")

    status = pm.get_status(info.process_id)
    assert status is not None
    assert status.status == ProcessStatus.RUNNING, f"Expected RUNNING, got {status.status}"
    assert status.pid > 0, f"Expected valid PID, got {status.pid}"
    assert status.exit_code is None, f"Exit code should be None while running"

    # 清理
    await pm.stop_process(info.process_id, force=True)


# ─── AC 3: 进程自然结束后 status=COMPLETED, exit_code=0 ─────────────────

@pytest.mark.asyncio
async def test_ac03_natural_completion():
    """AC 3: 进程自然结束后 status=COMPLETED, exit_code=0"""
    pm = ProcessManager()
    info = await pm.start_process("echo done")
    await asyncio.sleep(0.5)

    status = pm.get_status(info.process_id)
    assert status is not None
    assert status.status == ProcessStatus.COMPLETED, f"Expected COMPLETED, got {status.status}"
    assert status.exit_code == 0, f"Expected exit_code=0, got {status.exit_code}"

    # 验证 stdout 内容
    stdout = Path(info.stdout_path).read_text().strip()
    assert stdout == "done"


# ─── AC 4: stop_process(force=False) → SIGTERM 优雅退出 ─────────────────

@pytest.mark.asyncio
async def test_ac04_stop_graceful_sigterm():
    """AC 4: stop_process(force=False) → SIGTERM, 进程优雅退出"""
    pm = ProcessManager()
    info = await pm.start_process("sleep 30")

    # 优雅停止
    result = await pm.stop_process(info.process_id, force=False)
    assert result is True, "stop_process should return True"

    await asyncio.sleep(0.5)
    status = pm.get_status(info.process_id)
    assert status.status == ProcessStatus.STOPPED, f"Expected STOPPED, got {status.status}"

    # SIGTERM 的退出码通常是 -15
    if sys.platform != "win32":
        assert status.exit_code == -signal.SIGTERM, f"Expected exit_code=-15, got {status.exit_code}"


# ─── AC 5: stop_process(force=True) → SIGKILL 立即终止 ─────────────────

@pytest.mark.asyncio
async def test_ac05_stop_force_sigkill():
    """AC 5: stop_process(force=True) → SIGKILL, 进程立即终止"""
    pm = ProcessManager()
    info = await pm.start_process("sleep 30")

    # 强制停止
    result = await pm.stop_process(info.process_id, force=True)
    assert result is True, "stop_process should return True"

    await asyncio.sleep(0.5)
    status = pm.get_status(info.process_id)
    assert status.status == ProcessStatus.KILLED, f"Expected KILLED, got {status.status}"

    # SIGKILL 的退出码通常是 -9
    if sys.platform != "win32":
        assert status.exit_code == -signal.SIGKILL, f"Expected exit_code=-9, got {status.exit_code}"


# ─── AC 6: meta.json 随状态变化实时更新 ─────────────────────────────────

@pytest.mark.asyncio
async def test_ac06_meta_json_updates_on_start():
    """AC 6a: 进程启动后 meta.json 包含初始状态"""
    pm = ProcessManager()
    info = await pm.start_process("echo meta_test")

    meta_path = Path(info.meta_path)
    assert meta_path.exists(), "meta.json should exist after start"

    meta = json.loads(meta_path.read_text())
    assert meta["status"] == "running", f"Expected running, got {meta['status']}"
    assert meta["command"] == "echo meta_test"
    assert meta["pid"] is not None, "PID should be set after start"
    assert meta["start_time"] is not None


@pytest.mark.asyncio
async def test_ac06_meta_json_updates_on_completion():
    """AC 6b: 进程完成后 meta.json 更新状态和退出码"""
    pm = ProcessManager()
    info = await pm.start_process("echo done")
    await asyncio.sleep(0.5)

    meta = json.loads(Path(info.meta_path).read_text())
    assert meta["status"] == "completed", f"Expected completed, got {meta['status']}"
    assert meta["exit_code"] == 0
    assert meta["end_time"] is not None


@pytest.mark.asyncio
async def test_ac06_meta_json_updates_on_stop():
    """AC 6c: 进程被停止后 meta.json 更新状态"""
    pm = ProcessManager()
    info = await pm.start_process("sleep 30")
    await pm.stop_process(info.process_id, force=True)
    await asyncio.sleep(0.3)

    meta = json.loads(Path(info.meta_path).read_text())
    assert meta["status"] in ("killed", "stopped"), f"Expected killed/stopped, got {meta['status']}"
    assert meta["end_time"] is not None


# ─── AC 7: list_processes() 返回所有活跃进程 ─────────────────────────

@pytest.mark.asyncio
async def test_ac07_list_processes_returns_all():
    """AC 7: list_processes() 返回所有活跃进程"""
    pm = ProcessManager()
    info1 = await pm.start_process("sleep 10")
    info2 = await pm.start_process("sleep 20")

    procs = pm.list_processes()
    assert len(procs) == 2, f"Expected 2 processes, got {len(procs)}"

    pids = [p.process_id for p in procs]
    assert info1.process_id in pids
    assert info2.process_id in pids

    # 全部是 RUNNING
    for p in procs:
        assert p.status == ProcessStatus.RUNNING

    # 清理
    await pm.cleanup()
    assert len(pm.list_processes()) == 0, "After cleanup, list should be empty"
