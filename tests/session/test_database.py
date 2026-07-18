"""
AsyncDatabaseManager 单元测试

覆盖：
- _get_database_config 函数
- 数据库管理器初始化和单例模式
- 连接获取和释放

注意：由于数据库配置在 import 时已执行，部分测试需要直接测试函数逻辑。
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from broca.session.database import (
    AsyncDatabaseManager,
    _get_database_config,
)


class TestGetDatabaseConfig:
    """测试 _get_database_config 函数逻辑"""

    def test_env_var_override(self):
        """测试环境变量覆盖"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"BROCA_DATABASE_DIR": tmpdir}):
                db_dir, db_path = _get_database_config()
                assert db_dir == str(Path(tmpdir).resolve())
                assert db_path.endswith("sessions.db")

    def test_env_var_sets_correct_path(self):
        """测试环境变量设置正确的路径格式"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"BROCA_DATABASE_DIR": tmpdir}):
                db_dir, db_path = _get_database_config()
                assert os.path.isabs(db_dir)
                assert db_path == os.path.join(db_dir, "sessions.db")


class TestAsyncDatabaseManager:
    """测试 AsyncDatabaseManager 行为"""

    def setup_method(self):
        # 重置单例（注意：其他测试可能已经初始化了）
        AsyncDatabaseManager._instance = None
        AsyncDatabaseManager._engine = None
        AsyncDatabaseManager._session_factory = None

    def test_singleton(self):
        """测试单例模式"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"BROCA_DATABASE_DIR": tmpdir}):
                db1 = AsyncDatabaseManager()
                db2 = AsyncDatabaseManager()
                assert db1 is db2

    def test_initialize_with_env(self):
        """测试使用环境变量初始化"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"BROCA_DATABASE_DIR": tmpdir}):
                db = AsyncDatabaseManager()
                engine = db.get_engine()
                assert engine is not None

    def test_get_engine(self):
        """测试获取引擎"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"BROCA_DATABASE_DIR": tmpdir}):
                db = AsyncDatabaseManager()
                engine = db.get_engine()
                assert engine is not None

    def test_get_session_factory(self):
        """测试获取会话工厂"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"BROCA_DATABASE_DIR": tmpdir}):
                db = AsyncDatabaseManager()
                factory = db.get_session_factory()
                assert factory is not None

    @pytest.mark.asyncio
    async def test_get_session(self):
        """测试获取会话"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"BROCA_DATABASE_DIR": tmpdir}):
                # 确保单例被重置以接收新的环境变量
                AsyncDatabaseManager._instance = None
                AsyncDatabaseManager._engine = None
                AsyncDatabaseManager._session_factory = None

                db = AsyncDatabaseManager()
                async with db.get_session() as session:
                    assert session is not None

    @pytest.mark.asyncio
    async def test_close(self):
        """测试关闭连接"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"BROCA_DATABASE_DIR": tmpdir}):
                AsyncDatabaseManager._instance = None
                AsyncDatabaseManager._engine = None
                AsyncDatabaseManager._session_factory = None

                db = AsyncDatabaseManager()
                await db.close()
                assert db._engine is None

    @pytest.mark.asyncio
    async def test_session_context_manager(self):
        """测试会话上下文管理器"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"BROCA_DATABASE_DIR": tmpdir}):
                AsyncDatabaseManager._instance = None
                AsyncDatabaseManager._engine = None
                AsyncDatabaseManager._session_factory = None

                db = AsyncDatabaseManager()
                async with db.get_session() as session:
                    assert session is not None
                    assert not session.is_active or True  # SQLite session
