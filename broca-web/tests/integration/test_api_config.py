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


class TestGeneralConfigAPI:
    """Test GET/PUT /api/config/general (configs.json)."""

    VALID_CONFIG = {
        "database_dir": "/tmp/broca/data",
        "log_file": "/tmp/broca/logs/agent.log",
        "log_level": "INFO",
        "llm_config_file": "/tmp/broca/configs/llm_config.json",
        "socket_server_url": "http://localhost:6868",
        "api_server_url": "http://localhost:9000",
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
        fields kept (unknown dropped, KNOWN order preserved), .bak backup created."""
        config_file = tmp_path / "configs.json"
        original = {"database_dir": "/old", "unknown_field": "should-be-dropped"}
        config_file.write_text(json.dumps(original), encoding="utf-8")
        monkeypatch.setattr("app.api.config.GENERAL_CONFIG_PATH", config_file)

        payload = {
            "database_dir": "/new/data",
            "unknown_key": 123,
            "log_level": "DEBUG",
            "api_server_url": "http://localhost:9000",
            "extra_unknown": "x",
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
        assert "unknown_key" not in saved
        assert "extra_unknown" not in saved
        assert saved["log_level"] == "DEBUG"
        # 旧文件备份为 .bak
        backup_file = tmp_path / "configs.json.bak"
        assert backup_file.exists()
        assert json.loads(backup_file.read_text(encoding="utf-8")) == original

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
        """PUT general config with execution group: preserved in KNOWN order,
        unknown execution fields dropped, .bak backup created."""
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
                "bogus_field": "should-be-dropped",
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
        # execution 字段按 KNOWN 顺序写回，未知字段被过滤
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
        assert "bogus_field" not in saved["execution"]
        # 旧文件备份为 .bak
        backup_file = tmp_path / "configs.json.bak"
        assert backup_file.exists()
        assert json.loads(backup_file.read_text(encoding="utf-8")) == original

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
