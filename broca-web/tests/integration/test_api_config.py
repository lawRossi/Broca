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
    async def test_get_providers_skips_default_key(self, async_client: AsyncClient, auth_headers: dict):
        """The reserved __default__ key must not be exposed as a provider."""
        config_data = {
            "openai": {"models": {"gpt-4": {}}},
            "__default__": {"provider": "openai", "model": "gpt-4"},
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
            provider_ids = [p["id"] for p in response.json()["data"]]
            assert provider_ids == ["openai"]

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

    # ---------- __default__ 保留键：全局默认 provider / model ----------

    @pytest.mark.asyncio
    async def test_put_llm_config_default_valid(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """PUT config with a valid __default__ (provider+model pair) should persist it."""
        config_file = tmp_path / "llm_config.json"
        config_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr("app.api.config.LLM_CONFIG_PATH", config_file)

        config = {**self.VALID_CONFIG, "__default__": {"provider": "deepseek", "model": "m2"}}
        response = await async_client.put("/api/config/llm", json={"config": config}, headers=auth_headers)

        assert response.status_code == 200
        saved = json.loads(config_file.read_text(encoding="utf-8"))
        assert saved["__default__"] == {"provider": "deepseek", "model": "m2"}

    @pytest.mark.asyncio
    async def test_put_llm_config_default_unset_allowed(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """A __default__ with empty provider/model (unset) is valid and persisted as-is."""
        config_file = tmp_path / "llm_config.json"
        config_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr("app.api.config.LLM_CONFIG_PATH", config_file)

        config = {**self.VALID_CONFIG, "__default__": {"provider": "", "model": ""}}
        response = await async_client.put("/api/config/llm", json={"config": config}, headers=auth_headers)

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_put_llm_config_default_provider_only_rejected(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """provider without a paired model must be rejected (avoid partial default)."""
        config_file = tmp_path / "llm_config.json"
        original = json.dumps(self.VALID_CONFIG)
        config_file.write_text(original, encoding="utf-8")
        monkeypatch.setattr("app.api.config.LLM_CONFIG_PATH", config_file)

        config = {**self.VALID_CONFIG, "__default__": {"provider": "deepseek"}}
        response = await async_client.put("/api/config/llm", json={"config": config}, headers=auth_headers)

        assert response.status_code == 400
        assert config_file.read_text(encoding="utf-8") == original

    @pytest.mark.asyncio
    async def test_put_llm_config_default_unknown_provider(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """__default__ referencing an unknown provider should be rejected."""
        config_file = tmp_path / "llm_config.json"
        config_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr("app.api.config.LLM_CONFIG_PATH", config_file)

        config = {**self.VALID_CONFIG, "__default__": {"provider": "ghost", "model": "m2"}}
        response = await async_client.put("/api/config/llm", json={"config": config}, headers=auth_headers)

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_put_llm_config_default_model_not_in_provider(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """__default__ whose model is not under the referenced provider should be rejected."""
        config_file = tmp_path / "llm_config.json"
        config_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr("app.api.config.LLM_CONFIG_PATH", config_file)

        config = {**self.VALID_CONFIG, "__default__": {"provider": "deepseek", "model": "does-not-exist"}}
        response = await async_client.put("/api/config/llm", json={"config": config}, headers=auth_headers)

        assert response.status_code == 400


class TestGeneralConfigAPI:
    """Test GET/PUT /api/config/general (configs.json)."""

    VALID_CONFIG = {
        "database_dir": "/tmp/broca/data",
        "log_file": "/tmp/broca/logs/agent.log",
        "log_level": "INFO",
        "llm_config_file": "/tmp/broca/configs/llm_config.json",
        "socket_server_url": "http://localhost:6666",
        "api_server_url": "http://localhost:9001",
        "execution": {
            "step_max_errors": 3,
            "llm_retry_delay": 5,
            "tool_call_timeout": 120,
            "assign_task_timeout": 1800,
            "llm_timeout": 300,
            "llm_first_chunk_timeout": 30,
            "dead_loop_window": 3,
            "message_queue_size": 3,
        },
    }

    @pytest.mark.asyncio
    async def test_get_general_config_success(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """GET general config should return the full config dict."""
        config_file = tmp_path / "configs.json"
        config_file.write_text(json.dumps(self.VALID_CONFIG), encoding="utf-8")
        monkeypatch.setattr("app.api.config.GENERAL_CONFIG_PATH", config_file)

        response = await async_client.get("/api/config/general", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 200
        assert data["data"] == self.VALID_CONFIG
        assert data["data"]["database_dir"] == "/tmp/broca/data"

    @pytest.mark.asyncio
    async def test_get_general_config_no_file(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """Missing config file should return 404."""
        config_file = tmp_path / "configs.json"
        monkeypatch.setattr("app.api.config.GENERAL_CONFIG_PATH", config_file)

        response = await async_client.get("/api/config/general", headers=auth_headers)

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_general_config_damaged(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """Damaged JSON should return 500 with parse error in detail."""
        config_file = tmp_path / "configs.json"
        config_file.write_text('{"database_dir": "/x",}', encoding="utf-8")
        monkeypatch.setattr("app.api.config.GENERAL_CONFIG_PATH", config_file)

        response = await async_client.get("/api/config/general", headers=auth_headers)

        assert response.status_code == 500
        # HTTPException 的 detail 经统一异常处理放到 ApiResponse.msg 中
        assert "not valid JSON" in response.json().get("msg", "")

    @pytest.mark.asyncio
    async def test_put_general_config_success(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """PUT valid general config: file reloads as valid JSON, only known
        fields kept (KNOWN order preserved), .bak backup created."""
        config_file = tmp_path / "configs.json"
        original = {"database_dir": "/old"}
        config_file.write_text(json.dumps(original), encoding="utf-8")
        monkeypatch.setattr("app.api.config.GENERAL_CONFIG_PATH", config_file)

        payload = {
            "database_dir": "/new/data",
            "log_level": "DEBUG",
            "api_server_url": "http://localhost:9001",
        }
        response = await async_client.put(
            "/api/config/general",
            json={"config": payload},
            headers=auth_headers,
        )

        assert response.status_code == 200
        saved = json.loads(config_file.read_text(encoding="utf-8"))
        # 仅保留已知字段，且按 KNOWN 顺序
        assert list(saved.keys()) == ["database_dir", "log_level", "api_server_url"]
        assert saved["log_level"] == "DEBUG"
        # 旧文件备份为 .bak
        backup_file = tmp_path / "configs.json.bak"
        assert backup_file.exists()
        assert json.loads(backup_file.read_text(encoding="utf-8")) == original

    @pytest.mark.asyncio
    async def test_put_general_config_unknown_field_rejected(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """PUT with an unknown top-level field returns 400 and leaves the file unchanged."""
        config_file = tmp_path / "configs.json"
        original = json.dumps(self.VALID_CONFIG)
        config_file.write_text(original, encoding="utf-8")
        monkeypatch.setattr("app.api.config.GENERAL_CONFIG_PATH", config_file)

        response = await async_client.put(
            "/api/config/general",
            json={"config": {**self.VALID_CONFIG, "unknown_key": 123}},
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert "unknown_key" in response.json().get("msg", "")
        assert config_file.read_text(encoding="utf-8") == original

    @pytest.mark.asyncio
    async def test_put_general_config_invalid_log_level(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """PUT with invalid log_level should return 400 and not modify the file."""
        config_file = tmp_path / "configs.json"
        original = json.dumps(self.VALID_CONFIG)
        config_file.write_text(original, encoding="utf-8")
        monkeypatch.setattr("app.api.config.GENERAL_CONFIG_PATH", config_file)

        response = await async_client.put(
            "/api/config/general",
            json={"config": {**self.VALID_CONFIG, "log_level": "BOGUS"}},
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert config_file.read_text(encoding="utf-8") == original

    @pytest.mark.asyncio
    async def test_put_general_config_not_object(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """PUT with non-object config should be rejected by request validation (422)."""
        config_file = tmp_path / "configs.json"
        config_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr("app.api.config.GENERAL_CONFIG_PATH", config_file)

        response = await async_client.put(
            "/api/config/general",
            json={"config": ["not", "an", "object"]},
            headers=auth_headers,
        )

        # pydantic 请求模型要求 config 为 dict，非对象在请求校验层即被拒绝
        assert response.status_code == 422
        assert config_file.read_text(encoding="utf-8") == "{}"

    @pytest.mark.asyncio
    async def test_put_general_config_with_execution(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """PUT general config with execution group: preserved in KNOWN order, .bak backup created."""
        config_file = tmp_path / "configs.json"
        original = {"database_dir": "/old"}
        config_file.write_text(json.dumps(original), encoding="utf-8")
        monkeypatch.setattr("app.api.config.GENERAL_CONFIG_PATH", config_file)

        payload = {
            "database_dir": "/new/data",
            "execution": {
                "step_max_errors": 5,
                "llm_retry_delay": 7,
                "tool_call_timeout": 60,
                "assign_task_timeout": 900,
                "llm_timeout": 120,
                "llm_first_chunk_timeout": 15,
                "dead_loop_window": 4,
                "message_queue_size": 10,
            },
        }
        response = await async_client.put(
            "/api/config/general",
            json={"config": payload},
            headers=auth_headers,
        )

        assert response.status_code == 200
        saved = json.loads(config_file.read_text(encoding="utf-8"))
        assert "execution" in saved
        # execution 字段按 KNOWN 顺序写回
        assert list(saved["execution"].keys()) == [
            "step_max_errors",
            "llm_retry_delay",
            "tool_call_timeout",
            "assign_task_timeout",
            "llm_timeout",
            "llm_first_chunk_timeout",
            "dead_loop_window",
            "message_queue_size",
        ]
        assert saved["execution"]["step_max_errors"] == 5
        assert saved["execution"]["dead_loop_window"] == 4
        # 旧文件备份为 .bak
        backup_file = tmp_path / "configs.json.bak"
        assert backup_file.exists()
        assert json.loads(backup_file.read_text(encoding="utf-8")) == original

    @pytest.mark.asyncio
    async def test_put_general_config_unknown_execution_field_rejected(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """PUT with an unknown execution field returns 400 and leaves the file unchanged."""
        config_file = tmp_path / "configs.json"
        original = json.dumps(self.VALID_CONFIG)
        config_file.write_text(original, encoding="utf-8")
        monkeypatch.setattr("app.api.config.GENERAL_CONFIG_PATH", config_file)

        payload = {
            "database_dir": "/new/data",
            "execution": {"step_max_errors": 5, "bogus_field": 1},
        }
        response = await async_client.put(
            "/api/config/general",
            json={"config": payload},
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert "bogus_field" in response.json().get("msg", "")
        assert config_file.read_text(encoding="utf-8") == original

    @pytest.mark.asyncio
    async def test_put_general_config_new_execution_fields_persisted(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """Regression: permission_request_timeout / agent_query_timeout must be persisted."""
        config_file = tmp_path / "configs.json"
        config_file.write_text(json.dumps(self.VALID_CONFIG), encoding="utf-8")
        monkeypatch.setattr("app.api.config.GENERAL_CONFIG_PATH", config_file)

        payload = {
            "execution": {
                "permission_request_timeout": 90,
                "agent_query_timeout": 300,
            }
        }
        response = await async_client.put(
            "/api/config/general",
            json={"config": payload},
            headers=auth_headers,
        )

        assert response.status_code == 200
        saved = json.loads(config_file.read_text(encoding="utf-8"))
        assert saved["execution"]["permission_request_timeout"] == 90
        assert saved["execution"]["agent_query_timeout"] == 300

    @pytest.mark.asyncio
    async def test_put_general_config_runner_execution_fields_persisted(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """Regression: runner_* and max_concurrent_runners fields must be persisted,
        not rejected as unknown execution config fields."""
        config_file = tmp_path / "configs.json"
        config_file.write_text(json.dumps(self.VALID_CONFIG), encoding="utf-8")
        monkeypatch.setattr("app.api.config.GENERAL_CONFIG_PATH", config_file)

        payload = {
            "execution": {
                "max_concurrent_runners": 5,
                "runner_heartbeat_interval": 10,
                "runner_heartbeat_timeout": 60,
                "runner_heartbeat_check_interval": 20,
                "runner_status_persist_interval": 120,
                "runner_ipc_queue_size": 2000,
                "runner_log_gc_days": 14,
                "runner_log_gc_interval": 7200,
            }
        }
        response = await async_client.put(
            "/api/config/general",
            json={"config": payload},
            headers=auth_headers,
        )

        assert response.status_code == 200
        saved = json.loads(config_file.read_text(encoding="utf-8"))
        assert saved["execution"]["max_concurrent_runners"] == 5
        assert saved["execution"]["runner_heartbeat_interval"] == 10
        assert saved["execution"]["runner_heartbeat_timeout"] == 60
        assert saved["execution"]["runner_heartbeat_check_interval"] == 20
        assert saved["execution"]["runner_status_persist_interval"] == 120
        assert saved["execution"]["runner_ipc_queue_size"] == 2000
        assert saved["execution"]["runner_log_gc_days"] == 14
        assert saved["execution"]["runner_log_gc_interval"] == 7200

    @pytest.mark.asyncio
    async def test_put_general_config_execution_mode_persisted(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """Regression: execution_mode 必须被识别并持久化。

        Bug（VSCode 设置页基础配置保存失败）：
        `Unknown execution config field(s): ['execution_mode']` —— configs.json 里
        已有 execution.execution_mode，但后端执行字段白名单没同步，导致保存 400。
        """
        config_file = tmp_path / "configs.json"
        config_file.write_text(json.dumps(self.VALID_CONFIG), encoding="utf-8")
        monkeypatch.setattr("app.api.config.GENERAL_CONFIG_PATH", config_file)

        payload = {"execution": {"execution_mode": "non_blocking"}}
        response = await async_client.put(
            "/api/config/general",
            json={"config": payload},
            headers=auth_headers,
        )

        assert response.status_code == 200, response.json()
        saved = json.loads(config_file.read_text(encoding="utf-8"))
        assert saved["execution"]["execution_mode"] == "non_blocking"

    @pytest.mark.asyncio
    async def test_put_general_config_execution_mode_roundtrip_blocking(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """execution_mode=blocking 同样可保存（枚举值均可持久化）。"""
        config_file = tmp_path / "configs.json"
        config_file.write_text(json.dumps(self.VALID_CONFIG), encoding="utf-8")
        monkeypatch.setattr("app.api.config.GENERAL_CONFIG_PATH", config_file)

        payload = {"execution": {"execution_mode": "blocking", "tool_execution_mode": "serial"}}
        response = await async_client.put(
            "/api/config/general",
            json={"config": payload},
            headers=auth_headers,
        )

        assert response.status_code == 200, response.json()
        saved = json.loads(config_file.read_text(encoding="utf-8"))
        assert saved["execution"]["execution_mode"] == "blocking"
        assert saved["execution"]["tool_execution_mode"] == "serial"

    @pytest.mark.asyncio
    async def test_put_general_config_execution_mode_invalid_value_rejected(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """非枚举取值的 execution_mode / tool_execution_mode 必须 400 且不改写文件。

        取值写错会让运行时静默走错分支（execution_mode 决定阻塞/非阻塞执行），
        不能像未知字段那样被放行。
        """
        config_file = tmp_path / "configs.json"
        original = json.dumps(self.VALID_CONFIG)
        config_file.write_text(original, encoding="utf-8")
        monkeypatch.setattr("app.api.config.GENERAL_CONFIG_PATH", config_file)

        for bad_payload in (
            {"execution": {"execution_mode": "fast"}},
            {"execution": {"execution_mode": ""}},
            {"execution": {"execution_mode": True}},
            {"execution": {"tool_execution_mode": "batch"}},
        ):
            response = await async_client.put(
                "/api/config/general",
                json={"config": {**self.VALID_CONFIG, **bad_payload}},
                headers=auth_headers,
            )
            assert response.status_code == 400, f"{bad_payload!r} should be rejected"
            assert config_file.read_text(encoding="utf-8") == original

    @pytest.mark.asyncio
    async def test_put_general_config_path_fields_persisted(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """Regression: log_dir / agents_config_dir / snapshot_home 等路径字段必须被保留。

        GET 会把整个 configs.json 原样返回，前端保存时整份回传 ——
        白名单缺字段时保存会 400（`Unknown general config field(s)`），
        或（若放行却不过滤）写回时被悄悄丢掉。
        """
        config_file = tmp_path / "configs.json"
        config_file.write_text(json.dumps(self.VALID_CONFIG), encoding="utf-8")
        monkeypatch.setattr("app.api.config.GENERAL_CONFIG_PATH", config_file)

        payload = {
            "log_dir": "/tmp/broca/logs",
            "decision_config_file": "/tmp/broca/configs/decision.json",
            "agents_config_dir": "/tmp/broca/configs/agents",
            "snapshot_home": "/tmp/broca/snapshots",
            "components_config": "/tmp/broca/configs/components.json",
        }
        response = await async_client.put(
            "/api/config/general",
            json={"config": payload},
            headers=auth_headers,
        )

        assert response.status_code == 200, response.json()
        saved = json.loads(config_file.read_text(encoding="utf-8"))
        for key, value in payload.items():
            assert saved[key] == value, f"{key} 应被写回"

    def test_general_config_whitelist_covers_broca_config_fields(self):
        """守卫：后端 general/execution 白名单必须覆盖 BrocaConfig/ExecutionConfig 全部字段。

        防止「broca/configs.py 新增配置项、broca-web 白名单没同步」再次导致
        设置页整份 configs.json 回传时 400（本次即 execution_mode 缺失）。
        与 broca/tests/test_runner_db_batching.py 中「configs.json ↔ ExecutionConfig」
        的守卫组合起来，形成 configs.json ⊆ ExecutionConfig ⊆ 后端白名单 的闭环。
        """
        from dataclasses import fields as dataclass_fields

        from broca.configs import BrocaConfig, ExecutionConfig

        from app.api.config import KNOWN_EXECUTION_CONFIG_FIELDS, KNOWN_GENERAL_CONFIG_FIELDS

        # 顶层：BrocaConfig 中从 configs.json 读入的字符串字段
        # （config_source_path 由运行时推导、不落盘，故排除）
        cfg = BrocaConfig()
        top_fields = {
            key for key, value in cfg.__dict__.items() if isinstance(value, (str, type(None)))
        } - {"config_source_path"}
        missing_general = top_fields - set(KNOWN_GENERAL_CONFIG_FIELDS)
        assert not missing_general, (
            f"BrocaConfig 字段未加入后端 general 白名单：{sorted(missing_general)}"
        )

        # 子分组对象同样必须在 general 白名单里（按分组校验/写回）
        assert {"execution", "storage", "search"} <= set(KNOWN_GENERAL_CONFIG_FIELDS)

        missing_exec = {f.name for f in dataclass_fields(ExecutionConfig)} - set(
            KNOWN_EXECUTION_CONFIG_FIELDS
        )
        assert not missing_exec, f"ExecutionConfig 字段未加入后端 execution 白名单：{sorted(missing_exec)}"

    @pytest.mark.asyncio
    async def test_put_general_config_unknown_asr_field_rejected(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """PUT with an unknown asr field must return 400 (rather than silently drop)."""
        config_file = tmp_path / "configs.json"
        original = json.dumps(self.VALID_CONFIG)
        config_file.write_text(original, encoding="utf-8")
        monkeypatch.setattr("app.api.config.GENERAL_CONFIG_PATH", config_file)

        payload = {"asr": {"model_name": "foo", "bogus_asr": 1}}
        response = await async_client.put(
            "/api/config/general",
            json={"config": payload},
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert "bogus_asr" in response.json().get("msg", "")
        assert config_file.read_text(encoding="utf-8") == original

    @pytest.mark.asyncio
    async def test_put_general_config_execution_not_object(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """PUT with non-object 'execution' should return 400 and not modify file."""
        config_file = tmp_path / "configs.json"
        original = json.dumps(self.VALID_CONFIG)
        config_file.write_text(original, encoding="utf-8")
        monkeypatch.setattr("app.api.config.GENERAL_CONFIG_PATH", config_file)

        response = await async_client.put(
            "/api/config/general",
            json={"config": {**self.VALID_CONFIG, "execution": "not-an-object"}},
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert config_file.read_text(encoding="utf-8") == original

    @pytest.mark.asyncio
    async def test_put_general_config_execution_invalid_value(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """PUT with non-numeric or boolean/negative execution field should return 400."""
        config_file = tmp_path / "configs.json"
        original = json.dumps(self.VALID_CONFIG)
        config_file.write_text(original, encoding="utf-8")
        monkeypatch.setattr("app.api.config.GENERAL_CONFIG_PATH", config_file)

        # 非数字
        response = await async_client.put(
            "/api/config/general",
            json={"config": {**self.VALID_CONFIG, "execution": {"step_max_errors": "three"}}},
            headers=auth_headers,
        )
        assert response.status_code == 400

        # 布尔值（int 子类，应拒绝）
        response = await async_client.put(
            "/api/config/general",
            json={"config": {**self.VALID_CONFIG, "execution": {"step_max_errors": True}}},
            headers=auth_headers,
        )
        assert response.status_code == 400

        # 负数
        response = await async_client.put(
            "/api/config/general",
            json={"config": {**self.VALID_CONFIG, "execution": {"llm_retry_delay": -1}}},
            headers=auth_headers,
        )
        assert response.status_code == 400

        # 原文件未被修改
        assert config_file.read_text(encoding="utf-8") == original

    @pytest.mark.asyncio
    async def test_get_general_config_with_execution(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """GET general config should return the full config dict including execution."""
        config_file = tmp_path / "configs.json"
        config_file.write_text(json.dumps(self.VALID_CONFIG), encoding="utf-8")
        monkeypatch.setattr("app.api.config.GENERAL_CONFIG_PATH", config_file)

        response = await async_client.get("/api/config/general", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["execution"]["llm_timeout"] == 300
        assert data["data"]["execution"]["message_queue_size"] == 3


class TestToolPermissionConfigAPI:
    """Test GET/PUT /api/config/tool-permission."""

    VALID_CONFIG = {
        "_description": "工具权限配置文件",
        "_permission_values": {
            "allow": "直接执行",
            "ask": "询问用户",
            "forbidden": "禁止执行",
        },
        "tools": {"read_file": "allow", "bash": "ask", "web_fetch": "forbidden"},
    }

    @pytest.mark.asyncio
    async def test_get_tool_permission_success(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """GET tool-permission config should return the full dict (incl. metadata)."""
        config_file = tmp_path / "tool_permission_config.json"
        config_file.write_text(json.dumps(self.VALID_CONFIG), encoding="utf-8")
        monkeypatch.setattr("app.api.config.TOOL_PERMISSION_PATH", config_file)

        response = await async_client.get("/api/config/tool-permission", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 200
        assert data["data"] == self.VALID_CONFIG
        assert data["data"]["tools"]["bash"] == "ask"

    @pytest.mark.asyncio
    async def test_get_tool_permission_no_file(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """Missing tool-permission config file should return 404."""
        config_file = tmp_path / "tool_permission_config.json"
        monkeypatch.setattr("app.api.config.TOOL_PERMISSION_PATH", config_file)

        response = await async_client.get("/api/config/tool-permission", headers=auth_headers)

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_tool_permission_damaged(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """Damaged JSON should return 500 with parse error in detail."""
        config_file = tmp_path / "tool_permission_config.json"
        config_file.write_text('{"tools": {', encoding="utf-8")
        monkeypatch.setattr("app.api.config.TOOL_PERMISSION_PATH", config_file)

        response = await async_client.get("/api/config/tool-permission", headers=auth_headers)

        assert response.status_code == 500
        # HTTPException 的 detail 经统一异常处理放到 ApiResponse.msg 中
        assert "not valid JSON" in response.json().get("msg", "")

    @pytest.mark.asyncio
    async def test_put_tool_permission_success(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """PUT valid config: metadata preserved verbatim, .bak backup created."""
        config_file = tmp_path / "tool_permission_config.json"
        original = json.dumps(self.VALID_CONFIG)
        config_file.write_text(original, encoding="utf-8")
        monkeypatch.setattr("app.api.config.TOOL_PERMISSION_PATH", config_file)

        new_config = {
            "_description": self.VALID_CONFIG["_description"],
            "_permission_values": self.VALID_CONFIG["_permission_values"],
            "tools": {"read_file": "allow", "bash": "forbidden", "cron": "ask"},
        }
        response = await async_client.put(
            "/api/config/tool-permission",
            json={"config": new_config},
            headers=auth_headers,
        )

        assert response.status_code == 200
        saved = json.loads(config_file.read_text(encoding="utf-8"))
        # 元数据原样保留
        assert saved["_description"] == self.VALID_CONFIG["_description"]
        assert saved["_permission_values"] == self.VALID_CONFIG["_permission_values"]
        assert saved["tools"] == {"read_file": "allow", "bash": "forbidden", "cron": "ask"}
        # 旧文件备份为 .bak
        backup_file = tmp_path / "tool_permission_config.json.bak"
        assert backup_file.exists()
        assert json.loads(backup_file.read_text(encoding="utf-8")) == json.loads(original)

    @pytest.mark.asyncio
    async def test_put_tool_permission_invalid_permission(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """PUT with invalid permission value should return 400 and not modify file."""
        config_file = tmp_path / "tool_permission_config.json"
        original = json.dumps(self.VALID_CONFIG)
        config_file.write_text(original, encoding="utf-8")
        monkeypatch.setattr("app.api.config.TOOL_PERMISSION_PATH", config_file)

        response = await async_client.put(
            "/api/config/tool-permission",
            json={"config": {"tools": {"read_file": "maybe"}}},
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert config_file.read_text(encoding="utf-8") == original

    @pytest.mark.asyncio
    async def test_put_tool_permission_tools_not_object(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """PUT with non-object 'tools' should return 400."""
        config_file = tmp_path / "tool_permission_config.json"
        config_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr("app.api.config.TOOL_PERMISSION_PATH", config_file)

        response = await async_client.put(
            "/api/config/tool-permission",
            json={"config": {"tools": "not-an-object"}},
            headers=auth_headers,
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_put_tool_permission_invalid_metadata(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """PUT with non-string '_description' or non-object '_permission_values' should return 400."""
        config_file = tmp_path / "tool_permission_config.json"
        config_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr("app.api.config.TOOL_PERMISSION_PATH", config_file)

        bad_meta = {"tools": {}, "_description": 123}
        response = await async_client.put(
            "/api/config/tool-permission",
            json={"config": bad_meta},
            headers=auth_headers,
        )
        assert response.status_code == 400

        bad_values = {"tools": {}, "_permission_values": ["allow", "ask", "forbidden"]}
        response = await async_client.put(
            "/api/config/tool-permission",
            json={"config": bad_values},
            headers=auth_headers,
        )
        assert response.status_code == 400


class TestMcpConfigAPI:
    """Test GET/PUT /api/config/mcp (mcp_config.json)."""

    VALID_CONFIG = {
        "stock": {
            "command": "python",
            "args": ["stock_mcp_server.py"],
            "env": {"API_KEY": "xxx"},
            "tool_timeout": 15,
        },
        "weather": {
            "url": "https://api.example.com/mcp",
            "headers": {"Authorization": "Bearer xxx"},
            "tool_timeout": 30,
        },
    }

    @pytest.mark.asyncio
    async def test_get_mcp_success(self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch):
        """GET MCP config should return the full dict (stdio + HTTP servers)."""
        config_file = tmp_path / "mcp_config.json"
        config_file.write_text(json.dumps(self.VALID_CONFIG), encoding="utf-8")
        monkeypatch.setattr("app.api.config.MCP_CONFIG_PATH", config_file)

        response = await async_client.get("/api/config/mcp", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 200
        assert data["data"] == self.VALID_CONFIG
        assert data["data"]["stock"]["command"] == "python"
        assert data["data"]["weather"]["url"] == "https://api.example.com/mcp"

    @pytest.mark.asyncio
    async def test_get_mcp_no_file(self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch):
        """Missing MCP config file should return 404."""
        config_file = tmp_path / "mcp_config.json"
        monkeypatch.setattr("app.api.config.MCP_CONFIG_PATH", config_file)

        response = await async_client.get("/api/config/mcp", headers=auth_headers)

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_mcp_damaged(self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch):
        """Damaged JSON should return 500 with parse error in detail."""
        config_file = tmp_path / "mcp_config.json"
        config_file.write_text('{"stock": {', encoding="utf-8")
        monkeypatch.setattr("app.api.config.MCP_CONFIG_PATH", config_file)

        response = await async_client.get("/api/config/mcp", headers=auth_headers)

        assert response.status_code == 500
        # HTTPException 的 detail 经统一异常处理放到 ApiResponse.msg 中
        assert "not valid JSON" in response.json().get("msg", "")

    @pytest.mark.asyncio
    async def test_put_mcp_success(self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch):
        """PUT valid MCP config: persisted verbatim, server order preserved, .bak backup created."""
        config_file = tmp_path / "mcp_config.json"
        original = {"old": {"command": "python", "args": ["old.py"]}}
        config_file.write_text(json.dumps(original), encoding="utf-8")
        monkeypatch.setattr("app.api.config.MCP_CONFIG_PATH", config_file)

        response = await async_client.put(
            "/api/config/mcp",
            json={"config": self.VALID_CONFIG},
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.json()["code"] == 200
        saved = json.loads(config_file.read_text(encoding="utf-8"))
        assert saved == self.VALID_CONFIG
        # 服务器顺序保持
        assert list(saved.keys()) == ["stock", "weather"]
        # 旧文件备份为 .bak
        backup_file = tmp_path / "mcp_config.json.bak"
        assert backup_file.exists()
        assert json.loads(backup_file.read_text(encoding="utf-8")) == original

    @pytest.mark.asyncio
    async def test_put_mcp_empty_config(self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch):
        """PUT empty object should be accepted (no servers configured)."""
        config_file = tmp_path / "mcp_config.json"
        config_file.write_text(json.dumps(self.VALID_CONFIG), encoding="utf-8")
        monkeypatch.setattr("app.api.config.MCP_CONFIG_PATH", config_file)

        response = await async_client.put(
            "/api/config/mcp",
            json={"config": {}},
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert json.loads(config_file.read_text(encoding="utf-8")) == {}

    @pytest.mark.asyncio
    async def test_put_mcp_missing_transport(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """PUT with a server lacking both 'command' and 'url' should return 400."""
        config_file = tmp_path / "mcp_config.json"
        original = json.dumps(self.VALID_CONFIG)
        config_file.write_text(original, encoding="utf-8")
        monkeypatch.setattr("app.api.config.MCP_CONFIG_PATH", config_file)

        response = await async_client.put(
            "/api/config/mcp",
            json={"config": {"broken": {"tool_timeout": 10}}},
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert config_file.read_text(encoding="utf-8") == original

    @pytest.mark.asyncio
    async def test_put_mcp_invalid_command(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """PUT with empty/non-string command should return 400."""
        config_file = tmp_path / "mcp_config.json"
        config_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr("app.api.config.MCP_CONFIG_PATH", config_file)

        response = await async_client.put(
            "/api/config/mcp",
            json={"config": {"s": {"command": "   "}}},
            headers=auth_headers,
        )
        assert response.status_code == 400

        response = await async_client.put(
            "/api/config/mcp",
            json={"config": {"s": {"command": 123}}},
            headers=auth_headers,
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_put_mcp_invalid_args_and_env(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """PUT with non-list args or non-string env values should return 400."""
        config_file = tmp_path / "mcp_config.json"
        config_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr("app.api.config.MCP_CONFIG_PATH", config_file)

        response = await async_client.put(
            "/api/config/mcp",
            json={"config": {"s": {"command": "python", "args": "not-a-list"}}},
            headers=auth_headers,
        )
        assert response.status_code == 400

        response = await async_client.put(
            "/api/config/mcp",
            json={"config": {"s": {"command": "python", "env": {"KEY": 123}}}},
            headers=auth_headers,
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_put_mcp_invalid_url_and_headers(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """PUT with empty url or non-object headers should return 400."""
        config_file = tmp_path / "mcp_config.json"
        config_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr("app.api.config.MCP_CONFIG_PATH", config_file)

        response = await async_client.put(
            "/api/config/mcp",
            json={"config": {"s": {"url": ""}}},
            headers=auth_headers,
        )
        assert response.status_code == 400

        response = await async_client.put(
            "/api/config/mcp",
            json={"config": {"s": {"url": "https://x/mcp", "headers": ["bad"]}}},
            headers=auth_headers,
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_put_mcp_invalid_tool_timeout(
        self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch
    ):
        """PUT with non-positive / boolean tool_timeout should return 400."""
        config_file = tmp_path / "mcp_config.json"
        config_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr("app.api.config.MCP_CONFIG_PATH", config_file)

        for bad_timeout in (0, -5, True, "10"):
            response = await async_client.put(
                "/api/config/mcp",
                json={"config": {"s": {"command": "python", "tool_timeout": bad_timeout}}},
                headers=auth_headers,
            )
            assert response.status_code == 400, f"tool_timeout={bad_timeout!r} should be rejected"

    @pytest.mark.asyncio
    async def test_put_mcp_not_object(self, async_client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch):
        """PUT with non-object config should be rejected by request validation (422)."""
        config_file = tmp_path / "mcp_config.json"
        config_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr("app.api.config.MCP_CONFIG_PATH", config_file)

        response = await async_client.put(
            "/api/config/mcp",
            json={"config": ["not", "an", "object"]},
            headers=auth_headers,
        )

        assert response.status_code == 422
        assert config_file.read_text(encoding="utf-8") == "{}"
