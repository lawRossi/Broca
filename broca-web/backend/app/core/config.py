"""Web 后端配置 — 纯 .env 文件驱动，不读取 os.environ。

配置来源优先级:
  1. .env / .env.local / .env.development / .env.production 文件
  2. configs.json (通过 BROCA_CONFIG 字段指向)
  3. 代码默认值
"""

from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=[".env", ".env.local", ".env.production", ".env.development"],
        extra="ignore",
    )

    # 关键：移除 EnvSettingsSource → 不读 os.environ，仅从 .env 文件读取
    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings,
        dotenv_settings, file_secret_settings,
    ):
        return (
            init_settings,
            dotenv_settings,
            file_secret_settings,
        )

    # --- 数据库配置 ---
    database_type: str = "sqlite"  # "sqlite" | "postgresql"
    database_url: str = ""
    database_url_sync: str = ""
    sqlite_database_path: str = "sqlite:///./dev.db"

    # --- 环境标识 ---
    env: str = Field(
        default="dev",
        validation_alias=AliasChoices("env", "BROCA_ENV", "ENV"),
    )  # "dev" | "production"

    # --- 服务器配置 ---
    host: str = "0.0.0.0"
    # 端口优先级: .env PORT > configs.json api_server_url > 默认 9001
    port: int = 9001
    # SocketIO 端口优先级: .env BROCA_SOCKETIO_PORT > configs.json socket_server_url > 默认 6666
    socketio_port: int = Field(
        default=6666,
        validation_alias=AliasChoices("socketio_port", "BROCA_SOCKETIO_PORT", "SOCKETIO_PORT"),
    )
    reload: bool = True

    # --- SocketIO 配置 ---
    broca_socketio_enabled: bool = True
    broca_socketio_host: str = "0.0.0.0"
    broca_socketio_cors: str = "*"

    # --- CORS (HTTP API，生产环境必须显式设置，不允许 *) ---
    cors_allow_origins: str = "*"

    # --- JWT 配置 ---
    jwt_secret: str = "broca-default-dev-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 2880

    # --- Broca 配置路径 ---
    # 指向 configs.json 的路径（传给 broca.configs.get_configs()）
    broca_config: str = ""

    # --- 数据库目录覆盖 ---
    broca_database_dir: str = ""

    @model_validator(mode="before")
    @classmethod
    def _derive_ports_from_configs_json(cls, values: dict) -> dict:
        """当 PORT / BROCA_SOCKETIO_PORT 未通过 .env 显式设置时，
        从 configs.json (get_configs()) 的 URL 中提取端口。

        优先级: .env > configs.json > 硬编码默认值
        """
        try:
            from broca.configs import get_configs
            from urllib.parse import urlparse

            # 如果有显式 BROCA_CONFIG 路径，传给 get_configs
            config_path = values.get("broca_config") or None
            configs = get_configs(config_path)
        except ImportError:
            # broca core 未安装 — 回退到 .env / 硬编码默认值
            return values

        if "port" not in values:
            if configs.api_server_url:
                try:
                    p = urlparse(configs.api_server_url).port
                    if p:
                        values["port"] = p
                except Exception:
                    pass

        if "socketio_port" not in values:
            if configs.socket_server_url:
                try:
                    p = urlparse(configs.socket_server_url).port
                    if p:
                        values["socketio_port"] = p
                except Exception:
                    pass

        return values

    @model_validator(mode="after")
    def _enforce_production_safety(self) -> "Settings":
        """生产环境安全护栏：
        - JWT_SECRET 必须显式设置（不能用默认 dev 值）
        - CORS 不允许通配符 *
        """
        if self.env == "production":
            _DEV_JWT_DEFAULT = "broca-default-dev-secret-change-in-production"
            if self.jwt_secret == _DEV_JWT_DEFAULT or not self.jwt_secret.strip():
                raise ValueError(
                    "ENV=production 要求显式设置 JWT_SECRET（不能为空或默认 dev 值）。"
                    "请在 .env.production 中设置 JWT_SECRET。"
                )
            if self.cors_allow_origins.strip() == "*":
                raise ValueError(
                    "ENV=production 要求显式设置 CORS_ALLOW_ORIGINS（不允许 *）。"
                    "请设置为具体的域名列表，如 https://example.com。"
                )
        return self

    @property
    def async_database_url(self) -> str:
        """异步数据库连接URL"""
        if self.database_type == "sqlite":
            return self.sqlite_database_path.replace("sqlite:///", "sqlite+aiosqlite:///")
        return self.database_url

    @property
    def sync_database_url(self) -> str:
        """同步数据库连接URL"""
        if self.database_type == "sqlite":
            return self.sqlite_database_path
        return self.database_url_sync


settings = Settings()
