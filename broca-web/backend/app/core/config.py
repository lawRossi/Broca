import os
from urllib.parse import urlparse

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 数据库配置
    database_type: str = os.getenv("DATABASE_TYPE", "postgresql")  # postgresql 或 sqlite

    # Supabase配置 (生产环境)
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_key: str = os.getenv("SUPABASE_KEY", "")
    supabase_db_password: str = os.getenv("SUPABASE_DB_PASSWORD", "")
    supabase_jwt_secret: str = os.getenv("SUPABASE_JWT_SECRET", "")

    # Supabase Storage配置
    supabase_storage_bucket: str = os.getenv("SUPABASE_STORAGE_BUCKET", "reports")

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
    def database_url(self) -> str:
        """异步数据库连接URL"""
        if self.database_type == "sqlite":
            # SQLite使用aiosqlite驱动
            return self.sqlite_database_path.replace("sqlite:///", "sqlite+aiosqlite:///")

        # PostgreSQL (Supabase)
        parsed_url = urlparse(self.supabase_url)
        project_id = parsed_url.netloc.split(".")[0]
        return f"postgresql+asyncpg://postgres.{project_id}:{self.supabase_db_password}@aws-1-ap-southeast-1.pooler.supabase.com:6543/postgres"

    @property
    def database_url_sync(self) -> str:
        """同步数据库连接URL"""
        if self.database_type == "sqlite":
            return self.sqlite_database_path

        # PostgreSQL (Supabase)
        parsed_url = urlparse(self.supabase_url)
        project_id = parsed_url.netloc.split(".")[0]
        return f"postgresql://postgres.{project_id}:{self.supabase_db_password}@aws-1-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require"


settings = Settings()
