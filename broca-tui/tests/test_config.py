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
        assert config.socket_server_url == "http://localhost:6666"
        assert config.api_server_url == "http://localhost:9001"
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
            socket_server_url="http://custom:6666",
            api_server_url="http://custom:9001",
            theme="light",
        )
        assert config.socket_server_url == "http://custom:6666"
        assert config.api_server_url == "http://custom:9001"
        assert config.theme == "light"


class TestLoadConfig:
    """Test configuration loading logic (file-based, no env vars)."""

    def test_defaults_when_no_config(self):
        """Test default values when no config file found."""
        from broca_tui import config as config_module
        config_module._config_instance = None

        with patch("broca.configs.get_configs") as mock_gc:
            mock_gc.side_effect = ImportError("no broca installed")

        # Fallback: use dataclass defaults
        config = load_config()
        assert config.socket_server_url == "http://localhost:6666"
        assert config.api_server_url == "http://localhost:9001"
        assert config.theme == "dark"

    def test_configs_json_loaded(self):
        """Test that configs.json values are loaded via get_configs."""
        from broca_tui import config as config_module
        config_module._config_instance = None

        with patch("broca.configs.get_configs") as mock_gc:
            mock_gc.return_value.socket_server_url = "http://json-socket:6667"
            mock_gc.return_value.api_server_url = "http://json-api:9999"

            loaded = load_config()
            assert loaded.socket_server_url == "http://json-socket:6667"
            assert loaded.api_server_url == "http://json-api:9999"

    def test_partial_config_uses_defaults_for_missing(self):
        """Test that missing config fields fall back to defaults."""
        from broca_tui import config as config_module
        config_module._config_instance = None

        with patch("broca.configs.get_configs") as mock_gc:
            mock_gc.return_value.socket_server_url = "http://custom:6667"
            mock_gc.return_value.api_server_url = None  # not set

            loaded = load_config()
            assert loaded.socket_server_url == "http://custom:6667"
            assert loaded.api_server_url == "http://localhost:9001"  # default

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
