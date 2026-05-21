"""Alembic 迁移环境配置

数据库 URL 获取优先级:
  1. 环境变量: BROCA_DATABASE_DIR (指向目录, 自动拼接 sessions.db)
  2. alembic.ini 中的 sqlalchemy.url
  3. 默认: ~/.broca/data/sessions.db
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
from broca.session.models import SQLModel
target_metadata = SQLModel.metadata


def get_database_url() -> str:
    """获取数据库 URL，按优先级返回"""
    # 1. 环境变量 BROCA_DATABASE_DIR
    db_dir = os.getenv("BROCA_DATABASE_DIR")
    if db_dir:
        return f"sqlite:///{Path(db_dir, 'sessions.db')}"

    # 2. alembic.ini 中的配置
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url

    # 3. 默认路径
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
