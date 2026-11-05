"""Web 后端配置 — 纯 .env 文件驱动，不读取 os.environ。

配置来源优先级:
  1. .env / .env.local / .env.development / .env.production 文件
  2. configs.json (通过 BROCA_CONFIG 字段指向)
  3. 代码默认值
"""

from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend 目录（app/core/config.py → core → app → backend）
# 用于解析 BROCA_CONFIG 等相对路径，使其不依赖进程 CWD。
BACKEND_DIR = Path(__file__).resolve().parents[2]

# 开发环境专用的 broca 配置文件。生产环境禁止通过 BROCA_CONFIG 指向它
# （它把 database_dir/log_dir/snapshot_home 都隔离到 backend/.local-data）。
DEV_CONFIG_FILENAME = "configs.dev.json"


def resolve_broca_config_path(raw: str | None) -> Path | None:
    """把 BROCA_CONFIG 解析成绝对路径。

    委托给 ``broca.configs.resolve_configs_path()``（统一入口）。
    相对路径以 backend 目录为基准（而非进程 CWD）。
    """
    from broca.configs import resolve_configs_path

    return resolve_configs_path(raw, base_dir=BACKEND_DIR)


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
    # 相对路径以 backend 目录为基准解析，见 resolve_broca_config_path()
    broca_config: str = ""

    @property
    def broca_config_path(self) -> Path | None:
        """BROCA_CONFIG 的绝对路径；未设置时返回 None。"""
        return resolve_broca_config_path(self.broca_config)

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
            config_path = resolve_broca_config_path(values.get("broca_config"))
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
        - BROCA_CONFIG 不允许指向开发专用配置 configs.dev.json
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
            # dev 配置把 database_dir/log_dir/snapshot_home 都隔离到
            # backend/.local-data —— 生产实例读它等于数据凭空"消失"。
            # 注意：必须比较文件名而非字符串包含，避免误伤
            # ~/.broca/configs/configs.json 之类路径。
            config_path = self.broca_config_path
            if config_path is not None and config_path.name == DEV_CONFIG_FILENAME:
                raise ValueError(
                    "ENV=production 不允许 BROCA_CONFIG 指向 configs.dev.json"
                    f"（当前: {config_path}）。生产环境应指向 "
                    "~/.broca/configs/configs.json；请检查部署目录里是否残留了 "
                    ".env.local / .env.production / .env.development —— "
                    "它们的优先级高于 .env。"
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


# broca 核心的"生产"数据根目录。ENV != production 时若仍指向这里，
# 说明开发实例正在读写生产数据（sessions.db / 日志 / 快照）。
_PRODUCTION_DATA_ROOTS = (
    Path.home() / ".broca" / "data",
    Path.home() / ".broca" / "logs",
    Path.home() / ".broca" / "snapshots",
)


def check_data_dir_isolation() -> list[str]:
    """检查非 production 环境下是否误用了生产数据目录。

    Returns:
        命中的生产路径列表（空列表 = 隔离正常）。

    Note:
        这是一个纯函数，不做日志输出，方便单测直接断言。

    """
    if settings.env == "production":
        return []

    try:
        from broca.configs import get_configs

        configs = get_configs()
    except Exception:
        return []

    hits: list[str] = []
    for value in (configs.database_dir, configs.log_dir, configs.snapshot_home):
        if not isinstance(value, str) or not value:
            continue
        try:
            resolved = Path(value).expanduser().resolve()
        except OSError:
            continue
        for root in _PRODUCTION_DATA_ROOTS:
            root_resolved = root.resolve()
            if resolved == root_resolved or root_resolved in resolved.parents:
                hits.append(str(resolved))
                break
    return hits

