#!/usr/bin/env python3
"""
setup_admin.py — 创建或更新管理员账户

用法：
    python setup_admin.py [--db sqlite:///path/to/backend.db]
    python setup_admin.py --non-interactive [--username admin] [--password pass123]

流程：
  1. 连接数据库，检查 user_auth 表是否存在
  2. 交互式提示输入用户名和密码（或 --non-interactive 静默创建）
  3. 用户名已存在 → 更新密码；不存在 → 创建新用户

支持环境变量覆盖：
    SQLITE_DATABASE_PATH — 数据库路径（默认 ~/.broca/data/backend.db）
    ADMIN_USERNAME       — 管理员用户名（默认 admin）
    ADMIN_PASSWORD       — 管理员密码（默认交互式输入）
"""

import argparse
import getpass
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(SCRIPT_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def ensure_deps():
    missing = []
    try:
        import bcrypt  # noqa: F401
    except ImportError:
        missing.append("bcrypt")
    try:
        import sqlalchemy  # noqa: F401
    except ImportError:
        missing.append("sqlalchemy")
    try:
        import aiosqlite  # noqa: F401
    except ImportError:
        missing.append("aiosqlite")

    if missing:
        print(f"  正在安装缺失的依赖: {', '.join(missing)} ...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", *missing],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("  依赖安装完成。")


def resolve_db_url(args) -> str:
    db_url = args.db or os.getenv("SQLITE_DATABASE_PATH", "")
    if not db_url:
        broca_home = os.path.expanduser("~/.broca")
        db_url = f"sqlite:///{broca_home}/data/backend.db"
    return db_url


def to_async_url(db_url: str) -> str:
    if db_url.startswith("sqlite:///"):
        return db_url.replace("sqlite:///", "sqlite+aiosqlite:///")
    return db_url


def main():
    parser = argparse.ArgumentParser(description="创建管理员账户（安装时使用）")
    parser.add_argument("--db", help="数据库连接 URL（如 sqlite:///path/to/backend.db）")
    parser.add_argument("--username", help="管理员用户名（默认 admin）")
    parser.add_argument("--password", help="管理员密码（默认交互式输入）")
    parser.add_argument("--non-interactive", action="store_true", help="非交互模式，不提示输入")
    args = parser.parse_args()

    ensure_deps()

    import asyncio
    import bcrypt
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    db_url = resolve_db_url(args)
    async_db_url = to_async_url(db_url)

    # ============================================================
    # 第一步：检查数据库表是否存在
    # ============================================================
    async def check_table_exists():
        engine = create_async_engine(
            async_db_url,
            echo=False,
            poolclass=NullPool,
            connect_args={"check_same_thread": False},
        )
        try:
            async with engine.connect() as conn:
                is_sqlite = "sqlite" in async_db_url
                if is_sqlite:
                    r = await conn.execute(
                        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
                        {"name": "user_auth"},
                    )
                else:
                    r = await conn.execute(
                        text("SELECT table_name FROM information_schema.tables WHERE table_name=:name"),
                        {"name": "user_auth"},
                    )
                if r.fetchone() is None:
                    return False
                return True
        finally:
            await engine.dispose()

    if not asyncio.run(check_table_exists()):
        print("  数据库表 user_auth 不存在，请先执行数据库迁移。")
        print("  运行: cd broca-web/backend && alembic upgrade head")
        return 1

    # ============================================================
    # 第二步：创建管理员账户（始终创建/更新）
    # ============================================================
    print("\n🔧 创建管理员账户...\n")

    username = (args.username or os.getenv("ADMIN_USERNAME", "admin")).strip()
    password = args.password or os.getenv("ADMIN_PASSWORD", "")

    if not args.non_interactive and not password:
        # 交互式输入
        inp = input(f"管理员用户名 [{username}]: ").strip()
        if inp:
            username = inp

        while True:
            pwd1 = getpass.getpass("管理员密码（至少6位）: ")
            if len(pwd1) < 6:
                print("  密码至少需要6位字符，请重新输入。")
                continue
            pwd2 = getpass.getpass("确认密码: ")
            if pwd1 != pwd2:
                print("  两次密码不一致，请重新输入。")
                continue
            password = pwd1
            break

    # 如果仍无密码，生成随机密码
    if not password:
        import secrets
        import string

        password = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
        print(f"\n⚠  未指定密码，已生成随机密码: {password}")
        print("   请立即保存此密码！\n")

    # ============================================================
    # 第三步：写入数据库（用户名已存在则更新密码）
    # ============================================================
    async def upsert_user():
        engine = create_async_engine(
            async_db_url,
            echo=False,
            poolclass=NullPool,
            connect_args={"check_same_thread": False},
        )
        try:
            async with engine.connect() as conn:
                # 检查用户名是否已存在
                r = await conn.execute(
                    text("SELECT id FROM user_auth WHERE username = :username"),
                    {"username": username},
                )
                existing = r.fetchone()

                hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
                now = datetime.now(timezone.utc)

                if existing:
                    # 更新已有用户的密码
                    await conn.execute(
                        text(
                            "UPDATE user_auth SET hashed_password = :hashed_password "
                            "WHERE username = :username"
                        ),
                        {
                            "hashed_password": hashed,
                            "username": username,
                        },
                    )
                    await conn.commit()
                    print(f"  ✅ 管理员账户密码已更新!")
                    print(f"     用户名: {username}")
                    print(f"     ID:     {existing[0]}")
                else:
                    # 创建新用户
                    user_id = str(uuid.uuid4())
                    await conn.execute(
                        text(
                            "INSERT INTO user_auth (id, username, hashed_password, created_at) "
                            "VALUES (:id, :username, :hashed_password, :created_at)"
                        ),
                        {
                            "id": user_id,
                            "username": username,
                            "hashed_password": hashed,
                            "created_at": now,
                        },
                    )
                    await conn.commit()
                    print(f"  ✅ 管理员账户创建成功!")
                    print(f"     用户名: {username}")
                    print(f"     ID:     {user_id}")
                return True
        finally:
            await engine.dispose()

    success = asyncio.run(upsert_user())
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
