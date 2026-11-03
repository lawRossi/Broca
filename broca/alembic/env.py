"""Alembic 迁移环境配置

数据库 URL 获取优先级:
  1. alembic -x db_url=<完整 URL>  （安装脚本显式传入，保证"迁移的库 == 运行时读写的库"）
  2. 环境变量: BROCA_DATABASE_DIR (指向目录, 自动拼接 sessions.db)
  3. configs.json 的 database_dir (get_configs())
  4. alembic.ini 中的 sqlalchemy.url
  5. 默认: ~/.broca/data/sessions.db
"""

import os
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 注册模型
from broca.session.models import SQLModel  # noqa: E402
target_metadata = SQLModel.metadata


def _x_argument_db_url() -> str:
    """读取 `alembic -x db_url=...`（显式目标库，优先级最高）。

    安装脚本用 `-x db_url=` 传目标库，而不是用环境变量：
    `app/core/config.py` 与 `broca/configs.py` 都是纯文件驱动（不读 os.environ），
    环境变量在运行时会被静默忽略，用它传迁移目标必然导致
    「表建在一个库、运行时读写另一个库」。
    """
    try:
        x_args = context.get_x_argument(as_dictionary=True)
    except Exception:
        return ""
    return (x_args.get("db_url") or "").strip()


def _env_var_db_url() -> str:
    """BROCA_DATABASE_DIR 环境变量（指向目录，自动拼接 sessions.db）。"""
    db_dir = os.environ.get("BROCA_DATABASE_DIR", "").strip()
    if not db_dir:
        return ""
    return f"sqlite:///{Path(db_dir).expanduser() / 'sessions.db'}"


def get_database_url() -> str:
    """获取数据库 URL，按优先级返回"""
    # 1. -x db_url=...（安装脚本显式指定）
    url = _x_argument_db_url()
    if url:
        return url

    # 2. 环境变量 BROCA_DATABASE_DIR
    url = _env_var_db_url()
    if url:
        return url

    # 3. 从 configs.json 读取
    try:
        from broca.configs import get_configs
        db_dir = get_configs().database_dir
        if db_dir:
            return f"sqlite:///{Path(db_dir, 'sessions.db')}"
    except Exception:
        pass

    # 4. alembic.ini 中的配置
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url

    # 5. 默认路径
    default_dir = Path.home() / ".broca" / "data"
    return f"sqlite:///{default_dir / 'sessions.db'}"


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
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
    """Run migrations in 'online' mode."""
    url = get_database_url()
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = url

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={"check_same_thread": False},
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
