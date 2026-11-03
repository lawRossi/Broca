"""
AsyncDatabaseManager 单元测试

覆盖：
- _get_database_config 函数
- get_database_path 延迟计算
- 数据库管理器懒加载初始化和单例模式
- 连接获取和释放
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from broca.session.database import (
    AsyncDatabaseManager,
    _get_database_config,
    get_database_path,
)


def _reset_database_state(tmpdir: str):
    """重置数据库模块的所有缓存和单例状态"""
    import broca.session.database as db_mod
    db_mod._database_config_cache = None
    AsyncDatabaseManager._instance = None
    AsyncDatabaseManager._engine = None
    AsyncDatabaseManager._session_factory = None


class TestGetDatabaseConfig:
    """测试 _get_database_config 函数逻辑"""

    def test_config_override(self):
        """测试从 configs.json 读取 database_dir"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("broca.session.database.get_configs") as mock_gc:
                mock_gc.return_value.database_dir = tmpdir
                db_dir, db_path = _get_database_config()
                assert db_dir == str(Path(tmpdir).resolve())
                assert db_path.endswith("sessions.db")

    def test_config_sets_correct_path(self):
        """测试 configs.json 设置正确的路径格式"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("broca.session.database.get_configs") as mock_gc:
                mock_gc.return_value.database_dir = tmpdir
                db_dir, db_path = _get_database_config()
                assert os.path.isabs(db_dir)
                assert db_path == os.path.join(db_dir, "sessions.db")

    def test_default_path_when_no_config(self):
        """无配置时使用 ~/.broca/data 默认值"""
        with patch("broca.session.database.get_configs") as mock_gc:
            mock_gc.return_value.database_dir = None
            db_dir, db_path = _get_database_config()
            assert ".broca" in db_dir
            assert db_path.endswith("sessions.db")


class TestGetDatabasePath:
    """测试 get_database_path 延迟计算和缓存"""

    def test_lazy_computation(self):
        """首次调用才计算，后续返回缓存"""
        _reset_database_state("")
        with patch("broca.session.database._get_database_config") as mock_cfg:
            mock_cfg.return_value = ("/tmp/fake", "/tmp/fake/sessions.db")
            # 首次调用触发计算
            result = get_database_path()
            assert result == ("/tmp/fake", "/tmp/fake/sessions.db")
            assert mock_cfg.call_count == 1
            # 第二次调用返回缓存
            result2 = get_database_path()
            assert result2 == result
            assert mock_cfg.call_count == 1  # 不再重新计算


class TestAsyncDatabaseManager:
    """测试 AsyncDatabaseManager 行为"""

    def setup_method(self):
        # 重置单例
        AsyncDatabaseManager._instance = None
        AsyncDatabaseManager._engine = None
        AsyncDatabaseManager._session_factory = None

    def teardown_method(self):
        # 清理
        AsyncDatabaseManager._instance = None
        AsyncDatabaseManager._engine = None
        AsyncDatabaseManager._session_factory = None
        import broca.session.database as db_mod
        db_mod._database_config_cache = None

    def test_singleton(self):
        """测试单例模式"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("broca.session.database.get_configs") as mock_gc:
                mock_gc.return_value.database_dir = tmpdir
                db1 = AsyncDatabaseManager()
                db2 = AsyncDatabaseManager()
                assert db1 is db2

    def test_lazy_init_not_triggered_on_construction(self):
        """构造时不初始化引擎（懒加载）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("broca.session.database.get_configs") as mock_gc:
                mock_gc.return_value.database_dir = tmpdir
                db = AsyncDatabaseManager()
                assert db._engine is None

    def test_get_engine_triggers_init(self):
        """get_engine() 触发懒加载初始化"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _reset_database_state(tmpdir)
            with patch("broca.session.database.get_configs") as mock_gc:
                mock_gc.return_value.database_dir = tmpdir
                db = AsyncDatabaseManager()
                assert db._engine is None
                engine = db.get_engine()
                assert engine is not None
                assert tmpdir in str(engine.url)

    def test_get_session_factory_triggers_init(self):
        """get_session_factory() 触发懒加载初始化"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _reset_database_state(tmpdir)
            with patch("broca.session.database.get_configs") as mock_gc:
                mock_gc.return_value.database_dir = tmpdir
                db = AsyncDatabaseManager()
                assert db._session_factory is None
                factory = db.get_session_factory()
                assert factory is not None

    @pytest.mark.asyncio
    async def test_get_session(self):
        """测试获取会话"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _reset_database_state(tmpdir)
            with patch("broca.session.database.get_configs") as mock_gc:
                mock_gc.return_value.database_dir = tmpdir
                db = AsyncDatabaseManager()
                async with db.get_session() as session:
                    assert session is not None

    @pytest.mark.asyncio
    async def test_close(self):
        """测试关闭连接"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _reset_database_state(tmpdir)
            with patch("broca.session.database.get_configs") as mock_gc:
                mock_gc.return_value.database_dir = tmpdir
                db = AsyncDatabaseManager()
                # 先初始化
                db.get_engine()
                assert db._engine is not None
                await db.close()
                assert db._engine is None

    @pytest.mark.asyncio
    async def test_session_context_manager(self):
        """测试会话上下文管理器"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _reset_database_state(tmpdir)
            with patch("broca.session.database.get_configs") as mock_gc:
                mock_gc.return_value.database_dir = tmpdir
                db = AsyncDatabaseManager()
                async with db.get_session() as session:
                    assert session is not None
