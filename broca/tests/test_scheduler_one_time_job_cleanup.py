"""Regression tests: one-shot (date) job cleanup must not log spurious errors.

APScheduler removes ``date``-trigger jobs from its job store immediately after
they fire (``BaseScheduler._process_jobs``). The scheduler's async cleanup runs
later, after the child process finishes, so ``remove_job()`` reliably raises
``JobLookupError``. That is the expected path, not a failure.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from apscheduler.jobstores.base import JobLookupError


@pytest.fixture
def scheduler_env(monkeypatch):
    """Scheduler singleton with mocked services, APScheduler and logger."""
    from broca.scheduler import Scheduler

    s = Scheduler()
    monkeypatch.setattr(s, "job_service", MagicMock())
    monkeypatch.setattr(s, "execution_service", MagicMock())
    monkeypatch.setattr(s, "apscheduler", MagicMock())

    # 项目使用 loguru bound logger，caplog 捕获不到；用 mock 断言告警。
    mock_logger = MagicMock()
    monkeypatch.setattr("broca.scheduler.logger", mock_logger)
    return s, mock_logger


def _date_job():
    job = MagicMock()
    job.trigger_type = "date"
    return job


@pytest.mark.asyncio
async def test_cleanup_one_time_job_already_auto_removed(scheduler_env):
    """AC: JobLookupError is a no-op; completion and DB update still happen."""
    s, mock_logger = scheduler_env
    s.job_service.get = AsyncMock(return_value=_date_job())
    s.job_service.complete_job = AsyncMock()
    s.apscheduler.remove_job.side_effect = JobLookupError("job_123")

    await s._cleanup_one_time_job("job_123")

    s.job_service.complete_job.assert_awaited_once_with("job_123")
    mock_logger.warning.assert_not_called()
    mock_logger.debug.assert_called_once()


@pytest.mark.asyncio
async def test_cleanup_one_time_job_removes_present_job(scheduler_env):
    """AC: a still-present job is removed normally without warnings."""
    s, mock_logger = scheduler_env
    s.job_service.get = AsyncMock(return_value=_date_job())
    s.job_service.complete_job = AsyncMock()
    s.apscheduler.remove_job.return_value = None

    await s._cleanup_one_time_job("job_456")

    s.apscheduler.remove_job.assert_called_once_with("job_456")
    mock_logger.warning.assert_not_called()


@pytest.mark.asyncio
async def test_cleanup_one_time_job_ignores_recurring_job(scheduler_env):
    """AC: cron/interval jobs are left in the scheduler and DB active."""
    s, _ = scheduler_env
    job = MagicMock()
    job.trigger_type = "cron"
    s.job_service.get = AsyncMock(return_value=job)
    s.job_service.complete_job = AsyncMock()

    await s._cleanup_one_time_job("job_cron")

    s.job_service.complete_job.assert_not_awaited()
    s.apscheduler.remove_job.assert_not_called()


@pytest.mark.asyncio
async def test_cleanup_one_time_job_still_warns_on_real_error(scheduler_env):
    """AC: unexpected scheduler errors are still reported as warnings."""
    s, mock_logger = scheduler_env
    s.job_service.get = AsyncMock(return_value=_date_job())
    s.job_service.complete_job = AsyncMock()
    s.apscheduler.remove_job.side_effect = RuntimeError("boom")

    await s._cleanup_one_time_job("job_789")

    mock_logger.warning.assert_called_once()
    assert "Failed to remove one-time job" in mock_logger.warning.call_args[0][0]


@pytest.mark.asyncio
async def test_public_remove_job_handles_auto_removed_job(scheduler_env):
    """AC: public remove_job() also treats a missing date job as success."""
    s, mock_logger = scheduler_env
    s.apscheduler.remove_job.side_effect = JobLookupError("job_abc")
    s.job_service.delete = AsyncMock(return_value=True)

    result = await s.remove_job("job_abc")

    assert result is True
    mock_logger.warning.assert_not_called()
