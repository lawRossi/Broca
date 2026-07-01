"""
ProcessManager 单元测试

测试覆盖：正常执行、长时间运行查询、优雅/强制停止、异常退出、
大量输出、混合输出、多进程、cleanup、跨平台回退。
"""

import asyncio
import json
import os
import platform
import shutil
import signal
import sys
import time
from pathlib import Path

import pytest
import pytest_asyncio

from broca.process_manager import ProcessManager, ProcessStatus


# 确保每个测试有干净的 ProcessManager 单例
@pytest_asyncio.fixture(autouse=True)
async def reset_pm():
    """每个测试前重置 ProcessManager 状态"""
    pm = ProcessManager()
    await pm.cleanup()
    output_dir = Path(ProcessManager.OUTPUT_DIR)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    yield
    await pm.cleanup()


@pytest.mark.asyncio
async def test_short_command_completes():
    """短命令正常执行并完成"""
    pm = ProcessManager()
    info = await pm.start_process("echo hello_world")
    # 等待进程结束
    await asyncio.sleep(0.5)

    status = pm.get_status(info.process_id)
    assert status is not None
    assert status.status == ProcessStatus.COMPLETED
    assert status.exit_code == 0

    # 验证 stdout 文件内容
    stdout = Path(status.stdout_path).read_text().strip()
    assert stdout == "hello_world"

    # 验证 meta.json
    meta = json.loads(Path(status.meta_path).read_text())
    assert meta["status"] == "completed"
    assert meta["exit_code"] == 0
    assert meta["pid"] == status.pid


@pytest.mark.asyncio
async def test_long_running_process_status():
    """长时间运行进程能正确查询 RUNNING 状态"""
    pm = ProcessManager()
    info = await pm.start_process("sleep 10")

    status = pm.get_status(info.process_id)
    assert status is not None
    assert status.status == ProcessStatus.RUNNING
    assert status.pid > 0
    assert status.exit_code is None

    # 停止进程避免影响后续测试
    await pm.stop_process(info.process_id, force=True)
    await asyncio.sleep(0.3)


@pytest.mark.asyncio
async def test_stop_process_graceful():
    """优雅停止（SIGTERM）"""
    pm = ProcessManager()
    info = await pm.start_process("sleep 30")

    result = await pm.stop_process(info.process_id, force=False)
    assert result is True

    await asyncio.sleep(0.5)
    status = pm.get_status(info.process_id)
    assert status.status == ProcessStatus.STOPPED

    # 验证 meta.json 更新
    meta = json.loads(Path(status.meta_path).read_text())
    assert meta["status"] == "stopped"
    assert meta["end_time"] is not None


@pytest.mark.asyncio
async def test_stop_process_force():
    """强制停止（SIGKILL）"""
    pm = ProcessManager()
    info = await pm.start_process("sleep 30")

    result = await pm.stop_process(info.process_id, force=True)
    assert result is True

    await asyncio.sleep(0.5)
    status = pm.get_status(info.process_id)
    assert status.status == ProcessStatus.KILLED
    assert status.exit_code == -signal.SIGKILL  # -9

    meta = json.loads(Path(status.meta_path).read_text())
    assert meta["status"] == "killed"
    assert meta["exit_code"] == -9


@pytest.mark.asyncio
async def test_stop_nonexistent_process():
    """停止不存在的进程返回 False"""
    pm = ProcessManager()
    result = await pm.stop_process("nonexistent_id", force=False)
    assert result is False

    result = await pm.stop_process("nonexistent_id", force=True)
    assert result is False


@pytest.mark.asyncio
async def test_process_exit_failure():
    """进程异常退出返回 FAILED 状态"""
    pm = ProcessManager()
    # 运行不存在的命令
    info = await pm.start_process("nonexistent_command_xyz123")
    await asyncio.sleep(0.5)

    status = pm.get_status(info.process_id)
    assert status is not None
    assert status.status == ProcessStatus.FAILED
    assert status.exit_code != 0


