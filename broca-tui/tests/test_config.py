"""
Tests for broca_tui.config module.

Covers:
- Default configuration values
- Environment variable override
- configs.json loading with fallback
"""

import os
import json
import tempfile
from pathlib import Path
from unittest.mock import patch


from broca_tui.config import load_config, TUIConfig, get_config


class TestTUIConfig:
    """Test TUIConfig dataclass defaults."""

    def test_default_values(self):
        """Test that default values are reasonable."""
        config = TUIConfig()
        assert config.socket_server_url == "http://localhost:6868"
        assert config.api_server_url == "http://localhost:9000"
        assert config.client_type == "tui"
        assert config.auto_reconnect is True
        assert config.reconnect_delay == 1.0
        assert config.max_reconnect_attempts == 5
        assert config.theme == "dark"
        assert config.runner_poll_interval == 10
        assert config.history_page_size == 50

    def test_custom_values(self):
        """Test that constructor overrides work."""
        config = TUIConfig(
            socket_server_url="http://custom:6868",
            api_server_url="http://custom:9000",
            theme="light",
        )
        assert config.socket_server_url == "http://custom:6868"
        assert config.api_server_url == "http://custom:9000"
        assert config.theme == "light"


class TestLoadConfig:
    """Test configuration loading logic."""

    def test_env_vars_override_defaults(self):
        """Test that environment variables override default values."""
        with patch.dict(os.environ, {
            "BROCA_SOCKET_SERVER_URL": "http://env-socket:6868",
            "BROCA_API_SERVER_URL": "http://env-api:9000",
            "BROCA_TUI_THEME": "light",
        }, clear=True):
            config = load_config()
            assert config.socket_server_url == "http://env-socket:6868"
            assert config.api_server_url == "http://env-api:9000"
            assert config.theme == "light"

    def test_configs_json_loaded_when_no_env(self):
        """Test that configs.json values are used when no env vars set."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "configs"
            config_dir.mkdir(parents=True)
            config_file = config_dir / "configs.json"
            config_file.write_text(json.dumps({
                "socket_server_url": "http://json-socket:6868",
                "api_server_url": "http://json-api:9999",
            }))

            with patch.dict(os.environ, {
                "BROCA_HOME": tmpdir,
            }, clear=True):
                # Clear cached config
                from broca_tui import config as config_module
                config_module._config_instance = None
                loaded = load_config()
                assert loaded.socket_server_url == "http://json-socket:6868"
                assert loaded.api_server_url == "http://json-api:9999"

    def test_env_vars_override_configs_json(self):
        """Test that env vars take priority over configs.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "configs"
            config_dir.mkdir(parents=True)
            config_file = config_dir / "configs.json"
            config_file.write_text(json.dumps({
                "socket_server_url": "http://json-socket:6868",
                "api_server_url": "http://json-api:9999",
            }))

            with patch.dict(os.environ, {
                "BROCA_HOME": tmpdir,
                "BROCA_SOCKET_SERVER_URL": "http://env-override:6868",
            }, clear=True):
                from broca_tui import config as config_module
                config_module._config_instance = None
                loaded = load_config()
                # Env var should override the json value
                assert loaded.socket_server_url == "http://env-override:6868"
                # API URL should still come from configs.json
                assert loaded.api_server_url == "http://json-api:9999"

    def test_get_config_singleton(self):
        """Test that get_config returns the same instance."""
        from broca_tui import config as config_module
        config_module._config_instance = None
        c1 = get_config()
        c2 = get_config()
        assert c1 is c2


class TestClientId:
    """Test client ID generation."""

    def test_client_id_default_is_none(self):
        """Test that default client_id is None (will be auto-generated)."""
        config = TUIConfig()
        assert config.client_id is None

    def test_client_id_can_be_set(self):
        """Test that client_id can be configured."""
        config = TUIConfig(client_id="my-tui-client")
        assert config.client_id == "my-tui-client"
