"""Integration tests for session API endpoints.

Tests /api/session/* endpoints for CRUD operations, message queries, and stats.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


class TestCreateSessionAPI:
    """Test POST /api/session/sessions."""

    @pytest.mark.asyncio
    async def test_create_session_success(self, async_client: AsyncClient, auth_headers: dict):
        """Create a new session successfully."""
        with (
            patch("app.api.session.AgentFactory") as mock_agent_factory_cls,
            patch("app.api.session.get_session_service") as mock_get_session_service,
            patch("app.api.session.asyncio.create_task") as mock_create_task,
        ):
            mock_factory = MagicMock()
            mock_agent_factory_cls.return_value = mock_factory
            mock_factory.init_session_agents = AsyncMock(
                return_value=([MagicMock()], "test-session-001")
            )

            mock_session_svc = MagicMock()
            mock_session_svc.update = AsyncMock()
            mock_get_session_service.return_value = mock_session_svc

            # Mock background task
            mock_task = MagicMock()
            mock_create_task.return_value = mock_task
            mock_task.add_done_callback = MagicMock()

            response = await async_client.post(
                "/api/session/sessions",
                headers=auth_headers,
                json={"description": "Test session", "category": "normal"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 200
            assert data["data"]["session_id"] == "test-session-001"
            assert data["data"]["description"] == "Test session"
            assert data["data"]["category"] == "normal"

    @pytest.mark.asyncio
    async def test_create_session_no_agents(self, async_client: AsyncClient, auth_headers: dict):
        """Creating session without agents should fail."""
        with patch("app.api.session.AgentFactory") as mock_agent_factory_cls:
            mock_factory = MagicMock()
            mock_agent_factory_cls.return_value = mock_factory
            mock_factory.init_session_agents = AsyncMock(return_value=([], "test-session-001"))

            with patch("app.api.session.get_session_service") as mock_get_session_service:
                mock_session_svc = MagicMock()
                mock_session_svc.delete = AsyncMock()
                mock_get_session_service.return_value = mock_session_svc

                response = await async_client.post(
                    "/api/session/sessions",
                    headers=auth_headers,
                    json={"description": "Empty session"},
                )

                assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_create_session_invalid_workspace(self, async_client: AsyncClient, auth_headers: dict):
        """Invalid workspace path should return 400."""
        response = await async_client.post(
            "/api/session/sessions",
            headers=auth_headers,
            json={"workspace": "/nonexistent/path"},
        )

        assert response.status_code == 400


class TestListSessionsAPI:
    """Test GET /api/session/sessions."""

    @pytest.mark.asyncio
    async def test_list_sessions(self, async_client: AsyncClient, auth_headers: dict, sample_session):
        """List sessions should return paginated results."""
        with (
            patch("app.api.session.get_session_service") as mock_get_session_service,
            patch("app.api.session.RunnerManager") as mock_runner_manager_cls,
        ):
            mock_session_svc = MagicMock()
            mock_session_svc.get_batch = AsyncMock(return_value=[sample_session])
            mock_get_session_service.return_value = mock_session_svc

            mock_runner_manager = MagicMock()
            mock_runner_manager.get_session_status.return_value = {"status": "running"}
            mock_runner_manager_cls.return_value = mock_runner_manager

            response = await async_client.get(
                "/api/session/sessions?skip=0&limit=20",
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 200
            assert len(data["data"]["sessions"]) == 1
            assert data["data"]["total"] == 1

    @pytest.mark.asyncio
    async def test_list_sessions_with_keyword(self, async_client: AsyncClient, auth_headers: dict, sample_session):
        """Keyword filter should work."""
        with (
            patch("app.api.session.get_session_service") as mock_get_session_service,
            patch("app.api.session.RunnerManager") as mock_runner_manager_cls,
        ):
            mock_session_svc = MagicMock()
            mock_session_svc.get_batch = AsyncMock(return_value=[sample_session])
            mock_get_session_service.return_value = mock_session_svc

            mock_runner_manager = MagicMock()
            mock_runner_manager.get_session_status.return_value = {"status": "running"}
            mock_runner_manager_cls.return_value = mock_runner_manager

            # Search with matching keyword
            response = await async_client.get(
                "/api/session/sessions?keyword=Test+session",
                headers=auth_headers,
            )
            assert response.status_code == 200

            # Search with non-matching keyword
            response = await async_client.get(
                "/api/session/sessions?keyword=nonexistent",
                headers=auth_headers,
            )
            assert response.status_code == 200
            assert len(response.json()["data"]["sessions"]) == 0


class TestGetSessionAPI:
    """Test GET /api/session/{session_id}."""

    @pytest.mark.asyncio
    async def test_get_session_found(self, async_client: AsyncClient, auth_headers: dict, sample_session):
        """Existing session should be returned."""
        with (
            patch("app.api.session.get_session_service") as mock_get_session_service,
            patch("app.api.session.RunnerManager") as mock_runner_manager_cls,
        ):
            mock_session_svc = MagicMock()
            mock_session_svc.get = AsyncMock(return_value=sample_session)
            mock_get_session_service.return_value = mock_session_svc

            mock_runner_manager = MagicMock()
            mock_runner_manager.get_session_status.return_value = {"status": "running"}
            mock_runner_manager_cls.return_value = mock_runner_manager

            response = await async_client.get(
                "/api/session/test-session-001",
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert data["data"]["session_id"] == "test-session-001"
            assert data["data"]["runner_status"] == "running"

    @pytest.mark.asyncio
    async def test_get_session_not_found(self, async_client: AsyncClient, auth_headers: dict):
        """Non-existent session should return 404."""
        with patch("app.api.session.get_session_service") as mock_get_session_service:
            mock_session_svc = MagicMock()
            mock_session_svc.get = AsyncMock(return_value=None)
            mock_get_session_service.return_value = mock_session_svc

            response = await async_client.get(
                "/api/session/nonexistent",
                headers=auth_headers,
            )

            assert response.status_code == 404


class TestDeleteSessionAPI:
    """Test DELETE /api/session/{session_id} and /api/session/sessions."""

    @pytest.mark.asyncio
    async def test_delete_session_success(self, async_client: AsyncClient, auth_headers: dict, sample_session):
        """Delete session should stop runner and remove from DB."""
        with (
            patch("app.api.session.get_session_service") as mock_get_session_service,
            patch("app.api.session.RunnerManager") as mock_runner_manager_cls,
        ):
            mock_session_svc = MagicMock()
            mock_session_svc.get = AsyncMock(return_value=sample_session)
            mock_session_svc.delete = AsyncMock(return_value=True)
            mock_get_session_service.return_value = mock_session_svc

            mock_runner_manager = MagicMock()
            mock_runner_manager.stop_session = AsyncMock(return_value=True)
            mock_runner_manager_cls.return_value = mock_runner_manager

            response = await async_client.delete(
                "/api/session/test-session-001",
                headers=auth_headers,
            )

            assert response.status_code == 200
            assert mock_runner_manager.stop_session.called
            assert mock_session_svc.delete.called

    @pytest.mark.asyncio
    async def test_delete_session_not_found(self, async_client: AsyncClient, auth_headers: dict):
        """Delete non-existent session should return 404."""
        with patch("app.api.session.get_session_service") as mock_get_session_service:
            mock_session_svc = MagicMock()
            mock_session_svc.get = AsyncMock(return_value=None)
            mock_get_session_service.return_value = mock_session_svc

            response = await async_client.delete(
                "/api/session/nonexistent",
                headers=auth_headers,
            )
            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_batch_delete_sessions(self, async_client: AsyncClient, auth_headers: dict):
        """Batch delete should work."""
        with (
            patch("app.api.session.get_session_service") as mock_get_session_service,
            patch("app.api.session.RunnerManager") as mock_runner_manager_cls,
        ):
            mock_session_svc = MagicMock()
            mock_session_svc.delete_batch = AsyncMock(return_value=2)
            mock_get_session_service.return_value = mock_session_svc

            mock_runner_manager = MagicMock()
            mock_runner_manager.stop_session = AsyncMock(return_value=True)
            mock_runner_manager_cls.return_value = mock_runner_manager

            response = await async_client.request(
                "DELETE",
                "/api/session/sessions",
                headers=auth_headers,
                json={"session_ids": ["session-1", "session-2"]},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["data"]["deleted_count"] == 2


class TestUpdateSessionAPI:
    """Test PUT /api/session/{session_id}."""

    @pytest.mark.asyncio
    async def test_update_session_description(self, async_client: AsyncClient, auth_headers: dict, sample_session):
        """Update session description."""
        with patch("app.api.session.get_session_service") as mock_get_session_service:
            mock_session_svc = MagicMock()
            mock_session_svc.get = AsyncMock(return_value=sample_session)
            mock_session_svc.update = AsyncMock()
            mock_get_session_service.return_value = mock_session_svc

            response = await async_client.put(
                "/api/session/test-session-001",
                headers=auth_headers,
                json={"description": "Updated description"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["data"]["description"] == "Updated description"


class TestSessionMessagesAPI:
    """Test GET /api/session/{session_id}/messages."""

    @pytest.mark.asyncio
    async def test_get_messages(self, async_client: AsyncClient, auth_headers: dict, sample_session):
        """Get messages should return paginated results."""
        with (
            patch("app.api.session.get_session_service") as mock_get_session_service,
            patch("app.api.session.get_message_service") as mock_get_message_service,
        ):
            mock_session_svc = MagicMock()
            mock_session_svc.get = AsyncMock(return_value=sample_session)
            mock_get_session_service.return_value = mock_session_svc

            mock_msg_svc = MagicMock()
            mock_msg_svc.count = AsyncMock(return_value=0)
            mock_msg_svc.get_messages_by_session = AsyncMock(return_value=[])
            mock_get_message_service.return_value = mock_msg_svc

            response = await async_client.get(
                "/api/session/test-session-001/messages",
                headers=auth_headers,
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_messages_not_found(self, async_client: AsyncClient, auth_headers: dict):
        """Non-existent session should return 404."""
        with patch("app.api.session.get_session_service") as mock_get_session_service:
            mock_session_svc = MagicMock()
            mock_session_svc.get = AsyncMock(return_value=None)
            mock_get_session_service.return_value = mock_session_svc

            response = await async_client.get(
                "/api/session/nonexistent/messages",
                headers=auth_headers,
            )
            assert response.status_code == 404


class TestSessionSearchAPI:
    """Test GET /api/session/{session_id}/messages/search."""

    @pytest.mark.asyncio
    async def test_search_messages(self, async_client: AsyncClient, auth_headers: dict, sample_session):
        """Search messages should return results."""
        with (
            patch("app.api.session.get_session_service") as mock_get_session_service,
            patch("app.api.session.get_message_service") as mock_get_message_service,
        ):
            mock_session_svc = MagicMock()
            mock_session_svc.get = AsyncMock(return_value=sample_session)
            mock_get_session_service.return_value = mock_session_svc

            mock_msg_svc = MagicMock()
            mock_msg_svc.search_messages = AsyncMock(return_value=([], 0))
            mock_get_message_service.return_value = mock_msg_svc

            response = await async_client.get(
                "/api/session/test-session-001/messages/search?keyword=hello",
                headers=auth_headers,
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_search_filters(self, async_client: AsyncClient, auth_headers: dict, sample_session):
        """Search filters should return available options."""
        with (
            patch("app.api.session.get_session_service") as mock_get_session_service,
            patch("app.api.session.get_message_service") as mock_get_message_service,
        ):
            mock_session_svc = MagicMock()
            mock_session_svc.get = AsyncMock(return_value=sample_session)
            mock_get_session_service.return_value = mock_session_svc

            mock_msg_svc = MagicMock()
            mock_msg_svc.get_distinct_tool_names = AsyncMock(return_value=["bash", "read_file"])
            mock_get_message_service.return_value = mock_msg_svc

            response = await async_client.get(
                "/api/session/test-session-001/messages/search/filters",
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert "tool_names" in data["data"]


class TestSessionStatsAPI:
    """Test GET /api/session/{session_id}/stats."""

    @pytest.mark.asyncio
    async def test_get_stats(self, async_client: AsyncClient, auth_headers: dict, sample_session):
        """Get session stats."""
        with (
            patch("app.api.session.get_session_service") as mock_get_session_service,
            patch("app.api.session.get_message_service") as mock_get_message_service,
            patch("app.api.session.RunnerManager") as mock_runner_manager_cls,
        ):
            mock_session_svc = MagicMock()
            mock_session_svc.get = AsyncMock(return_value=sample_session)
            mock_get_session_service.return_value = mock_session_svc

            mock_msg_svc = MagicMock()
            mock_msg_svc.get_message_stats_by_session = AsyncMock(
                return_value={"total_messages": 10, "user_messages": 5}
            )
            mock_get_message_service.return_value = mock_msg_svc

            mock_runner_manager = MagicMock()
            mock_runner_manager.get_session_status.return_value = {"status": "running"}
            mock_runner_manager_cls.return_value = mock_runner_manager

            response = await async_client.get(
                "/api/session/test-session-001/stats",
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert data["data"]["total_messages"] == 10
            assert data["data"]["runner"]["status"] == "running"


class TestSessionTurnsAPI:
    """Test GET /api/session/{session_id}/turns."""

    @pytest.mark.asyncio
    async def test_get_turns(self, async_client: AsyncClient, auth_headers: dict, sample_session):
        """Get turns should return turn list."""
        with (
            patch("app.api.session.get_session_service") as mock_get_session_service,
            patch("app.api.session.get_turn_service") as mock_get_turn_service,
            patch("app.api.session.get_agent_service") as mock_get_agent_service,
        ):
            mock_session_svc = MagicMock()
            mock_session_svc.get = AsyncMock(return_value=sample_session)
            mock_get_session_service.return_value = mock_session_svc

            mock_turn_svc = MagicMock()
            mock_turn_svc.count_turns_by_session = AsyncMock(return_value=0)
            mock_turn_svc.get_turns_by_session = AsyncMock(return_value=[])
            mock_turn_svc.get_turn_time_range = AsyncMock(return_value=(None, None))
            mock_turn_svc.get_turn_stats = AsyncMock(
                return_value={
                    "is_reverted": False,
                    "user_message": None,
                    "total_steps": 0,
                    "tool_call_stats": {},
                    "current_file_path": None,
                    "current_todo_list": [],
                    "final_response": None,
                    "last_message_id": None,
                    "changed_files": {},
                }
            )
            mock_get_turn_service.return_value = mock_turn_svc

            mock_agent_svc = MagicMock()
            mock_agent_svc.get = AsyncMock(return_value=None)
            mock_get_agent_service.return_value = mock_agent_svc

            response = await async_client.get(
                "/api/session/test-session-001/turns",
                headers=auth_headers,
            )
            assert response.status_code == 200


class TestSessionAgentsAPI:
    """Test GET /api/session/{session_id}/agents."""

    @pytest.mark.asyncio
    async def test_get_agents(self, async_client: AsyncClient, auth_headers: dict, sample_agent):
        """Get agents should return agent list."""
        with patch("app.api.session.get_agent_service") as mock_get_agent_service:
            mock_agent_svc = MagicMock()
            # Create an agent with proper model_dump
            agent_mock = MagicMock()
            agent_mock.model_dump.return_value = {
                "agent_id": "agent-001",
                "session_id": "test-session-001",
                "name": "Test Agent",
                "role": "assistant",
                "config_id": "config-001",
                "agent_status": "idle",
            }
            # Also support dict access for the "agent_status" fallback
            agent_mock.agent_status = "idle"
            mock_agent_svc.get_agents_by_session = AsyncMock(return_value=[agent_mock])
            mock_get_agent_service.return_value = mock_agent_svc

            response = await async_client.get(
                "/api/session/test-session-001/agents",
                headers=auth_headers,
            )
            assert response.status_code == 200
            data = response.json()
            assert len(data["data"]) == 1
            assert data["data"][0]["status"] == "idle"


class TestSessionAgentConfigAPI:
    """Test agent config endpoints."""

    @pytest.mark.asyncio
    async def test_get_agent_config(
        self, async_client: AsyncClient, auth_headers: dict, sample_session, sample_agent, sample_agent_config
    ):
        """Get agent config should return config details."""
        with (
            patch("app.api.session.get_session_service") as mock_get_session_service,
            patch("app.api.session.get_agent_service") as mock_get_agent_service,
            patch("app.api.session.get_agent_config_service") as mock_get_agent_config_service,
        ):
            mock_session_svc = MagicMock()
            mock_session_svc.get = AsyncMock(return_value=sample_session)
            mock_get_session_service.return_value = mock_session_svc

            mock_agent_svc = MagicMock()
            mock_agent_svc.get = AsyncMock(return_value=sample_agent)
            mock_get_agent_service.return_value = mock_agent_svc

            mock_config_svc = MagicMock()
            mock_config_svc.get = AsyncMock(return_value=sample_agent_config)
            mock_get_agent_config_service.return_value = mock_config_svc

            response = await async_client.get(
                "/api/session/test-session-001/agents/agent-001/config",
                headers=auth_headers,
            )
            assert response.status_code == 200
            data = response.json()
            assert "config_content" in data["data"]
            assert data["data"]["agent_id"] == "agent-001"

    @pytest.mark.asyncio
    async def test_get_agent_config_wrong_session(
        self, async_client: AsyncClient, auth_headers: dict, sample_session
    ):
        """Agent from wrong session should return 400."""
        with (
            patch("app.api.session.get_session_service") as mock_get_session_service,
            patch("app.api.session.get_agent_service") as mock_get_agent_service,
        ):
            mock_session_svc = MagicMock()
            mock_session_svc.get = AsyncMock(return_value=sample_session)
            mock_get_session_service.return_value = mock_session_svc

            wrong_agent = MagicMock()
            wrong_agent.session_id = "different-session"
            mock_agent_svc = MagicMock()
            mock_agent_svc.get = AsyncMock(return_value=wrong_agent)
            mock_get_agent_service.return_value = mock_agent_svc

            response = await async_client.get(
                "/api/session/test-session-001/agents/agent-001/config",
                headers=auth_headers,
            )
            assert response.status_code == 400


class TestSessionFileDiffAPI:
    """Test GET /api/session/{session_id}/turns/{turn_id}/file-diff."""

    @pytest.mark.asyncio
    async def test_get_file_diff(
        self, async_client: AsyncClient, auth_headers: dict, sample_session
    ):
        """Get file diff should return diff content."""
        with (
            patch("app.api.session.get_session_service") as mock_get_session_service,
            patch("app.api.session.get_turn_service") as mock_get_turn_service,
        ):
            mock_session_svc = MagicMock()
            mock_session_svc.get = AsyncMock(return_value=sample_session)
            mock_get_session_service.return_value = mock_session_svc

            mock_turn_svc = MagicMock()
            mock_turn_svc.get_file_diff = AsyncMock(
                return_value="--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new"
            )
            mock_get_turn_service.return_value = mock_turn_svc

            response = await async_client.get(
                "/api/session/test-session-001/turns/turn-001/file-diff?path=/tmp/file.py",
                headers=auth_headers,
            )
            assert response.status_code == 200
            data = response.json()
            assert "diff" in data["data"]
            assert "+new" in data["data"]["diff"]
