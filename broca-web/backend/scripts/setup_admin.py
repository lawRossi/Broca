#!/usr/bin/env python3
"""
setup_admin.py — 在安装过程中创建管理员账户

用法：
    python setup_admin.py [--db sqlite:///path/to/backend.db]
    python setup_admin.py --non-interactive [--username admin] [--password pass123]

流程：
  1. 连接数据库，检查是否有任何用户存在
  2. 已有用户 → 显示信息并跳过
  3. 无用户   → 交互式提示创建（或 --non-interactive 静默创建）

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
from datetime import datetime

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
    # 第一步：连接数据库，检查状态
    #   返回值: ("user_exists", id, username) | ("no_table",) | ("empty",)
    # ============================================================
    async def check_db_state():
        engine = create_async_engine(
            async_db_url,
            echo=False,
            poolclass=NullPool,
            connect_args={"check_same_thread": False},
        )
        try:
            async with engine.connect() as conn:
                # 检查 user_auth 表是否存在
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
                    return ("no_table",)

                # 表存在，查询是否有用户
                r = await conn.execute(text("SELECT id, username FROM user_auth LIMIT 1"))
                row = r.fetchone()
                if row:
                    return ("user_exists", row[0], row[1])
                return ("empty",)
        finally:
            await engine.dispose()

    state = asyncio.run(check_db_state())

    if state[0] == "no_table":
        print("  数据库表 user_auth 不存在，请先执行数据库迁移。")
        print("  运行: cd broca-web/backend && alembic upgrade head")
        return 1

    if state[0] == "user_exists":
        print(f"  ✓ 账户已存在: {state[2]} (ID: {state[1]}) — 跳过创建")
        return 0

    # ============================================================
    # 第二步：无用户，需要创建
    # ============================================================
    print("\n🔧 检测到尚未创建管理员账户，开始创建...\n")

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
    # 第三步：写入数据库
    # ============================================================
    async def insert_user():
        engine = create_async_engine(
            async_db_url,
            echo=False,
            poolclass=NullPool,
            connect_args={"check_same_thread": False},
        )
        try:
            async with engine.connect() as conn:
                user_id = str(uuid.uuid4())
                hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
                now = datetime.now(datetime.UTC)

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

    success = asyncio.run(insert_user())
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
