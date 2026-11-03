"""
Configuration module for Broca TUI.

Reads configuration from configs.json (via broca.configs.get_configs()).
No environment variables are read.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def _get_broca_home() -> Path:
    """Get the Broca home directory."""
    return Path.home() / ".broca"


def _load_configs_json() -> dict:
    """Load configs.json: project config > user config."""
    # 优先使用 broca.configs.get_configs()（统一配置发现逻辑）
    try:
        from broca.configs import get_configs
        cfg = get_configs()
        # 构造 dict 供 TUIConfig 使用
        result = {}
        if cfg.socket_server_url:
            result["socket_server_url"] = cfg.socket_server_url
        if cfg.api_server_url:
            result["api_server_url"] = cfg.api_server_url
        if result:
            return result
    except ImportError:
        pass

    # 回退：手动发现（broca 包未安装时）
    project_config = Path(__file__).resolve().parent.parent.parent / "configs" / "configs.json"
    user_config = _get_broca_home() / "configs" / "configs.json"

    for path in (project_config, user_config):
        if path.exists():
            try:
                with open(path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
    return {}


@dataclass
class TUIConfig:
    """TUI configuration loaded from config files."""

    # Socket.IO server URL
    socket_server_url: str = "http://localhost:6666"

    # REST API server URL
    api_server_url: str = "http://localhost:9001"

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
    """Load TUI configuration from config files.

    Priority: configs.json > defaults
    """
    configs = _load_configs_json()
    config = TUIConfig()

    # Socket server URL
    config.socket_server_url = configs.get("socket_server_url", config.socket_server_url)

    # API server URL
    config.api_server_url = configs.get("api_server_url", config.api_server_url)

    # Client ID
    config.client_id = configs.get("client_id", config.client_id)

    # User ID
    config.user_id = configs.get("user_id", config.user_id)

    # Theme
    config.theme = configs.get("tui_theme", config.theme)

    return config


# Global config instance
_config_instance: Optional[TUIConfig] = None


def get_config() -> TUIConfig:
    """Get the global TUI configuration instance."""
    global _config_instance
    if _config_instance is None:
        _config_instance = load_config()
    return _config_instance
