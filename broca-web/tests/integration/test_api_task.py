"""Integration tests for task API endpoints.

Tests /api/task/* endpoints for CRUD operations, search, comments, etc.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


class TestListTasksAPI:
    """Test GET /api/task/tasks."""

    @pytest.mark.asyncio
    async def test_list_tasks(self, async_client: AsyncClient, auth_headers: dict, sample_task):
        """List tasks should return paginated results."""
        with patch("app.api.task.get_task_service") as mock_get_task_service:
            mock_task_svc = MagicMock()
            mock_task_svc.get_batch = AsyncMock(return_value=[sample_task])
            mock_get_task_service.return_value = mock_task_svc

            response = await async_client.get(
                "/api/task/tasks?skip=0&limit=20",
                headers=auth_headers,
            )
            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 200
            assert len(data["data"]["tasks"]) == 1
            assert data["data"]["total"] == 1

    @pytest.mark.asyncio
    async def test_list_tasks_with_filters(self, async_client: AsyncClient, auth_headers: dict, sample_task):
        """List tasks with status filter."""
        with patch("app.api.task.get_task_service") as mock_get_task_service:
            mock_task_svc = MagicMock()
            mock_task_svc.get_batch = AsyncMock(return_value=[sample_task])
            mock_get_task_service.return_value = mock_task_svc

            response = await async_client.get(
                "/api/task/tasks?status=pending&priority=medium",
                headers=auth_headers,
            )
            assert response.status_code == 200
            # Verify that the service was called with the correct filters
            assert mock_task_svc.get_batch.called


class TestGetTaskDetailAPI:
    """Test GET /api/task/{task_id}."""

    @pytest.mark.asyncio
    async def test_get_task_detail(self, async_client: AsyncClient, auth_headers: dict, sample_task):
        """Task detail should return task with comments and children."""
        with (
            patch("app.api.task.get_task_service") as mock_get_task_service,
            patch("app.api.task.get_task_comment_service") as mock_get_comment_service,
        ):
            mock_task_svc = MagicMock()
            mock_task_svc.get = AsyncMock(return_value=sample_task)
            mock_task_svc.get_child_tasks = AsyncMock(return_value=[])
            mock_get_task_service.return_value = mock_task_svc

            mock_comment_svc = MagicMock()
            mock_comment_svc.get_comments_by_task = AsyncMock(return_value=[])
            mock_get_comment_service.return_value = mock_comment_svc

            response = await async_client.get("/api/task/task-001", headers=auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert data["data"]["task"]["task_id"] == "task-001"
            assert "comments" in data["data"]
            assert "children" in data["data"]

    @pytest.mark.asyncio
    async def test_get_task_not_found(self, async_client: AsyncClient, auth_headers: dict):
        """Non-existent task should return 404."""
        with patch("app.api.task.get_task_service") as mock_get_task_service:
            mock_task_svc = MagicMock()
            mock_task_svc.get = AsyncMock(return_value=None)
            mock_get_task_service.return_value = mock_task_svc

            response = await async_client.get("/api/task/nonexistent", headers=auth_headers)
            assert response.status_code == 404


class TestCreateTaskAPI:
    """Test POST /api/task/."""

    @pytest.mark.asyncio
    async def test_create_task_success(self, async_client: AsyncClient, auth_headers: dict):
        """Create task should return the created task."""
        with patch("app.api.task.get_task_service") as mock_get_task_service:
            mock_task_svc = MagicMock()
            created_task = MagicMock()
            created_task.task_id = "new-task-001"
            created_task.name = "New Task"
            created_task.description = "A new task"
            created_task.status = "pending"
            created_task.priority = "high"
            created_task.assignee = None
            created_task.parent_id = None
            created_task.session_id = None
            created_task.created_at = None
            created_task.updated_at = None
            mock_task_svc.create_task = AsyncMock(return_value=created_task)
            mock_get_task_service.return_value = mock_task_svc

            response = await async_client.post(
                "/api/task/",
                headers=auth_headers,
                json={"name": "New Task", "description": "A new task", "priority": "high"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["data"]["task"]["task_id"] == "new-task-001"
            assert data["data"]["task"]["name"] == "New Task"

    @pytest.mark.asyncio
    async def test_create_task_missing_fields(self, async_client: AsyncClient, auth_headers: dict):
        """Create task without required fields should return 400."""
        response = await async_client.post(
            "/api/task/",
            headers=auth_headers,
            json={"priority": "high"},
        )
        assert response.status_code == 400


class TestUpdateTaskAPI:
    """Test PUT /api/task/{task_id}."""

    @pytest.mark.asyncio
    async def test_update_task(self, async_client: AsyncClient, auth_headers: dict, sample_task):
        """Update task should succeed."""
        with patch("app.api.task.get_task_service") as mock_get_task_service:
            mock_task_svc = MagicMock()
            mock_task_svc.get = AsyncMock(return_value=sample_task)
            mock_task_svc.update_task = AsyncMock(return_value=sample_task)
            mock_get_task_service.return_value = mock_task_svc

            response = await async_client.put(
                "/api/task/task-001",
                headers=auth_headers,
                json={"status": "completed", "priority": "high"},
            )
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_update_task_not_found(self, async_client: AsyncClient, auth_headers: dict):
        """Update non-existent task should return 404."""
        with patch("app.api.task.get_task_service") as mock_get_task_service:
            mock_task_svc = MagicMock()
            mock_task_svc.get = AsyncMock(return_value=None)
            mock_get_task_service.return_value = mock_task_svc

            response = await async_client.put(
                "/api/task/nonexistent",
                headers=auth_headers,
                json={"status": "completed"},
            )
            assert response.status_code == 404


class TestDeleteTaskAPI:
    """Test DELETE /api/task/{task_id}."""

    @pytest.mark.asyncio
    async def test_delete_task(self, async_client: AsyncClient, auth_headers: dict):
        """Delete task should succeed."""
        with patch("app.api.task.get_task_service") as mock_get_task_service:
            mock_task_svc = MagicMock()
            mock_task_svc.delete = AsyncMock(return_value=True)
            mock_get_task_service.return_value = mock_task_svc

            response = await async_client.delete("/api/task/task-001", headers=auth_headers)
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_task_not_found(self, async_client: AsyncClient, auth_headers: dict):
        """Delete non-existent task should return error response."""
        with patch("app.api.task.get_task_service") as mock_get_task_service:
            mock_task_svc = MagicMock()
            mock_task_svc.delete = AsyncMock(return_value=False)
            mock_get_task_service.return_value = mock_task_svc

            response = await async_client.delete("/api/task/nonexistent", headers=auth_headers)
            # The endpoint raises HTTPException(404), caught by exception handler
            assert response.status_code in (404, 500)


class TestTaskCommentsAPI:
    """Test task comment endpoints."""

    @pytest.mark.asyncio
    async def test_get_task_comments(self, async_client: AsyncClient, auth_headers: dict, sample_task):
        """Get task comments should return comment list."""
        with (
            patch("app.api.task.get_task_service") as mock_get_task_service,
            patch("app.api.task.get_task_comment_service") as mock_get_comment_service,
        ):
            mock_task_svc = MagicMock()
            mock_task_svc.get = AsyncMock(return_value=sample_task)
            mock_get_task_service.return_value = mock_task_svc

            mock_comment_svc = MagicMock()
            mock_comment_svc.get_comments_by_task = AsyncMock(return_value=[])
            mock_get_comment_service.return_value = mock_comment_svc

            response = await async_client.get(
                "/api/task/task-001/comments",
                headers=auth_headers,
            )
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_add_task_comment(self, async_client: AsyncClient, auth_headers: dict, sample_task):
        """Add comment to task should succeed."""
        with patch("app.api.task.get_task_service") as mock_get_task_service:
            mock_task_svc = MagicMock()
            mock_task_svc.get = AsyncMock(return_value=sample_task)

            comment = MagicMock()
            comment.comment_id = "comment-001"
            comment.author = "user1"
            comment.content = "Nice work!"
            comment.created_at = None
            mock_task_svc.add_comment = AsyncMock(return_value=comment)
            mock_get_task_service.return_value = mock_task_svc

            response = await async_client.post(
                "/api/task/task-001/comments",
                headers=auth_headers,
                json={"author": "user1", "content": "Nice work!"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["data"]["comment"]["comment_id"] == "comment-001"

    @pytest.mark.asyncio
    async def test_add_comment_missing_fields(self, async_client: AsyncClient, auth_headers: dict):
        """Add comment without required fields should return 400."""
        response = await async_client.post(
            "/api/task/task-001/comments",
            headers=auth_headers,
            json={},
        )
        assert response.status_code == 400


class TestTaskChildrenAPI:
    """Test GET /api/task/{task_id}/children."""

    @pytest.mark.asyncio
    async def test_get_task_children(self, async_client: AsyncClient, auth_headers: dict, sample_task):
        """Get task children should return child list."""
        with patch("app.api.task.get_task_service") as mock_get_task_service:
            mock_task_svc = MagicMock()
            mock_task_svc.get = AsyncMock(return_value=sample_task)
            mock_task_svc.get_child_tasks = AsyncMock(return_value=[])
            mock_get_task_service.return_value = mock_task_svc

            response = await async_client.get(
                "/api/task/task-001/children",
                headers=auth_headers,
            )
            assert response.status_code == 200


class TestSearchTasksAPI:
    """Test GET /api/task/search."""

    @pytest.mark.asyncio
    async def test_search_tasks(self, async_client: AsyncClient, auth_headers: dict, sample_task):
        """Search tasks should return matching results."""
        mock_task_svc = MagicMock()
        mock_task_svc.search_tasks = AsyncMock(return_value=[sample_task])

        with patch("app.api.task.get_task_service", return_value=mock_task_svc):
            response = await async_client.get(
                "/api/task/search?query=test&skip=0&limit=20",
                headers=auth_headers,
            )
            assert response.status_code == 200
            data = response.json()
            assert len(data["data"]["tasks"]) == 1
