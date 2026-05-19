import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 数据库配置
    database_type: str = os.getenv("DATABASE_TYPE", "sqlite")  # postgresql 或 sqlite

    # PostgreSQL 连接配置（使用 Supabase 连接池时使用）
    database_url: str = os.getenv("DATABASE_URL", "")
    database_url_sync: str = os.getenv("DATABASE_URL_SYNC", "")

    # SQLite配置 (开发环境)
    sqlite_database_path: str = os.getenv("SQLITE_DATABASE_PATH", "sqlite:///./dev.db")

    # 服务器配置
    host: str = os.getenv("HOST", "0.0.0.0")  # noqa: S104
    port: int = int(os.getenv("PORT", "8000"))

    # JWT 配置（自有认证系统）
    jwt_secret: str = os.getenv("JWT_SECRET", "broca-default-dev-secret-change-in-production")
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))  # 默认24小时

    class Config:  # noqa: D106
        env_file = [".env.local", ".env.production", ".env.development"]

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
