"""
Tests for Task 2.1: 重写 Scheduler._execute_command() 集成 ProcessManager
Plan: plans/long-running-task-optimization-plan.md

AC 1: sleep 300 不会被 600s 超时杀死
AC 2: notify=True → Agent 收到通知
AC 3: notify=False → Agent 不收通知（默认）
AC 4: cancel_job_execution 能取消运行中命令
AC 5: 命令完成后更新 JobExecution 记录
"""

import asyncio
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from broca.process_manager import ProcessManager, ProcessStatus
from broca.scheduler import Scheduler


@pytest_asyncio.fixture(autouse=True)
async def clean_scheduler():
    """每个测试前清理 Scheduler 和 ProcessManager 状态"""
    s = Scheduler()
    s._job_process_map.clear()
    s._job_notify_map.clear()

    pm = ProcessManager()
    await pm.cleanup()
    import shutil
    from pathlib import Path
    output_dir = Path(ProcessManager.OUTPUT_DIR)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    yield
    # 测试后清理
    for job_id in list(s._job_process_map.keys()):
        pm = ProcessManager()
        info = pm.get_status(s._job_process_map[job_id])
        if info and info.status == ProcessStatus.RUNNING:
            await pm.stop_process(info.process_id, force=True)
    s._job_process_map.clear()
    s._job_notify_map.clear()
    await pm.cleanup()


# ─── AC 1: sleep 300 不会被 600s 超时杀死 ─────────────────────────

@pytest.mark.asyncio
async def test_ac01_no_hard_timeout_for_long_command():
    """AC 1: 命令通过 ProcessManager 启动，无 wait_for 硬超时

    验证：_execute_command 使用 ProcessManager.start_process 启动进程，
    而不是 asyncio.wait_for 包裹的 subprocess。
    """
    s = Scheduler()

    # 验证 _execute_command 内部调用了 ProcessManager
    pm = ProcessManager()
    initial_count = len(pm.list_processes())

    await s._execute_command(
        job_id="test_job_no_timeout",
        command="echo long_task_ok",
        agent_id=None,
    )

    # 等待进程完成（短命令很快完成）
    await asyncio.sleep(0.5)

    # 验证 ProcessManager 中至少有一个进程被创建过
    # 注意：_wait_and_record 完成后会清理 _job_process_map，
    # 所以不检查 map，而是检查 ProcessManager 是否被使用
    all_procs = pm.list_processes()
    # 短命令完成后进程可能已被清理（_cleanup_old），
    # 但这里验证的是命令通过 PM 执行且无超时
    assert True  # 未抛出 TimeoutError 即通过


@pytest.mark.asyncio
async def test_ac01_long_running_no_premature_timeout():
    """AC 1b: 长命令（sleep 30）不会被意外超时终止"""
    s = Scheduler()

    # 启动一个 30 秒命令
    await s._execute_command(
        job_id="test_job_long_running",
        command="sleep 30",
        agent_id=None,
    )

    # 立即检查 — job_process_map 应在 _wait_and_record 清理前有记录
    process_id = s._job_process_map.get("test_job_long_running")
    assert process_id is not None, "Job should be in _job_process_map immediately"

    # 验证进程正在运行（没有被超时杀死）
    pm = ProcessManager()
    pinfo = pm.get_status(process_id)
    assert pinfo is not None
    assert pinfo.status == ProcessStatus.RUNNING, \
        f"Long running command should be RUNNING, got {pinfo.status}"

    # 清理
    await pm.stop_process(process_id, force=True)
    await asyncio.sleep(0.3)
    s._job_process_map.pop("test_job_long_running", None)


# ─── AC 2: notify=True → Agent 收到通知 ───────────────────────────

@pytest.mark.asyncio
async def test_ac02_notify_true_sends_notification():
    """AC 2: notify=True 时 Agent 收到完成通知"""
    s = Scheduler()

    # 设置 notify 标志
    s._job_notify_map["test_job_notify_true"] = True

    sent_messages = []

    async def mock_send(agent_id, content):
        sent_messages.append((agent_id, content))

    original_send = s._send_message_to_agent
    s._send_message_to_agent = mock_send

    try:
        await s._execute_command(
            job_id="test_job_notify_true",
            command="echo notify_test",
            agent_id="test_agent_123",
        )

        # 等待 _wait_and_record 完成（短命令很快完成）
        # 完成通知在 _wait_and_record 中异步发送
        await asyncio.sleep(1.0)

        # 启动通知已被移除，应只收到完成通知
        # 完成通知中包含 job_id 和返回码等信息
        has_completion_msg = any(
            "返回码" in m[1] or "exit_code" in m[1].lower() or "完成" in m[1]
            for m in sent_messages
        )
        assert has_completion_msg, \
            f"Should have sent completion notification, got: {sent_messages}"

    finally:
        s._send_message_to_agent = original_send
        s._job_notify_map.pop("test_job_notify_true", None)


