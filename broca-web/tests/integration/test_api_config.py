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


class TestLLMConfigAPI:
    """Test GET /api/config/llm and PUT /api/config/llm."""

    VALID_CONFIG = {
        "deepseek": {
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "sk-test",
            "models": {
                "m1": {
                    "model": "openai/deepseek-v4",
                    "meta": {"modality": {"text": ""}},
                },
                "m2": {
                    "model": "openai/deepseek-v4-flash",
                    "temperature": 0.7,
                    "meta": {"modality": {"text": "", "image": {}, "video": {"fp": 2}}, "context_window": 1000000},
                },
            },
        }
    }

    @pytest.mark.asyncio
    async def test_get_llm_config_success(self, async_client: AsyncClient, auth_headers: dict):
        """Get full LLM config should return the config object."""
        config_json = json.dumps(self.VALID_CONFIG)

        with (
            patch("app.api.config.LLM_CONFIG_PATH") as mock_path,
            patch("builtins.open", mock_open(read_data=config_json)),
        ):
            mock_path.exists = MagicMock(return_value=True)
            mock_path.__str__ = MagicMock(return_value="/test/llm_config.json")
            mock_path.__fspath__ = MagicMock(return_value="/test/llm_config.json")

            response = await async_client.get(
                "/api/config/llm",
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 200
            assert isinstance(data["data"], dict)
            assert "deepseek" in data["data"]
            assert data["data"]["deepseek"]["api_key"] == "sk-test"
            assert data["data"]["deepseek"]["models"]["m1"]["model"] == "openai/deepseek-v4"

    @pytest.mark.asyncio
    async def test_get_llm_config_no_file(self, async_client: AsyncClient, auth_headers: dict):
        """Missing config file should return error response."""
        with patch("app.api.config.LLM_CONFIG_PATH") as mock_path:
            mock_path.exists = MagicMock(return_value=False)

            response = await async_client.get(
                "/api/config/llm",
                headers=auth_headers,
            )
            assert response.status_code in (404, 500)

    @pytest.mark.asyncio
    async def test_put_llm_config_success(self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch):
        """PUT valid config should persist it to the config file."""
        config_file = tmp_path / "llm_config.json"
        config_file.write_text(json.dumps({"old": {"base_url": "u", "api_key": "k", "models": {}}}), encoding="utf-8")
        monkeypatch.setattr("app.api.config.LLM_CONFIG_PATH", config_file)

        response = await async_client.put(
            "/api/config/llm",
            json={"config": self.VALID_CONFIG},
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.json()["code"] == 200
        saved = json.loads(config_file.read_text(encoding="utf-8"))
        assert "deepseek" in saved
        assert set(saved["deepseek"]["models"].keys()) == {"m1", "m2"}
        assert saved["deepseek"]["models"]["m2"]["temperature"] == 0.7

    @pytest.mark.asyncio
    async def test_put_llm_config_invalid_missing_models(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """PUT config with provider missing 'models' should return 400 and not modify the file."""
        config_file = tmp_path / "llm_config.json"
        original = json.dumps(self.VALID_CONFIG)
        config_file.write_text(original, encoding="utf-8")
        monkeypatch.setattr("app.api.config.LLM_CONFIG_PATH", config_file)

        bad_config = {"p": {"base_url": "https://x", "api_key": "k"}}
        response = await async_client.put(
            "/api/config/llm",
            json={"config": bad_config},
            headers=auth_headers,
        )

        assert response.status_code == 400
        # 原文件未被修改
        assert config_file.read_text(encoding="utf-8") == original

    @pytest.mark.asyncio
    async def test_put_llm_config_invalid_not_object(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """PUT non-object config should be rejected by request validation (422)."""
        config_file = tmp_path / "llm_config.json"
        config_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr("app.api.config.LLM_CONFIG_PATH", config_file)

        response = await async_client.put(
            "/api/config/llm",
            json={"config": ["not", "an", "object"]},
            headers=auth_headers,
        )

        # pydantic 请求模型要求 config 为 dict，非对象在请求校验层即被拒绝
        assert response.status_code == 422
        # 原文件未被修改
        assert config_file.read_text(encoding="utf-8") == "{}"

    @pytest.mark.asyncio
    async def test_put_creates_backup(self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch):
        """Saving config should create a .bak backup containing the previous config."""
        config_file = tmp_path / "llm_config.json"
        old_config = {
            "deepseek": {"base_url": "https://api.deepseek.com/v1", "api_key": "sk-old", "models": {}}
        }
        config_file.write_text(json.dumps(old_config), encoding="utf-8")
        monkeypatch.setattr("app.api.config.LLM_CONFIG_PATH", config_file)

        response = await async_client.put(
            "/api/config/llm",
            json={"config": self.VALID_CONFIG},
            headers=auth_headers,
        )

        assert response.status_code == 200
        backup_file = tmp_path / "llm_config.json.bak"
        assert backup_file.exists()
        backup = json.loads(backup_file.read_text(encoding="utf-8"))
        assert backup["deepseek"]["api_key"] == "sk-old"

    @pytest.mark.asyncio
    async def test_put_llm_config_accepts_modality(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """PUT config with meta.modality (multimodal capabilities) should be accepted."""
        config_file = tmp_path / "llm_config.json"
        config_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr("app.api.config.LLM_CONFIG_PATH", config_file)

        response = await async_client.put(
            "/api/config/llm",
            json={"config": self.VALID_CONFIG},
            headers=auth_headers,
        )

        assert response.status_code == 200
        saved = json.loads(config_file.read_text(encoding="utf-8"))
        modality = saved["deepseek"]["models"]["m2"]["meta"]["modality"]
        assert modality == {"text": "", "image": {}, "video": {"fp": 2}}
        assert saved["deepseek"]["models"]["m2"]["meta"]["context_window"] == 1000000

    @pytest.mark.asyncio
    async def test_put_llm_config_invalid_missing_meta(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """PUT config with model missing 'meta' should return 400 (runtime requires meta.modality)."""
        config_file = tmp_path / "llm_config.json"
        original = json.dumps(self.VALID_CONFIG)
        config_file.write_text(original, encoding="utf-8")
        monkeypatch.setattr("app.api.config.LLM_CONFIG_PATH", config_file)

        bad_config = {
            "p": {
                "base_url": "https://x",
                "api_key": "k",
                "models": {"m": {"model": "openai/x"}},
            }
        }
        response = await async_client.put(
            "/api/config/llm",
            json={"config": bad_config},
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert config_file.read_text(encoding="utf-8") == original

    @pytest.mark.asyncio
    async def test_put_llm_config_invalid_missing_modality(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """PUT config with model missing 'meta.modality' should return 400."""
        config_file = tmp_path / "llm_config.json"
        config_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr("app.api.config.LLM_CONFIG_PATH", config_file)

        bad_config = {
            "p": {
                "base_url": "https://x",
                "api_key": "k",
                "models": {"m": {"model": "openai/x", "meta": {"context_window": 1000}}},
            }
        }
        response = await async_client.put(
            "/api/config/llm",
            json={"config": bad_config},
            headers=auth_headers,
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_put_llm_config_invalid_modality_not_object(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """PUT config with non-object meta.modality should return 400."""
        config_file = tmp_path / "llm_config.json"
        config_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr("app.api.config.LLM_CONFIG_PATH", config_file)

        bad_config = {
            "p": {
                "base_url": "https://x",
                "api_key": "k",
                "models": {"m": {"model": "openai/x", "meta": {"modality": "text"}}},
            }
        }
        response = await async_client.put(
            "/api/config/llm",
            json={"config": bad_config},
            headers=auth_headers,
        )

        assert response.status_code == 400
