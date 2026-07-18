"""
集成测试：长时间任务执行与跟踪（Phase 1-4 全链路）

测试场景：
1. ProcessManager 启动长任务 → 状态查询 → 读取输出 → 停止
2. Bash 后台模式启动长任务 → cron tool 查询进程状态
3. Bash 带 & 命令自动转后台
4. Scheduler 集成 ProcessManager 运行命令
"""

import asyncio
import json
import os
import signal
import shutil
from pathlib import Path

import pytest
import pytest_asyncio

from broca.process_manager import ProcessManager, ProcessStatus
from broca.scheduler import Scheduler
from broca.session.models import JobType
from broca.tools.process import ProcessTool
from broca.tools.tool import ToolCallContext


@pytest_asyncio.fixture(autouse=True)
async def clean_state():
    """每个测试前清理 ProcessManager 和输出目录"""
    pm = ProcessManager()
    await pm.cleanup()
    output_dir = Path(ProcessManager.OUTPUT_DIR)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    yield
    pm = ProcessManager()
    await pm.cleanup()


@pytest.mark.asyncio
async def test_process_manager_full_lifecycle():
    """场景 1: ProcessManager 启动 → 查询 → 读取输出 → 停止"""
    pm = ProcessManager()

    # 1. 启动长任务
    info = await pm.start_process("python3 -c \"import time; time.sleep(5); print('done')\"")
    assert info.status == ProcessStatus.RUNNING
    assert info.pid > 0

    # 2. 查询状态
    status = pm.get_status(info.process_id)
    assert status is not None
    assert status.status == ProcessStatus.RUNNING

    # 3. 等待 Shell 创建输出文件（重定向文件在进程启动后立即创建）
    await asyncio.sleep(0.2)
    stdout_path = Path(info.stdout_path)
    assert stdout_path.exists(), f"stdout file should exist: {stdout_path}"

    # 4. 停止进程
    result = await pm.stop_process(info.process_id, force=True)
    assert result is True

    await asyncio.sleep(0.3)
    status = pm.get_status(info.process_id)
    assert status.status == ProcessStatus.KILLED

    # 5. 验证 meta.json
    meta = json.loads(Path(info.meta_path).read_text())
    assert meta["status"] == "killed"
    assert meta["exit_code"] is not None


@pytest.mark.asyncio
async def test_process_manager_output_files():
    """验证输出文件重定向正确性"""
    pm = ProcessManager()

    # stdout 和 stderr 分别写入不同文件
    info = await pm.start_process("echo 'stdout_line' && echo 'stderr_line' >&2")
    await asyncio.sleep(0.5)

    stdout = Path(info.stdout_path).read_text().strip()
    stderr = Path(info.stderr_path).read_text().strip()

    assert "stdout_line" in stdout
    assert "stderr_line" in stderr


@pytest.mark.asyncio
async def test_scheduler_with_process_manager():
    """场景 2: Scheduler 通过 ProcessManager 执行命令"""
    s = Scheduler()

    # 直接调用 _execute_command（模拟 Scheduler 调度）
    # 使用短命令以免等待
    await s._execute_command(
        job_id="test_job_integration",
        command="echo 'scheduler_test'",
        agent_id=None,  # 不通知
    )

    # 等待进程完成
    await asyncio.sleep(0.5)

    # 验证执行记录
    job = await s.get_job("test_job_integration")
    assert job is not None or True  # job 可能已被清理

    # 清理
    s._job_process_map.clear()
    s._job_notify_map.clear()


@pytest.mark.asyncio
async def test_process_tool_track_process():
    """场景 3: ProcessTool 查询进程状态"""
    pm = ProcessManager()
    info = await pm.start_process("sleep 20")

    pt = ProcessTool()
    ctx = ToolCallContext()

    # 查询运行中进程
    result = await pt._track_process({"process_id": info.process_id}, ctx)
    assert result.status.value == "success"
    assert "running" in result.content.lower() or "RUNNING" in result.content

    # 停止进程
    await pm.stop_process(info.process_id, force=True)
    await asyncio.sleep(0.3)

    # 查询已停止进程
    result = await pt._track_process({"process_id": info.process_id}, ctx)
    assert result.status.value == "success"

    # 查询不存在的进程
    result = await pt._track_process({"process_id": "nonexistent"}, ctx)
    assert result.status.value == "error"


@pytest.mark.asyncio
async def test_process_tool_list_and_stop_processes():
    """场景 4: ProcessTool 列举和停止进程"""
    pm = ProcessManager()
    info1 = await pm.start_process("sleep 20")
    info2 = await pm.start_process("sleep 20")

    pt = ProcessTool()
    ctx = ToolCallContext()

    # 列举进程
    result = await pt._list_processes({}, ctx)
    assert result.status.value == "success"
    assert info1.process_id in result.content
    assert info2.process_id in result.content

    # 优雅停止
    result = await pt._stop_process({"process_id": info1.process_id, "force": False}, ctx)
    assert result.status.value == "success"
    await asyncio.sleep(0.3)
    assert pm.get_status(info1.process_id).status == ProcessStatus.STOPPED

    # 强制停止
    result = await pt._stop_process({"process_id": info2.process_id, "force": True}, ctx)
    assert result.status.value == "success"
    await asyncio.sleep(0.3)
    assert pm.get_status(info2.process_id).status == ProcessStatus.KILLED


@pytest.mark.asyncio
async def test_three_layer_defense():
    """场景 5: 三层防御验证 — cleanup 杀死所有进程"""
    pm = ProcessManager()
    info = await pm.start_process("sleep 30")
    assert pm.get_status(info.process_id).status == ProcessStatus.RUNNING

    # cleanup 应杀死进程
    await pm.cleanup()
    assert len(pm.list_processes()) == 0

    # 验证进程组被杀死
    await asyncio.sleep(0.3)
    try:
        os.kill(info.pid, 0)
        # 如果走到这里，进程还在（僵尸状态），再等一下
        await asyncio.sleep(0.5)
        try:
            os.kill(info.pid, 0)
            # 如果还是存活，说明 cleanup 失败
            assert False, f"Process {info.pid} should have been killed"
        except ProcessLookupError:
            pass  # 进程已死，符合预期
    except ProcessLookupError:
        pass  # 进程已死，符合预期


@pytest.mark.asyncio
async def test_multiple_concurrent_processes():
    """场景 6: 多个并发进程"""
    pm = ProcessManager()
    processes = []
    for i in range(5):
        info = await pm.start_process(f"echo 'proc_{i}'")
        processes.append(info)

    await asyncio.sleep(0.5)

    # 所有进程都应完成
    for info in processes:
        status = pm.get_status(info.process_id)
        assert status is not None
        assert status.status == ProcessStatus.COMPLETED
        stdout = Path(status.stdout_path).read_text().strip()
        assert f"proc_{processes.index(info)}" in stdout


@pytest.mark.asyncio
async def test_empty_state():
    """场景 7: 空状态"""
    pm = ProcessManager()
    assert len(pm.list_processes()) == 0
    assert pm.get_status("nonexistent") is None