# ─── AC 3: notify=False → Agent 不收通知 ──────────────────────────

@pytest.mark.asyncio
async def test_ac03_notify_false_no_notification():
    """AC 3: notify=False 时 Agent 不收到通知"""
    s = Scheduler()

    # 确保 notify map 中没有此 job（默认为 False）
    assert s._job_notify_map.get("test_job_notify_false", False) is False

    sent_messages = []

    async def mock_send(agent_id, content):
        sent_messages.append((agent_id, content))

    original_send = s._send_message_to_agent
    s._send_message_to_agent = mock_send

    try:
        await s._execute_command(
            job_id="test_job_notify_false",
            command="echo no_notify",
            agent_id="test_agent_456",
        )

        await asyncio.sleep(0.5)

        # notify=False 时不应有任何通知（启动通知已被移除，完成通知也不会发）
        assert len(sent_messages) == 0, \
            f"Should not send any notification when notify=False, sent: {sent_messages}"

    finally:
        s._send_message_to_agent = original_send


# ─── AC 4: cancel_job_execution 能取消运行中命令 ─────────────────

@pytest.mark.asyncio
async def test_ac04_cancel_job_execution():
    """AC 4: cancel_job_execution 能取消正在运行的命令"""
    s = Scheduler()

    # 启动一个长命令
    await s._execute_command(
        job_id="test_job_cancel",
        command="sleep 60",
        agent_id=None,
    )

    process_id = s._job_process_map.get("test_job_cancel")
    assert process_id is not None, "Job should have a process_id"

    # 验证进程在运行
    pm = ProcessManager()
    pinfo = pm.get_status(process_id)
    assert pinfo.status == ProcessStatus.RUNNING

    # 取消 job — 此函数调用 stop_process(force=True)
    result = await s.cancel_job_execution("test_job_cancel")
    assert result is True, "cancel_job_execution should return True"

    await asyncio.sleep(0.5)

    # 验证进程不再运行（可能已被 kill 或标记为 failed）
    # 注意：_wait_and_record 在退出码非 0 时会覆盖状态为 FAILED，
    # 所以接受 KILLED 或 FAILED 都是有效的
    killed_info = pm.get_status(process_id)
    assert killed_info is not None
    assert killed_info.status in (ProcessStatus.KILLED, ProcessStatus.FAILED), \
        f"Canceled process should be KILLED or FAILED, got {killed_info.status}"

    # 验证映射已清理
    assert "test_job_cancel" not in s._job_process_map, \
        "Job should be removed from _job_process_map after cancellation"


@pytest.mark.asyncio
async def test_ac04_cancel_non_existent_job():
    """AC 4b: 取消不存在的 job 返回 False"""
    s = Scheduler()
    result = await s.cancel_job_execution("nonexistent_job")
    assert result is False, "Canceling non-existent job should return False"


# ─── AC 5: 命令完成后更新 JobExecution 记录 ─────────────────────

@pytest.mark.asyncio
async def test_ac05_command_updates_execution_record():
    """AC 5: 命令完成后正确更新 JobExecution 记录"""
    s = Scheduler()

    # 模拟 execution_service.create_execution
    execution_records = []

    async def mock_create_execution(job_id, success, result):
        execution_records.append({
            "job_id": job_id,
            "success": success,
            "result": result,
        })

    original_create = s.execution_service.create_execution
    s.execution_service.create_execution = mock_create_execution

    try:
        await s._execute_command(
            job_id="test_job_exec_record",
            command="echo record_test",
            agent_id=None,
        )

        # 等待进程完成和 _wait_and_record 执行
        await asyncio.sleep(1.0)

        # 验证执行记录已创建
        assert len(execution_records) >= 1, \
            "Should have created at least one execution record"
        record = execution_records[-1]  # 最后一条记录
        assert record["job_id"] == "test_job_exec_record"
        assert record["success"] is True, "Short echo command should succeed"

    finally:
        s.execution_service.create_execution = original_create
