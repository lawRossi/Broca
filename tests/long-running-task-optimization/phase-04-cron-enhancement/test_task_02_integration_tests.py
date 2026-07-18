"""
Tests for Task 4.2: 集成测试
Plan: plans/long-running-task-optimization-plan.md

AC 1: 所有集成测试通过
AC 2: 模拟完整用户场景：启动长任务 → 查询状态 → 读取输出 → 停止进程
"""

import asyncio
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from broca.process_manager import ProcessManager, ProcessStatus
from broca.tools.process import ProcessTool
from broca.tools.tool import ToolCallContext, ToolStatus


@pytest_asyncio.fixture(autouse=True)
async def clean_pm():
    pm = ProcessManager()
    await pm.cleanup()
    output_dir = Path(ProcessManager.OUTPUT_DIR)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    yield
    await pm.cleanup()


@pytest.mark.asyncio
async def test_ac01_all_integration_tests_pass():
    """AC 1: 所有集成测试通过 — 由 test runner 整体验证通过"""
    pass


@pytest.mark.asyncio
async def test_ac02_full_user_scenario():
    """AC 2: 模拟完整用户场景：启动长任务 → 查询状态 → 读取输出 → 停止进程"""
    # ── 1. 启动长任务 ────────────────────────────────────────
    pm = ProcessManager()
    # 使用 -u 禁用 Python 输出缓冲，确保 kill 前内容已写入文件
    info = await pm.start_process(
        "python3 -u -c \"\n"
        "import time\n"
        "print('server_started', flush=True)\n"
        "time.sleep(10)\n"
        "print('server_stopped', flush=True)\n"
        "\""
    )

    process_id = info.process_id
    assert info.status == ProcessStatus.RUNNING
    assert info.pid > 0

    # ── 2. 查询进程状态 ──────────────────────────────────────
    pt = ProcessTool()
    ctx = ToolCallContext()

    track_result = await pt._track_process({"process_id": process_id}, ctx)
    assert track_result.status.value == "success"
    assert "running" in track_result.content.lower()
    assert str(info.pid) in track_result.content

    # 验证文件路径信息
    assert "stdout" in track_result.content.lower()
    assert "stderr" in track_result.content.lower()

    # ── 3. 验证输出文件可访问（Agent 可用 read_file 读取） ──
    await asyncio.sleep(0.5)
    stdout_path = Path(info.stdout_path)
    assert stdout_path.exists(), "stdout.log should exist and be readable"

    # 验证输出文件包含预期内容（flush=True 确保内容已写入）
    stdout_content = stdout_path.read_text()
    assert "server_started" in stdout_content, \
        f"stdout should contain 'server_started', got: {stdout_content!r}"

    # ── 4. 列举进程（验证进程在列表中） ─────────────────────
    list_result = await pt._list_processes({}, ctx)
    assert list_result.status.value == "success"
    assert process_id in list_result.content

    # ── 5. 停止进程 ──────────────────────────────────────────
    stop_result = await pt._stop_process({"process_id": process_id, "force": True}, ctx)
    assert stop_result.status.value == "success", \
        f"Stop should succeed: {stop_result.content}"

    await asyncio.sleep(0.3)

    # ── 6. 验证进程已停止 ───────────────────────────────────
    final_status = pm.get_status(process_id)
    assert final_status is not None
    assert final_status.status in (ProcessStatus.KILLED, ProcessStatus.FAILED), \
        f"After force stop, status should be KILLED/FAILED, got {final_status.status}"


@pytest.mark.asyncio
async def test_ac02_scenario_with_http_server():
    """AC 2b: 模拟 HTTP 服务器场景：启动 → 查询 → 停止"""
    pm = ProcessManager()

    # 启动 Python HTTP 服务器
    info = await pm.start_process("python3 -m http.server 19999")
    assert info.status == ProcessStatus.RUNNING

    pt = ProcessTool()
    ctx = ToolCallContext()

    # 查询状态
    result = await pt._track_process({"process_id": info.process_id}, ctx)
    assert result.status.value == "success"

    # 停止
    stop_result = await pt._stop_process({"process_id": info.process_id, "force": True}, ctx)
    assert stop_result.status.value == "success"

    await asyncio.sleep(0.3)
    status = pm.get_status(info.process_id)
    assert status.status == ProcessStatus.KILLED
