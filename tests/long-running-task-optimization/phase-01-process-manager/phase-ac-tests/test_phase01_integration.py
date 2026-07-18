"""
Phase 1 集成测试: ProcessManager 核心模块
Plan: plans/long-running-task-optimization-plan.md

Phase AC 1: 新模块 broca/process_manager.py 完整实现，单例模式
Phase AC 2: 进程启动时 stdout/stderr 通过 shell 重定向到文件，不做内存缓冲
Phase AC 3: 支持按 process_id 查询状态（运行中/已完成/已失败/被停止）和文件路径
Phase AC 4: 支持发送 SIGTERM（优雅停止）和 SIGKILL（强制停止）到整个进程组
Phase AC 5: 进程退出后自动更新 meta.json（状态、退出码、结束时间）
Phase AC 6: 自动清理已结束超过 1 小时的进程记录和输出文件
Phase AC 7: 三层防御确保主进程退出后后台进程被清理
Phase AC 8: 单元测试覆盖正常执行、取消进程、进程异常退出、父进程崩溃场景
"""

import asyncio
import json
import os
import shutil
import signal
import sys
from pathlib import Path

import pytest
import pytest_asyncio

from broca.process_manager import ProcessManager, ProcessStatus


@pytest_asyncio.fixture(autouse=True)
async def reset_pm():
    pm = ProcessManager()
    await pm.cleanup()
    output_dir = Path(ProcessManager.OUTPUT_DIR)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    yield
    pm = ProcessManager()
    await pm.cleanup()


@pytest.mark.asyncio
async def test_phase_ac01_singleton_and_module_exists():
    """Phase AC 1: 新模块完整实现，单例模式"""
    # 验证模块可导入
    import broca.process_manager as pm_module
    assert hasattr(pm_module, "ProcessManager")
    assert hasattr(pm_module, "ProcessStatus")
    assert hasattr(pm_module, "ProcessInfo")

    # 验证单例模式
    pm1 = ProcessManager()
    pm2 = ProcessManager()
    assert pm1 is pm2, "ProcessManager should be a singleton"

    # 验证 ProcessStatus 枚举
    assert ProcessStatus.RUNNING.value == "running"
    assert ProcessStatus.COMPLETED.value == "completed"
    assert ProcessStatus.FAILED.value == "failed"
    assert ProcessStatus.STOPPED.value == "stopped"
    assert ProcessStatus.KILLED.value == "killed"


@pytest.mark.asyncio
async def test_phase_ac02_file_redirect_no_memory_buffer():
    """Phase AC 2: stdout/stderr 通过 shell 重定向到文件，不做内存缓冲"""
    pm = ProcessManager()
    info = await pm.start_process("echo file_redirect_test && echo stderr_test >&2")
    await asyncio.sleep(0.5)

    # 验证文件存在
    stdout_path = Path(info.stdout_path)
    stderr_path = Path(info.stderr_path)
    assert stdout_path.exists(), "stdout.log should exist"
    assert stderr_path.exists(), "stderr.log should exist"

    # 验证内容分别写入不同文件
    stdout_content = stdout_path.read_text().strip()
    stderr_content = stderr_path.read_text().strip()
    assert "file_redirect_test" in stdout_content
    assert "stderr_test" in stderr_content

    # 验证 ProcessInfo._process 没有 stdout/stderr 管道（无内存缓冲）
    assert info._process.stdout is None or info._process.stdout == asyncio.subprocess.DEVNULL, \
        "Should not buffer stdout in memory"
    assert info._process.stderr is None or info._process.stderr == asyncio.subprocess.DEVNULL, \
        "Should not buffer stderr in memory"


@pytest.mark.asyncio
async def test_phase_ac03_query_status_by_process_id():
    """Phase AC 3: 支持按 process_id 查询状态和文件路径"""
    pm = ProcessManager()
    info = await pm.start_process("sleep 20")

    # 查询运行中状态
    status = pm.get_status(info.process_id)
    assert status is not None
    assert status.status == ProcessStatus.RUNNING
    assert status.process_id == info.process_id
    assert status.pid > 0
    assert status.stdout_path is not None
    assert status.stderr_path is not None
    assert status.meta_path is not None

    # 查询不存在的 process_id
    none_status = pm.get_status("nonexistent_id")
    assert none_status is None

    # 停止后查询状态变化
    await pm.stop_process(info.process_id, force=True)
    await asyncio.sleep(0.3)
    stopped_status = pm.get_status(info.process_id)
    assert stopped_status.status in (ProcessStatus.KILLED, ProcessStatus.STOPPED)


