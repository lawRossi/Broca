"""
数据库连接管理模块

负责数据库连接、会话工厂和初始化管理。
"""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession

# 数据库文件路径
DATABASE_DIR = "/home/ubuntu/code/Broca/data"
DATABASE_PATH = os.path.join(DATABASE_DIR, "sessions.db")


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
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
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
                await session.commit()
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
