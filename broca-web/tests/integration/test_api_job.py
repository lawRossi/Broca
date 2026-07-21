"""Integration tests for job API endpoints.

Tests /api/job/* endpoints for CRUD operations, execution, pause/resume.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


class TestListJobsAPI:
    """Test GET /api/job/jobs."""

    @pytest.mark.asyncio
    async def test_list_jobs(self, async_client: AsyncClient, auth_headers: dict, sample_job):
        """List jobs should return paginated results."""
        with patch("app.api.job.get_job_service") as mock_get_job_service:
            mock_job_svc = MagicMock()
            mock_job_svc.get_batch = AsyncMock(return_value=[sample_job])
            mock_get_job_service.return_value = mock_job_svc

            response = await async_client.get(
                "/api/job/jobs?skip=0&limit=20",
                headers=auth_headers,
            )
            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 200
            assert len(data["data"]["jobs"]) == 1
            assert data["data"]["total"] == 1

    @pytest.mark.asyncio
    async def test_list_jobs_with_filters(self, async_client: AsyncClient, auth_headers: dict, sample_job):
        """List jobs with filters."""
        with patch("app.api.job.get_job_service") as mock_get_job_service:
            mock_job_svc = MagicMock()
            mock_job_svc.get_batch = AsyncMock(return_value=[sample_job])
            mock_get_job_service.return_value = mock_job_svc

            response = await async_client.get(
                "/api/job/jobs?status=active&job_type=scheduled",
                headers=auth_headers,
            )
            assert response.status_code == 200


class TestGetJobDetailAPI:
    """Test GET /api/job/{job_id}."""

    @pytest.mark.asyncio
    async def test_get_job_detail(self, async_client: AsyncClient, auth_headers: dict, sample_job):
        """Job detail should include execution records."""
        with (
            patch("app.api.job.get_job_service") as mock_get_job_service,
            patch("app.api.job.get_job_execution_service") as mock_get_exec_service,
        ):
            mock_job_svc = MagicMock()
            mock_job_svc.get = AsyncMock(return_value=sample_job)
            mock_get_job_service.return_value = mock_job_svc

            mock_exec_svc = MagicMock()
            mock_exec_svc.get_executions_by_job = AsyncMock(return_value=[])
            mock_get_exec_service.return_value = mock_exec_svc

            response = await async_client.get("/api/job/job-001", headers=auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert "job" in data["data"]
            assert "executions" in data["data"]

    @pytest.mark.asyncio
    async def test_get_job_not_found(self, async_client: AsyncClient, auth_headers: dict):
        """Non-existent job should return 404."""
        with patch("app.api.job.get_job_service") as mock_get_job_service:
            mock_job_svc = MagicMock()
            mock_job_svc.get = AsyncMock(return_value=None)
            mock_get_job_service.return_value = mock_job_svc

            response = await async_client.get("/api/job/nonexistent", headers=auth_headers)
            assert response.status_code == 404


class TestJobExecutionsAPI:
    """Test GET /api/job/{job_id}/executions."""

    @pytest.mark.asyncio
    async def test_get_job_executions(self, async_client: AsyncClient, auth_headers: dict):
        """Get job executions should return record list."""
        with (
            patch("app.api.job.get_job_service") as mock_get_job_service,
        ):
            mock_job_svc = MagicMock()
            mock_job_svc.get = AsyncMock(return_value=MagicMock())  # Job exists
            mock_get_job_service.return_value = mock_job_svc

            # db_manager is imported inside the function from broca.session.service
            # which is already patched at conftest level
            from broca.session.service import db_manager

            # Mock async session for direct query
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_session.exec = AsyncMock(return_value=mock_result)
            db_manager.get_session = MagicMock()
            db_manager.get_session.return_value.__aenter__.return_value = mock_session

            response = await async_client.get(
                "/api/job/job-001/executions",
                headers=auth_headers,
            )
            assert response.status_code == 200


class TestJobExecuteNowAPI:
    """Test POST /api/job/{job_id}/execute."""

    @pytest.mark.asyncio
    async def test_execute_job_now(self, async_client: AsyncClient, auth_headers: dict):
        """Execute job now should succeed."""
        # Scheduler is already patched at conftest level as broca.scheduler.Scheduler
        with patch("broca.scheduler.Scheduler.execute_job_now", new_callable=AsyncMock, return_value=True):
            response = await async_client.post(
                "/api/job/job-001/execute",
                headers=auth_headers,
            )
            assert response.status_code == 200


class TestUpdateJobAPI:
    """Test PUT /api/job/{job_id}."""

    @pytest.mark.asyncio
    async def test_update_job(self, async_client: AsyncClient, auth_headers: dict, sample_job):
        """Update job should succeed."""
        with patch("app.api.job.get_job_service") as mock_get_job_service:
            mock_job_svc = MagicMock()
            mock_job_svc.get = AsyncMock(return_value=sample_job)
            mock_job_svc.update = AsyncMock(return_value=sample_job)
            mock_get_job_service.return_value = mock_job_svc

            response = await async_client.put(
                "/api/job/job-001",
                headers=auth_headers,
                json={"name": "Updated Job", "content": "echo updated"},
            )
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_update_job_invalid_fields(self, async_client: AsyncClient, auth_headers: dict, sample_job):
        """Update with invalid fields should return 400."""
        with patch("app.api.job.get_job_service") as mock_get_job_service:
            mock_job_svc = MagicMock()
            mock_job_svc.get = AsyncMock(return_value=sample_job)
            mock_get_job_service.return_value = mock_job_svc

            response = await async_client.put(
                "/api/job/job-001",
                headers=auth_headers,
                json={"invalid_field": "value"},
            )
            assert response.status_code == 400


class TestDeleteJobAPI:
    """Test DELETE /api/job/{job_id}."""

    @pytest.mark.asyncio
    async def test_delete_job(self, async_client: AsyncClient, auth_headers: dict):
        """Delete job should succeed."""
        with patch("broca.scheduler.Scheduler.remove_job", new_callable=AsyncMock, return_value=True):
            response = await async_client.delete("/api/job/job-001", headers=auth_headers)
            assert response.status_code == 200


class TestPauseResumeJobAPI:
    """Test POST /api/job/{job_id}/pause and /api/job/{job_id}/resume."""

    @pytest.mark.asyncio
    async def test_pause_job(self, async_client: AsyncClient, auth_headers: dict):
        """Pause job should succeed."""
        with (
            patch("app.api.job.get_job_service") as mock_get_job_service,
            patch("broca.scheduler.Scheduler") as mock_scheduler_cls,
        ):
            mock_job_svc = MagicMock()
            mock_job_svc.pause_job = AsyncMock(return_value=True)
            mock_get_job_service.return_value = mock_job_svc

            mock_scheduler = MagicMock()
            mock_scheduler.apscheduler.pause_job = MagicMock()
            mock_scheduler_cls.return_value = mock_scheduler

            response = await async_client.post("/api/job/job-001/pause", headers=auth_headers)
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_resume_job(self, async_client: AsyncClient, auth_headers: dict):
        """Resume job should succeed."""
        with (
            patch("app.api.job.get_job_service") as mock_get_job_service,
            patch("broca.scheduler.Scheduler") as mock_scheduler_cls,
        ):
            mock_job_svc = MagicMock()
            mock_job_svc.resume_job = AsyncMock(return_value=True)
            mock_get_job_service.return_value = mock_job_svc

            mock_scheduler = MagicMock()
            mock_scheduler.apscheduler.resume_job = MagicMock()
            mock_scheduler_cls.return_value = mock_scheduler

            response = await async_client.post("/api/job/job-001/resume", headers=auth_headers)
            assert response.status_code == 200
