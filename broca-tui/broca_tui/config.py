"""
Configuration module for Broca TUI.

Reads configuration from environment variables and ~/.broca/configs/configs.json.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def _get_broca_home() -> Path:
    """Get the Broca home directory."""
    return Path(os.environ.get("BROCA_HOME", Path.home() / ".broca"))


def _load_configs_json() -> dict:
    """Load configs.json from Broca home directory."""
    config_path = _get_broca_home() / "configs" / "configs.json"
    fallback_path = Path(__file__).parent.parent.parent.parent / "configs" / "configs.json"

    for path in [config_path, fallback_path]:
        if path.exists():
            try:
                with open(path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
    return {}


@dataclass
class TUIConfig:
    """TUI configuration loaded from environment and config files."""

    # Socket.IO server URL
    socket_server_url: str = "http://localhost:6868"

    # REST API server URL
    api_server_url: str = "http://localhost:9000"

    # Client type identifier
    client_type: str = "tui"

    # Client ID (auto-generated if not provided)
    client_id: Optional[str] = None

    # User ID
    user_id: Optional[str] = None

    # Socket reconnection settings
    auto_reconnect: bool = True
    reconnect_delay: float = 1.0
    max_reconnect_attempts: int = 5

    # UI settings
    theme: str = "dark"

    # Runner polling interval (seconds)
    runner_poll_interval: int = 10

    # Message history page size
    history_page_size: int = 50


def load_config() -> TUIConfig:
    """Load TUI configuration from environment variables and config files.

    Priority: environment variables > configs.json > defaults
    """
    configs = _load_configs_json()
    config = TUIConfig()

    # Socket server URL
    config.socket_server_url = os.environ.get(
        "BROCA_SOCKET_SERVER_URL",
        configs.get("socket_server_url", config.socket_server_url),
    )

    # API server URL
    config.api_server_url = os.environ.get(
        "BROCA_API_SERVER_URL",
        configs.get("api_server_url", config.api_server_url),
    )

    # Client ID
    config.client_id = os.environ.get(
        "BROCA_CLIENT_ID",
        configs.get("client_id", config.client_id),
    )

    # User ID
    config.user_id = os.environ.get(
        "BROCA_USER_ID",
        configs.get("user_id", config.user_id),
    )

    # Theme
    config.theme = os.environ.get(
        "BROCA_TUI_THEME",
        configs.get("tui_theme", config.theme),
    )

    return config


# Global config instance
_config_instance: Optional[TUIConfig] = None


def get_config() -> TUIConfig:
    """Get the global TUI configuration instance."""
    global _config_instance
    if _config_instance is None:
        _config_instance = load_config()
    return _config_instance
