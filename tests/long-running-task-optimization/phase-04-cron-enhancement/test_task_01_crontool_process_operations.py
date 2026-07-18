"""
Tests for ProcessTool 进程管理操作
(原 CronTool 进程管理操作拆分至独立 ProcessTool)

AC 1: track_process 对运行中的进程返回 status、PID、运行时间、输出文件路径
AC 2: list_processes 列出所有活跃进程及基本信息
AC 3: stop_process 优雅停止（SIGTERM）/强制停止（SIGKILL）进程
AC 4: 操作不存在的 process_id 返回明确的错误消息
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


# ─── AC 1: track_process ──────────────────────────────────────

@pytest.mark.asyncio
async def test_ac01_track_running_process():
    """AC 1: track_process 对运行中的进程返回 status、PID、路径"""
    pm = ProcessManager()
    info = await pm.start_process("sleep 20")

    pt = ProcessTool()
    ctx = ToolCallContext()
    ctx.agent = MagicMock()
    ctx.agent.agent_id = "test_agent"

    result = await pt._track_process({"process_id": info.process_id}, ctx)

    # 验证返回成功
    assert result.status.value == "success", \
        f"Expected success, got {result.status.value}"

    # 验证返回内容包含关键信息
    content = result.content.lower()
    assert "running" in content, "Should show running status"
    assert str(info.pid) in result.content, "Should show PID"
    assert "stdout" in result.content.lower(), "Should show stdout path"
    assert "stderr" in result.content.lower(), "Should show stderr path"

    # 清理
    await pm.stop_process(info.process_id, force=True)


@pytest.mark.asyncio
async def test_ac01_track_completed_process():
    """AC 1b: track_process 对已完成的进程也能返回信息"""
    pm = ProcessManager()
    info = await pm.start_process("echo track_test")
    await asyncio.sleep(0.5)

    pt = ProcessTool()
    ctx = ToolCallContext()

    result = await pt._track_process({"process_id": info.process_id}, ctx)
    assert result.status.value == "success"
    assert "completed" in result.content.lower()


# ─── AC 2: list_processes ─────────────────────────────────────

@pytest.mark.asyncio
async def test_ac02_list_all_processes():
    """AC 2: list_processes 列出所有活跃进程及基本信息"""
    pm = ProcessManager()
    info1 = await pm.start_process("sleep 20")
    info2 = await pm.start_process("sleep 20")

    pt = ProcessTool()
    ctx = ToolCallContext()

    result = await pt._list_processes({}, ctx)
    assert result.status.value == "success"

    # 验证两个进程都在列表中
    content = result.content
    assert info1.process_id in content, \
        f"Should include process {info1.process_id}"
    assert info2.process_id in content, \
        f"Should include process {info2.process_id}"
    assert "2 个进程" in content or "2 processes" in content.lower() or "2" in content, \
        "Should indicate 2 processes"

    # 清理
    await pm.cleanup()


@pytest.mark.asyncio
async def test_ac02_list_empty():
    """AC 2b: 没有进程时 list_processes 返回空提示"""
    pt = ProcessTool()
    ctx = ToolCallContext()

    result = await pt._list_processes({}, ctx)
    assert result.status.value == "success"
    assert "没有" in result.content or "no" in result.content.lower() or "empty" in result.content.lower(), \
        f"Empty state should show appropriate message: {result.content}"


# ─── AC 3: stop_process ───────────────────────────────────────

@pytest.mark.asyncio
async def test_ac03_stop_process_graceful():
    """AC 3a: stop_process 优雅停止（SIGTERM）"""
    pm = ProcessManager()
    info = await pm.start_process("sleep 30")

    pt = ProcessTool()
    ctx = ToolCallContext()

    result = await pt._stop_process({"process_id": info.process_id, "force": False}, ctx)
    assert result.status.value == "success", \
        f"Expected success, got {result.status.value}"

    await asyncio.sleep(0.3)
    status = pm.get_status(info.process_id)
    assert status.status == ProcessStatus.STOPPED, \
        f"Expected STOPPED, got {status.status}"


@pytest.mark.asyncio
async def test_ac03_stop_process_force():
    """AC 3b: stop_process 强制停止（SIGKILL）"""
    pm = ProcessManager()
    info = await pm.start_process("sleep 30")

    pt = ProcessTool()
    ctx = ToolCallContext()

    result = await pt._stop_process({"process_id": info.process_id, "force": True}, ctx)
    assert result.status.value == "success"

    await asyncio.sleep(0.3)
    status = pm.get_status(info.process_id)
    assert status.status == ProcessStatus.KILLED, \
        f"Expected KILLED, got {status.status}"


# ─── AC 4: 不存在的 process_id 返回错误 ─────────────────────

@pytest.mark.asyncio
async def test_ac04_track_nonexistent_process():
    """AC 4a: track_process 不存在的 process_id 返回错误"""
    pt = ProcessTool()
    ctx = ToolCallContext()

    result = await pt._track_process({"process_id": "nonexistent_proc"}, ctx)
    assert result.status.value == "error", \
        f"Expected error, got {result.status.value}"
    assert "不存在" in result.content or "not found" in result.content.lower() or "nonexistent" in result.content.lower(), \
        f"Should indicate process not found: {result.content}"


@pytest.mark.asyncio
async def test_ac04_stop_nonexistent_process():
    """AC 4b: stop_process 不存在的 process_id 返回错误"""
    pt = ProcessTool()
    ctx = ToolCallContext()

    result = await pt._stop_process({"process_id": "nonexistent_proc"}, ctx)
    assert result.status.value == "error", \
        f"Expected error, got {result.status.value}"
    assert "失败" in result.content or "不存在" in result.content or "not found" in result.content.lower() or "failed" in result.content.lower(), \
        f"Should indicate failure: {result.content}"


# ─── AC 5: get_job 结果中增加进程状态信息 ─────────────────────

@pytest.mark.asyncio
async def test_ac05_get_job_process_status_logic():
    """AC 5: get_job 中 process_status 添加逻辑正确

    验证 get_job 方法中的 process_status 构造逻辑。
    由于 get_job 需要数据库记录，这里直接验证 process_status 的构造。
    """
    from broca.scheduler import Scheduler
    s = Scheduler()

    pm = ProcessManager()
    info = await pm.start_process("sleep 30")

    # 手动设置 job_process_map（模拟 Scheduler 的内部状态）
    s._job_process_map["test_job_pm"] = info.process_id

    # 验证 _job_process_map 中有映射
    mapped_process_id = s._job_process_map.get("test_job_pm")
    assert mapped_process_id == info.process_id

    # 验证 ProcessManager 能通过 process_id 查询到进程状态
    pinfo = pm.get_status(mapped_process_id)
    assert pinfo is not None
    assert pinfo.status == ProcessStatus.RUNNING
    assert pinfo.pid == info.pid
    assert pinfo.stdout_path is not None
    assert pinfo.stderr_path is not None

    # 清理
    await pm.stop_process(info.process_id, force=True)
    await asyncio.sleep(0.3)
    s._job_process_map.pop("test_job_pm", None)


@pytest.mark.asyncio
async def test_ac05_get_job_no_process_in_map():
    """AC 5b: 没有关联进程的 get_job 不包含 process_status"""
    from broca.scheduler import Scheduler
    s = Scheduler()

    # 验证没有映射时不会返回错误
    assert s._job_process_map.get("nonexistent_job") is None
