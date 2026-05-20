"""
数据库连接管理模块

负责数据库连接、会话工厂和初始化管理。
支持从环境变量或 .env 文件配置数据库路径。
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from broca.configs import get_configs


def _get_database_config() -> tuple[str, str]:
    """获取数据库配置，优先级: 环境变量 > 配置文件 > 默认值"""
    # 1. 环境变量优先
    env_dir = os.getenv("BROCA_DATABASE_DIR")
    if env_dir:
        database_dir = str(Path(env_dir).resolve())
        database_path = os.path.join(database_dir, "sessions.db")
        print(f"Database dir from env: {database_dir}")
        return database_dir, database_path

    # 2. 从配置文件读取
    configs = get_configs()
    if configs.database_dir:
        database_dir = str(Path(configs.database_dir).resolve())
        database_path = os.path.join(database_dir, "sessions.db")
        return database_dir, database_path

    # 3. 默认值
    home_dir = Path.home() / ".broca" / "data"
    database_dir = str(home_dir.resolve())
    database_path = os.path.join(database_dir, "sessions.db")
    return database_dir, database_path


# 获取数据库配置
DATABASE_DIR, DATABASE_PATH = _get_database_config()


class AsyncDatabaseManager:
    """异步数据库管理器（使用aiosqlite）"""

    _instance = None
    _engine = None
    _session_factory = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._engine is None:
            self._initialize_database()

    def _initialize_database(self):
        """初始化异步数据库连接"""
        # 确保数据目录存在
        os.makedirs(DATABASE_DIR, exist_ok=True)

        # 创建异步引擎
        self._engine = create_async_engine(
            f"sqlite+aiosqlite:///{DATABASE_PATH}",
            connect_args={"check_same_thread": False},
            pool_size=5,
            max_overflow=10,
            pool_recycle=3600,
            pool_timeout=30,
            pool_pre_ping=True,
            echo=False,
        )

        # 创建异步会话工厂，设置expire_on_commit=False避免DetachedInstanceError
        self._session_factory = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

        print(f"Async database initialized at: {DATABASE_PATH}")

    def get_engine(self):
        """获取异步数据库引擎"""
        return self._engine

    def get_session_factory(self):
        """获取会话工厂"""
        return self._session_factory

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """获取异步数据库会话"""
        async with self._session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    async def close(self):
        """关闭数据库连接"""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None


# 全局数据库管理器实例
db_manager = AsyncDatabaseManager()
