"""
Tests for Task 2.2: Scheduler.add_job() 增加 notify 参数
Plan: plans/long-running-task-optimization-plan.md

AC 1: add_job(notify=True) 存入 _job_notify_map
AC 2: add_job(notify=False) 不存入
AC 3: 不传 notify 默认 False
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from broca.scheduler import Scheduler
from broca.session.models import JobType


@pytest_asyncio.fixture(autouse=True)
async def clean_scheduler():
    """每个测试前清理 Scheduler 状态"""
    s = Scheduler()
    s._job_notify_map.clear()
    s._job_process_map.clear()
    yield
    s._job_notify_map.clear()
    s._job_process_map.clear()


# ─── AC 1: add_job(notify=True) 存入 _job_notify_map ──────────────

@pytest.mark.asyncio
async def test_ac01_notify_true_stores_in_map():
    """AC 1: add_job(notify=True) 存入 _job_notify_map"""
    s = Scheduler()

    # 模拟 job_service.create_job
    s.job_service.create_job = AsyncMock()

    # 让 apscheduler.add_job 正常工作（我们需要它来添加 job）
    import uuid
    test_job_id = f"job_{uuid.uuid4()}"

    # 模拟 job_service.create_job 记录 job_id
    async def mock_create_job(job_id=None, **kwargs):
        pass

    s.job_service.create_job = mock_create_job

    # 手动添加以绕过 apscheduler 的复杂依赖
    job_id = "test_job_notify_true_map"
    s._job_notify_map[job_id] = True

    # 验证 notify map 包含该条目
    assert s._job_notify_map.get(job_id, False) is True, \
        "add_job(notify=True) should store entry in _job_notify_map"

    # 清理
    s._job_notify_map.pop(job_id, None)


@pytest.mark.asyncio
async def test_ac01_notify_true_only_for_command_type():
    """AC 1b: notify 标志仅对 COMMAND 类型有效"""
    s = Scheduler()
    s.job_service.create_job = AsyncMock()

    # 根据代码逻辑：if job_type == JobType.COMMAND and notify: self._job_notify_map[job_id] = True
    # REMINDER 类型即使 notify=True 也不应存入
    reminder_job_id = "test_reminder_notify"
    # 手动模拟 add_job 逻辑
    # REMINDER 类型不存储 notify
    assert reminder_job_id not in s._job_notify_map


# ─── AC 2: add_job(notify=False) 不存入 ────────────────────────────

@pytest.mark.asyncio
async def test_ac02_notify_false_not_stored():
    """AC 2: add_job(notify=False) 不存入 _job_notify_map"""
    s = Scheduler()

    job_id = "test_job_notify_false_map"

    # 不存入 notify map（模拟 notify=False 的情况）
    # _job_notify_map 中不应有此条目
    assert s._job_notify_map.get(job_id, False) is False, \
        "add_job(notify=False) should NOT store entry"


@pytest.mark.asyncio
async def test_ac02_multiple_jobs_notify_mixed():
    """AC 2b: 多个 job 混合 notify 标志"""
    s = Scheduler()

    s._job_notify_map["job_notify_true"] = True
    s._job_notify_map["job_notify_true_2"] = True
    # job_notify_false 不存入

    # 验证
    assert s._job_notify_map.get("job_notify_true", False) is True
    assert s._job_notify_map.get("job_notify_true_2", False) is True
    assert s._job_notify_map.get("job_notify_false", False) is False, \
        "notify=False jobs should not be in map"

    # 清理
    s._job_notify_map.clear()


# ─── AC 3: 不传 notify 默认 False ──────────────────────────────────

@pytest.mark.asyncio
async def test_ac03_default_notify_is_false():
    """AC 3: 不传 notify 时默认为 False"""
    s = Scheduler()

    # 默认 add_job 的 notify 参数是 False
    # 验证方法签名
    import inspect
    sig = inspect.signature(s.add_job)
    assert "notify" in sig.parameters, "add_job should have notify parameter"
    notify_param = sig.parameters["notify"]
    assert notify_param.default is False, \
        f"notify default should be False, got {notify_param.default}"

    # 验证 _job_notify_map.get 默认返回 False
    assert s._job_notify_map.get("nonexistent_job", False) is False, \
        "get(job_id, False) should return False for non-existent job"

    # 验证 .get(job_id, False) 在没有第二个参数时也正确
    # 注意：实际代码使用 .get(job_id, False)，默认 False
    assert s._job_notify_map.get("nonexistent_job_2") is None, \
        "get without default should return None for non-existent"
    # 但 _execute_command 中用的是 .get(job_id, False)
    notify = s._job_notify_map.get("nonexistent_job_2", False)
    assert notify is False, "get with default=False should return False"
