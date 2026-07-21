"""Integration tests for config API endpoints.

Tests /api/config/llm/providers and /api/config/llm/models/{provider}.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, mock_open, patch

import pytest
from httpx import AsyncClient


class TestLLMProvidersAPI:
    """Test GET /api/config/llm/providers."""

    @pytest.mark.asyncio
    async def test_get_providers_success(self, async_client: AsyncClient, auth_headers: dict):
        """Get providers should return provider list."""
        config_data = {
            "openai": {"models": {"gpt-4": {}}},
            "deepseek": {"models": {"deepseek-chat": {}}},
        }
        config_json = json.dumps(config_data)

        with (
            patch("app.api.config.LLM_CONFIG_PATH") as mock_path,
            patch("builtins.open", mock_open(read_data=config_json)),
        ):
            mock_path.exists = MagicMock(return_value=True)
            mock_path.__str__ = MagicMock(return_value="/tmp/test_llm_config.json")
            mock_path.__fspath__ = MagicMock(return_value="/tmp/test_llm_config.json")

            response = await async_client.get(
                "/api/config/llm/providers",
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert len(data["data"]) == 2
            provider_ids = [p["id"] for p in data["data"]]
            assert "openai" in provider_ids
            assert "deepseek" in provider_ids

    @pytest.mark.asyncio
    async def test_get_providers_no_config(self, async_client: AsyncClient, auth_headers: dict):
        """Missing config file should return error response."""
        with patch("app.api.config.LLM_CONFIG_PATH") as mock_path:
            mock_path.exists = MagicMock(return_value=False)

            response = await async_client.get(
                "/api/config/llm/providers",
                headers=auth_headers,
            )
            # Should return an error response (either via HTTPException handler or general handler)
            assert response.status_code in (404, 500)


class TestLLMModelsAPI:
    """Test GET /api/config/llm/models/{provider}."""

    @pytest.mark.asyncio
    async def test_get_models_success(self, async_client: AsyncClient, auth_headers: dict):
        """Get models for a provider should return model list."""
        config_data = {
            "openai": {
                "models": {
                    "gpt-4": {},
                    "gpt-4-turbo": {},
                    "gpt-3.5-turbo": {},
                }
            }
        }
        config_json = json.dumps(config_data)

        with (
            patch("app.api.config.LLM_CONFIG_PATH") as mock_path,
            patch("builtins.open", mock_open(read_data=config_json)),
        ):
            mock_path.exists = MagicMock(return_value=True)
            mock_path.__str__ = MagicMock(return_value="/tmp/test_llm_config.json")
            mock_path.__fspath__ = MagicMock(return_value="/tmp/test_llm_config.json")

            response = await async_client.get(
                "/api/config/llm/models/openai",
                headers=auth_headers,
            )
            assert response.status_code == 200
            data = response.json()
            assert len(data["data"]) == 3

    @pytest.mark.asyncio
    async def test_get_models_not_found(self, async_client: AsyncClient, auth_headers: dict):
        """Non-existent provider should return error response."""
        config_data = {"openai": {"models": {"gpt-4": {}}}}
        config_json = json.dumps(config_data)

        with (
            patch("app.api.config.LLM_CONFIG_PATH") as mock_path,
            patch("builtins.open", mock_open(read_data=config_json)),
        ):
            mock_path.exists = MagicMock(return_value=True)
            mock_path.__str__ = MagicMock(return_value="/tmp/test_llm_config.json")

            response = await async_client.get(
                "/api/config/llm/models/nonexistent",
                headers=auth_headers,
            )
            assert response.status_code in (404, 500)

    @pytest.mark.asyncio
    async def test_get_models_no_config(self, async_client: AsyncClient, auth_headers: dict):
        """Missing config file should return error."""
        with patch("app.api.config.LLM_CONFIG_PATH") as mock_path:
            mock_path.exists = MagicMock(return_value=False)

            response = await async_client.get(
                "/api/config/llm/models/openai",
                headers=auth_headers,
            )
            assert response.status_code in (404, 500)
