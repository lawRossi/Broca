"""Integration tests for session runner API endpoints.

Tests /api/session/runners, /api/session/{id}/runner/* endpoints.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


class TestListRunnersAPI:
    """Test GET /api/session/runners."""

    @pytest.mark.asyncio
    async def test_list_runners(self, async_client: AsyncClient, auth_headers: dict):
        """List runners should return stats."""
        with patch("app.api.session_runner.RunnerManager") as mock_runner_manager_cls:
            mock_runner_manager = MagicMock()
            mock_runner_manager.get_stats.return_value = {
                "total_runners": 2,
                "active_runners": 1,
                "max_runners": 10,
            }
            mock_runner_manager_cls.return_value = mock_runner_manager

            response = await async_client.get("/api/session/runners", headers=auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 200
            assert data["data"]["total_runners"] == 2
# But due to routing order, they are unreachable. We test the /{session_id}/runner/* endpoints below.


class TestGetRunnerStatusAPI:
    """Test GET /api/session/{session_id}/runner/status."""

    @pytest.mark.asyncio
    async def test_get_runner_status_found(self, async_client: AsyncClient, auth_headers: dict):
        """Existing runner should return status."""
        with patch("app.api.session_runner.RunnerManager") as mock_runner_manager_cls:
            mock_runner_manager = MagicMock()
            mock_runner_manager.get_status.return_value = {
                "session_id": "test-session-001",
                "status": "running",
                "pid": 12345,
            }
            mock_runner_manager_cls.return_value = mock_runner_manager

            response = await async_client.get(
                "/api/session/test-session-001/runner/status",
                headers=auth_headers,
            )
            assert response.status_code == 200
            data = response.json()
            assert data["data"]["status"] == "running"

    @pytest.mark.asyncio
    async def test_get_runner_status_not_found(self, async_client: AsyncClient, auth_headers: dict):
        """Non-existent runner should return status 'none'."""
        with patch("app.api.session_runner.RunnerManager") as mock_runner_manager_cls:
            mock_runner_manager = MagicMock()
            mock_runner_manager.get_status.return_value = None
            mock_runner_manager_cls.return_value = mock_runner_manager

            response = await async_client.get(
                "/api/session/nonexistent/runner/status",
                headers=auth_headers,
            )
            assert response.status_code == 200
            data = response.json()
            assert data["data"]["status"] == "none"


class TestRestartRunnerAPI:
    """Test POST /api/session/{session_id}/runner/restart."""

    @pytest.mark.asyncio
    async def test_restart_runner(self, async_client: AsyncClient, auth_headers: dict):
        """Restart runner 应停止旧进程并在后台启动新进程，立即返回 starting。"""
        with (
            patch("app.api.session_runner.RunnerManager") as mock_runner_manager_cls,
            patch("broca.session.SessionManager") as mock_sm_cls,
        ):
            mock_runner_manager = MagicMock()
            mock_runner_manager.stop_session = AsyncMock(return_value=True)
            mock_runner_manager.start_session = AsyncMock()
            mock_runner_manager_cls.return_value = mock_runner_manager

            session = MagicMock()
            session.workspace = "/tmp/test-workspace"
            mock_sm_cls.return_value.get_session = AsyncMock(return_value=session)

            response = await async_client.post(
                "/api/session/test-session-001/runner/restart",
                headers=auth_headers,
            )
            # 让后台 _start_bg 任务有机会执行
            await asyncio.sleep(0)

            assert response.status_code == 200
            data = response.json()
            assert data["data"]["session_id"] == "test-session-001"
            assert data["data"]["status"] == "starting"
            mock_runner_manager.stop_session.assert_awaited_once_with(
                "test-session-001"
            )


class TestStopRunnerAPI:
    """Test POST /api/session/{session_id}/runner/stop."""

    @pytest.mark.asyncio
    async def test_stop_runner(self, async_client: AsyncClient, auth_headers: dict):
        """Stop runner should succeed."""
        with patch("app.api.session_runner.RunnerManager") as mock_runner_manager_cls:
            mock_runner_manager = MagicMock()
            mock_runner_manager.request_stop = AsyncMock(
                return_value={
                    "session_id": "test-session-001",
                    "status": "stopping",
                    "message": "Runner stopping",
                }
            )
            mock_runner_manager.stop_session = AsyncMock(return_value=True)
            mock_runner_manager_cls.return_value = mock_runner_manager

            response = await async_client.post(
                "/api/session/test-session-001/runner/stop",
                headers=auth_headers,
            )
            assert response.status_code == 200
            data = response.json()
            assert data["data"]["status"] == "stopping"
            assert "stopping" in data["msg"].lower()

    @pytest.mark.asyncio
    async def test_stop_runner_no_active(self, async_client: AsyncClient, auth_headers: dict):
        """Stopping non-existent runner should return success message."""
        with patch("app.api.session_runner.RunnerManager") as mock_runner_manager_cls:
            mock_runner_manager = MagicMock()
            mock_runner_manager.request_stop = AsyncMock(
                return_value={
                    "session_id": "nonexistent",
                    "status": "stopped",
                    "message": "No active runner",
                }
            )
            mock_runner_manager.stop_session = AsyncMock(return_value=False)
            mock_runner_manager_cls.return_value = mock_runner_manager

            response = await async_client.post(
                "/api/session/nonexistent/runner/stop",
                headers=auth_headers,
            )
            assert response.status_code == 200
            data = response.json()
            assert data["data"]["status"] == "stopped"
            assert "no runner" in data["msg"].lower()
