import os
import sys
from logging.config import fileConfig

# Add the backend directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import engine_from_config, pool

# Import your models' Base.metadata for 'autogenerate' support
from sqlmodel import SQLModel

from alembic import context
from app.core.config import settings

# Import all models to ensure they are registered with SQLModel.metadata
from app.models import *  # noqa: F403

target_metadata = SQLModel.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _x_argument_db_url() -> str:
    """读取 `alembic -x db_url=...`（显式目标库，优先级最高）。

    `app/core/config.py::Settings` 明确移除了 `env_settings` 源（纯 .env 文件驱动，
    不读 os.environ），所以 `SQLITE_DATABASE_PATH` 之类的环境变量在迁移期会被
    静默忽略 —— 历史 bug：install.sh 用环境变量传目标库，迁移实际写到了
    backend 目录下的 dev.db，而运行时读的是 ~/.broca/data/backend.db。
    """
    try:
        x_args = context.get_x_argument(as_dictionary=True)
    except Exception:
        return ""
    return (x_args.get("db_url") or "").strip()


def get_database_url() -> str:
    """获取数据库连接URL"""
    # 1. -x db_url=...（安装脚本显式指定，保证与运行时同源）
    url = _x_argument_db_url()
    if url:
        return url

    # 2. 首先尝试从alembic.ini获取
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url

    # 3. 如果alembic.ini中没有配置，则从应用配置获取
    return settings.sync_database_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    # 获取数据库URL
    database_url = get_database_url()

    # 创建引擎配置
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = database_url

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
