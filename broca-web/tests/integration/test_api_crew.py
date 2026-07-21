"""Integration tests for crew API endpoints.

Tests /api/crews/* endpoints for submission, validation, listing, abort, etc.
"""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


class TestSubmitCrewAPI:
    """Test POST /api/crews."""

    @pytest.mark.asyncio
    async def test_submit_crew_from_yaml(self, async_client: AsyncClient, auth_headers: dict):
        """Submit crew from YAML content should succeed."""
        yaml_content = """
name: test_crew
description: A test crew
agents:
  - name: agent1
    role: assistant
orchestrator:
  type: pipeline
"""

        with patch("app.api.crew.get_crew_service") as mock_get_crew_service:
            mock_service = MagicMock()
            mock_service.submit_crew_from_yaml = AsyncMock(
                return_value={
                    "execution_id": "crew-exec-001",
                    "status": "running",
                    "crew_name": "test_crew",
                }
            )
            mock_get_crew_service.return_value = mock_service

            response = await async_client.post(
                "/api/crews",
                headers=auth_headers,
                json={"yaml_content": yaml_content, "session_id": "test-session-001"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 200
            assert data["data"]["execution_id"] == "crew-exec-001"

    @pytest.mark.asyncio
    async def test_submit_crew_no_content(self, async_client: AsyncClient, auth_headers: dict):
        """Submit without yaml_content or yaml_path should return 400."""
        response = await async_client.post(
            "/api/crews",
            headers=auth_headers,
            json={"session_id": "test-session-001"},
        )
        assert response.status_code == 200  # Returns ApiResponse.error, not HTTPException
        data = response.json()
        assert data["code"] == 400

    @pytest.mark.asyncio
    async def test_submit_crew_validation_error(self, async_client: AsyncClient, auth_headers: dict):
        """Submit with invalid config should return error."""
        with patch("app.api.crew.get_crew_service") as mock_get_crew_service:
            mock_service = MagicMock()
            mock_service.submit_crew_from_yaml = AsyncMock(side_effect=ValueError("Invalid config"))
            mock_get_crew_service.return_value = mock_service

            response = await async_client.post(
                "/api/crews",
                headers=auth_headers,
                json={"yaml_content": "invalid: yaml", "session_id": "test-session-001"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 400


class TestValidateCrewAPI:
    """Test POST /api/crews/validate."""

    @pytest.mark.asyncio
    async def test_validate_valid_crew(self, async_client: AsyncClient, auth_headers: dict):
        """Valid YAML should pass validation."""
        with patch("app.api.crew.get_crew_service") as mock_get_crew_service:
            mock_service = MagicMock()
            mock_service.validate_crew_yaml = MagicMock(return_value=[])
            mock_get_crew_service.return_value = mock_service

            response = await async_client.post(
                "/api/crews/validate",
                headers=auth_headers,
                json={"yaml_content": "name: valid\nagents: []"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["data"]["valid"] is True
            assert data["data"]["error_count"] == 0

    @pytest.mark.asyncio
    async def test_validate_invalid_crew(self, async_client: AsyncClient, auth_headers: dict):
        """Invalid YAML should return errors."""
        with patch("app.api.crew.get_crew_service") as mock_get_crew_service:
            mock_service = MagicMock()
            mock_service.validate_crew_yaml = MagicMock(return_value=["Agent not found", "Missing orchestrator"])
            mock_get_crew_service.return_value = mock_service

            response = await async_client.post(
                "/api/crews/validate",
                headers=auth_headers,
                json={"yaml_content": "name: invalid"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["data"]["valid"] is False
            assert data["data"]["error_count"] == 2


class TestListCrewExecutionsAPI:
    """Test GET /api/crews."""

    @pytest.mark.asyncio
    async def test_list_executions(self, async_client: AsyncClient, auth_headers: dict):
        """List executions should return records."""
        with patch("app.api.crew.get_crew_service") as mock_get_crew_service:
            mock_service = MagicMock()
            mock_service.list_executions = AsyncMock(
                return_value=[
                    {"execution_id": "exec-001", "status": "completed"},
                    {"execution_id": "exec-002", "status": "running"},
                ]
            )
            mock_get_crew_service.return_value = mock_service

            response = await async_client.get("/api/crews", headers=auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert data["data"]["total"] == 2

    @pytest.mark.asyncio
    async def test_list_executions_filtered(self, async_client: AsyncClient, auth_headers: dict):
        """List executions with filters."""
        with patch("app.api.crew.get_crew_service") as mock_get_crew_service:
            mock_service = MagicMock()
            mock_service.list_executions = AsyncMock(return_value=[])
            mock_get_crew_service.return_value = mock_service

            response = await async_client.get(
                "/api/crews?session_id=test-session-001&status=running",
                headers=auth_headers,
            )
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_crew_configs(self, async_client: AsyncClient, auth_headers: dict):
        """List crew configs in workspace."""
        with patch("app.api.crew.get_crew_service") as mock_get_crew_service:
            mock_service = MagicMock()
            mock_service.list_crew_configs = MagicMock(
                return_value=[
                    {"filename": "test.yaml", "name": "test_crew"},
                ]
            )
            mock_get_crew_service.return_value = mock_service

            response = await async_client.get(
                "/api/crews/configs?workspace=/tmp",
                headers=auth_headers,
            )
            assert response.status_code == 200
            data = response.json()
            assert data["data"]["total"] == 1


class TestGetCrewExecutionAPI:
    """Test GET /api/crews/{execution_id}."""

    @pytest.mark.asyncio
    async def test_get_execution_found(self, async_client: AsyncClient, auth_headers: dict):
        """Existing execution should be returned."""
        with patch("app.api.crew.get_crew_service") as mock_get_crew_service:
            mock_service = MagicMock()
            mock_service.get_execution = AsyncMock(
                return_value={"execution_id": "exec-001", "status": "completed"}
            )
            mock_get_crew_service.return_value = mock_service

            response = await async_client.get("/api/crews/exec-001", headers=auth_headers)
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_execution_not_found(self, async_client: AsyncClient, auth_headers: dict):
        """Non-existent execution should return 404."""
        with patch("app.api.crew.get_crew_service") as mock_get_crew_service:
            mock_service = MagicMock()
            mock_service.get_execution = AsyncMock(return_value=None)
            mock_get_crew_service.return_value = mock_service

            response = await async_client.get("/api/crews/nonexistent", headers=auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 404


class TestAbortCrewExecutionAPI:
    """Test POST /api/crews/{execution_id}/abort."""

    @pytest.mark.asyncio
    async def test_abort_execution(self, async_client: AsyncClient, auth_headers: dict):
        """Abort execution should succeed."""
        with patch("app.api.crew.get_crew_service") as mock_get_crew_service:
            mock_service = MagicMock()
            mock_service.abort_execution = AsyncMock(return_value=(True, "Aborted successfully"))
            mock_get_crew_service.return_value = mock_service

            response = await async_client.post("/api/crews/exec-001/abort", headers=auth_headers)
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_abort_not_found(self, async_client: AsyncClient, auth_headers: dict):
        """Abort non-existent execution should return error."""
        with patch("app.api.crew.get_crew_service") as mock_get_crew_service:
            mock_service = MagicMock()
            mock_service.abort_execution = AsyncMock(return_value=(False, "Execution not found"))
            mock_get_crew_service.return_value = mock_service

            response = await async_client.post("/api/crews/nonexistent/abort", headers=auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 400


class TestCrewConfigsDetailAPI:
    """Test GET/PUT /api/crews/configs/{filename}."""

    @pytest.mark.asyncio
    async def test_get_crew_config_detail(self, async_client: AsyncClient, auth_headers: dict):
        """Get crew config detail should return content."""
        with patch("app.api.crew.get_crew_service") as mock_get_crew_service:
            mock_service = MagicMock()
            mock_service.get_crew_config_content = MagicMock(
                return_value={
                    "filename": "test.yaml",
                    "content": "name: test\nagents: []",
                    "summary": {"name": "test"},
                }
            )
            mock_get_crew_service.return_value = mock_service

            response = await async_client.get(
                "/api/crews/configs/test.yaml?workspace=/tmp",
                headers=auth_headers,
            )
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_save_crew_config(self, async_client: AsyncClient, auth_headers: dict):
        """Save crew config should succeed."""
        with patch("app.api.crew.get_crew_service") as mock_get_crew_service:
            mock_service = MagicMock()
            mock_service.save_crew_config = MagicMock(
                return_value={
                    "filename": "new.yaml",
                    "name": "new_crew",
                }
            )
            mock_get_crew_service.return_value = mock_service

            response = await async_client.put(
                "/api/crews/configs/new.yaml",
                headers=auth_headers,
                json={"workspace": "/tmp", "filename": "new.yaml", "content": "name: new_crew\nagents: []"},
            )
            assert response.status_code == 200


class TestDeleteCrewExecutionAPI:
    """Test DELETE /api/crews/{execution_id}."""

    @pytest.mark.asyncio
    async def test_delete_execution(self, async_client: AsyncClient, auth_headers: dict):
        """Delete execution should succeed."""
        with patch("app.api.crew.get_crew_service") as mock_get_crew_service:
            mock_service = MagicMock()
            mock_service.delete_execution = AsyncMock(return_value=True)
            mock_get_crew_service.return_value = mock_service

            response = await async_client.delete("/api/crews/exec-001", headers=auth_headers)
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_execution_not_found(self, async_client: AsyncClient, auth_headers: dict):
        """Delete non-existent execution should return 404."""
        with patch("app.api.crew.get_crew_service") as mock_get_crew_service:
            mock_service = MagicMock()
            mock_service.delete_execution = AsyncMock(return_value=False)
            mock_get_crew_service.return_value = mock_service

            response = await async_client.delete("/api/crews/nonexistent", headers=auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 404