@pytest.mark.asyncio
async def test_large_output():
    """大量输出正确写入文件"""
    pm = ProcessManager()
    # 生成 10000 行输出
    cmd = "for i in $(seq 1 10000); do echo \"line $i\"; done"
    info = await pm.start_process(cmd)
    await asyncio.sleep(1)

    status = pm.get_status(info.process_id)
    assert status.status == ProcessStatus.COMPLETED

    stdout = Path(status.stdout_path).read_text()
    lines = stdout.strip().split("\n")
    assert len(lines) == 10000
    assert lines[0] == "line 1"
    assert lines[-1] == "line 10000"


@pytest.mark.asyncio
async def test_mixed_stdout_stderr():
    """stdout 和 stderr 分别写入不同文件"""
    pm = ProcessManager()
    cmd = "echo out_message && echo err_message >&2"
    info = await pm.start_process(cmd)
    await asyncio.sleep(0.5)

    stdout = Path(info.stdout_path).read_text().strip()
    stderr = Path(info.stderr_path).read_text().strip()

    assert "out_message" in stdout
    assert "err_message" in stderr


@pytest.mark.asyncio
async def test_list_processes():
    """list_processes 返回所有活跃进程"""
    pm = ProcessManager()
    info1 = await pm.start_process("sleep 10")
    info2 = await pm.start_process("sleep 20")

    procs = pm.list_processes()
    assert len(procs) == 2

    pids = [p.process_id for p in procs]
    assert info1.process_id in pids
    assert info2.process_id in pids

    # 全部是 RUNNING
    for p in procs:
        assert p.status == ProcessStatus.RUNNING

    # 清理
    await pm.cleanup()


@pytest.mark.asyncio
async def test_cleanup_kills_all():
    """cleanup 杀死所有存活进程"""
    pm = ProcessManager()
    info1 = await pm.start_process("sleep 30")
    info2 = await pm.start_process("sleep 30")

    assert pm.get_status(info1.process_id).status == ProcessStatus.RUNNING
    assert pm.get_status(info2.process_id).status == ProcessStatus.RUNNING

    await pm.cleanup()

    # cleanup 清空了注册表
    assert len(pm.list_processes()) == 0

    # 验证进程确实被杀死（给内核一点时间回收）
    await asyncio.sleep(0.3)
    for pid in [info1.pid, info2.pid]:
        try:
            os.kill(pid, 0)  # 信号 0 仅检查进程存在
            # 进程可能还在僵尸状态，再等一次
            await asyncio.sleep(0.5)
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
        except ProcessLookupError:
            pass  # 进程已死，符合预期


@pytest.mark.asyncio
async def test_killpg_cross_platform():
    """验证跨平台进程组终止逻辑"""
    pm = ProcessManager()
    info = await pm.start_process("sleep 20")

    # 验证进程组存在
    if sys.platform != "win32":
        try:
            os.killpg(info.pid, 0)  # 不发送信号，只检查进程是否存在
            assert True  # 进程组存在
        except ProcessLookupError:
            pytest.fail("Process group should exist")

    # 通过 stop_process 使用 SIGKILL（内部会走 killpg/terminate）
    result = await pm.stop_process(info.process_id, force=True)
    assert result is True

    await asyncio.sleep(0.3)
    status = pm.get_status(info.process_id)
    assert status.status == ProcessStatus.KILLED


@pytest.mark.asyncio
async def test_repeated_start_stop():
    """重复启动和停止不影响系统稳定性"""
    pm = ProcessManager()
    for i in range(5):
        info = await pm.start_process(f"echo \"run {i}\"")
        await asyncio.sleep(0.3)
        status = pm.get_status(info.process_id)
        assert status.status == ProcessStatus.COMPLETED
        stdout = Path(info.stdout_path).read_text().strip()
        assert stdout == f"run {i}"


@pytest.mark.asyncio
async def test_process_output_dir_structure():
    """验证输出目录结构正确"""
    pm = ProcessManager()
    info = await pm.start_process("echo test")
    await asyncio.sleep(0.3)

    proc_dir = Path(pm.OUTPUT_DIR) / info.process_id
    assert proc_dir.exists()
    assert (proc_dir / "stdout.log").exists()
    assert (proc_dir / "stderr.log").exists()
    assert (proc_dir / "meta.json").exists()