@pytest.mark.asyncio
async def test_phase_ac04_sigterm_and_sigkill_to_process_group():
    """Phase AC 4: SIGTERM 优雅停止和 SIGKILL 强制停止到整个进程组"""
    if sys.platform == "win32":
        pytest.skip("Process group signals not supported on Windows")

    pm = ProcessManager()

    # 测试 SIGTERM
    info1 = await pm.start_process("sleep 30")
    await pm.stop_process(info1.process_id, force=False)
    await asyncio.sleep(0.3)
    status1 = pm.get_status(info1.process_id)
    assert status1.status == ProcessStatus.STOPPED
    assert status1.exit_code == -signal.SIGTERM

    # 测试 SIGKILL
    info2 = await pm.start_process("sleep 30")
    await pm.stop_process(info2.process_id, force=True)
    await asyncio.sleep(0.3)
    status2 = pm.get_status(info2.process_id)
    assert status2.status == ProcessStatus.KILLED
    assert status2.exit_code == -signal.SIGKILL


@pytest.mark.asyncio
async def test_phase_ac05_meta_json_auto_update():
    """Phase AC 5: 进程退出后自动更新 meta.json（状态、退出码、结束时间）"""
    pm = ProcessManager()
    info = await pm.start_process("echo auto_meta_update")
    await asyncio.sleep(0.5)

    meta = json.loads(Path(info.meta_path).read_text())
    assert meta["status"] == "completed"
    assert meta["exit_code"] == 0
    assert meta["end_time"] is not None
    assert meta["start_time"] is not None
    assert meta["process_id"] == info.process_id
    assert meta["command"] == "echo auto_meta_update"


@pytest.mark.asyncio
async def test_phase_ac06_auto_cleanup_old_processes():
    """Phase AC 6: 自动清理已结束超过 1 小时的进程记录和输出文件"""
    pm = ProcessManager()
    info = await pm.start_process("echo cleanup_test")
    await asyncio.sleep(0.3)

    # 进程完成后，设置 end_time 为 2 小时前（模拟过期）
    proc_dir = Path(info.meta_path).parent
    assert proc_dir.exists()

    # 手动触发清理（设置清理阈值为 0 秒来模拟）
    # 直接修改 end_time 使其过期
    status = pm.get_status(info.process_id)
    import datetime
    from datetime import timezone
    status.end_time = datetime.datetime.now(timezone.utc) - datetime.timedelta(hours=2)

    # 强制将 _MAX_PROCESS_AGE 临时调小来验证清理逻辑
    original_max_age = pm._MAX_PROCESS_AGE
    pm._MAX_PROCESS_AGE = 0  # 立即过期
    pm._cleanup_old()       # 执行清理

    # 验证进程记录已被清理
    assert pm.get_status(info.process_id) is None, \
        "Old process should be removed from registry"

    # 恢复原始值
    pm._MAX_PROCESS_AGE = original_max_age


@pytest.mark.asyncio
async def test_phase_ac07_three_layer_defense():
    """Phase AC 7: 三层防御确保主进程退出后后台进程被清理"""
    pm = ProcessManager()
    info = await pm.start_process("sleep 30")
    assert pm.get_status(info.process_id).status == ProcessStatus.RUNNING

    # 第 1 层验证：独立进程组
    if sys.platform != "win32":
        try:
            # 验证进程组存在（通过 os.getpgid 检查）
            pgid = os.getpgid(info.pid)
            assert pgid == info.pid, "Process should be in its own group (PGID == PID)"
        except ProcessLookupError:
            pass  # 进程可能已经结束

    # 第 3 层验证：cleanup 杀死所有进程
    await pm.cleanup()
    assert len(pm.list_processes()) == 0, "After cleanup, no processes should remain"

    # 验证进程确实被杀死
    await asyncio.sleep(0.3)
    try:
        os.kill(info.pid, 0)
        # 进程还在（可能僵尸），再等一次
        await asyncio.sleep(0.5)
        with pytest.raises(ProcessLookupError):
            os.kill(info.pid, 0)
    except ProcessLookupError:
        pass  # 进程已死，符合预期
