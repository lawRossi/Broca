"""
数据库连接管理模块

负责数据库连接、会话工厂和初始化管理。
支持从环境变量或 .env 文件配置数据库路径。
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from broca.configs import get_configs
from broca.logging_config import get_logger

logger = get_logger(__name__)


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
        # timeout=10: 每个连接创建时设置 SQLite busy_timeout=10000ms（默认仅 5s），
        # 减少 abort 等并发写场景下 "database is locked" 的触发概率。
        self._engine = create_async_engine(
            f"sqlite+aiosqlite:///{DATABASE_PATH}",
            connect_args={"check_same_thread": False, "timeout": 10},
            pool_size=5,
            max_overflow=10,
            pool_recycle=3600,
            pool_timeout=30,
            pool_pre_ping=True,
            echo=False,
        )

        # 每个新连接建立时启用 WAL 模式。
        # WAL 模式下读事务(SHARED 锁)不会阻塞其他连接的写提交(EXCLUSIVE 锁)，
        # 从根上消除 abort 场景下（Web 后端持读锁等待 IPC / runner 收尾写库）
        # 跨进程、跨连接导致的 "database is locked"。
        @event.listens_for(self._engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):
            try:
                # aiosqlite 适配器包装了底层 sqlite3.Connection
                raw = getattr(dbapi_connection, "_connection", dbapi_connection)
                conn = getattr(raw, "_conn", raw)
                cursor = conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.close()
            except Exception as e:
                logger.warning(f"Failed to set SQLite PRAGMA journal_mode=WAL: {e}")

        # 创建异步会话工厂，设置expire_on_commit=False避免DetachedInstanceError
        self._session_factory = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

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
            except BaseException:
                # 必须捕获 BaseException（含 asyncio.CancelledError）：
                # abort 会取消执行任务，若取消时正处在数据库事务中，
                # 必须回滚以释放 SQLite 写锁；否则事务残留可能导致
                # 后续写入 "database is locked"。
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
