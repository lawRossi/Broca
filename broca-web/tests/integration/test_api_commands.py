"""Integration tests for commands API endpoints.

Tests /api/commands endpoints for retrieving available commands.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient


class TestCommandsAPI:
    """Test GET /api/commands."""

    @pytest.mark.asyncio
    async def test_get_commands_list(self, async_client: AsyncClient, auth_headers: dict):
        """Get commands should return command list."""
        mock_commands = [
            {"name": "help", "description": "Show help", "type": "local", "is_hidden": False, "is_enabled": True},
            {"name": "plan", "description": "Create a plan", "type": "prompt", "is_hidden": False, "is_enabled": True},
        ]

        # We need to patch the internal _load_commands or the registry
        with (
            patch("app.api.commands.CommandRegistry") as mock_registry_cls,
            patch("app.api.commands.load_all_commands") as mock_load,
        ):
            mock_registry = MagicMock()
            cmd1 = MagicMock()
            cmd1.name = "help"
            cmd1.description = "Show help"
            cmd1.short_description = ""
            cmd1.type = "local"
            cmd1.is_hidden = False
            cmd1.is_enabled = True
            cmd1.argument_hint = ""
            cmd1.show_result = False

            cmd2 = MagicMock()
            cmd2.name = "plan"
            cmd2.description = "Create a plan"
            cmd2.short_description = ""
            cmd2.type = "prompt"
            cmd2.is_hidden = False
            cmd2.is_enabled = True
            cmd2.argument_hint = ""
            cmd2.show_result = False

            mock_registry.get_all.return_value = [cmd1, cmd2]
            mock_registry_cls.return_value = mock_registry

            # Clear cache to force reload
            import app.api.commands
            app.api.commands._commands_cache = None

            response = await async_client.get("/api/commands", headers=auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert "commands" in data["data"]
            assert len(data["data"]["commands"]) >= 2

    @pytest.mark.asyncio
    async def test_get_command_by_name(self, async_client: AsyncClient, auth_headers: dict):
        """Get command by name should return command details."""
        # First ensure cache is populated
        with (
            patch("app.api.commands.CommandRegistry") as mock_registry_cls,
            patch("app.api.commands.load_all_commands"),
        ):
            mock_registry = MagicMock()
            cmd = MagicMock()
            cmd.name = "help"
            cmd.description = "Show help"
            cmd.short_description = ""
            cmd.type = "local"
            cmd.is_hidden = False
            cmd.is_enabled = True
            cmd.argument_hint = ""
            cmd.show_result = False
            mock_registry.get_all.return_value = [cmd]
            mock_registry_cls.return_value = mock_registry

            import app.api.commands
            app.api.commands._commands_cache = None

            response = await async_client.get("/api/commands/help", headers=auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert data["data"]["name"] == "help"

    @pytest.mark.asyncio
    async def test_get_command_not_found(self, async_client: AsyncClient, auth_headers: dict):
        """Non-existent command should return ApiResponse error with code 404."""
        with (
            patch("app.api.commands.CommandRegistry") as mock_registry_cls,
            patch("app.api.commands.load_all_commands"),
        ):
            mock_registry = MagicMock()
            cmd = MagicMock()
            cmd.name = "help"
            cmd.description = "Show help"
            cmd.short_description = ""
            cmd.type = "local"
            cmd.is_hidden = False
            cmd.is_enabled = True
            cmd.argument_hint = ""
            cmd.show_result = False
            mock_registry.get_all.return_value = [cmd]
            mock_registry_cls.return_value = mock_registry

            import app.api.commands
            app.api.commands._commands_cache = None

            response = await async_client.get("/api/commands/nonexistent", headers=auth_headers)
            # The endpoint returns ApiResponse.error (200 HTTP with 404 code in body)
            data = response.json()
            assert data["code"] == 404
            assert "not found" in data["msg"].lower()
