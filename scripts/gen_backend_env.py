#!/usr/bin/env python3
"""生成生产环境的后端 `.env` 文件，并自检是否满足 App 的生产安全护栏。

背景（bug）：
    `install.sh` 原先用裸 heredoc 生成 `.env`：
        ENV=production
        JWT_SECRET=${JWT_SECRET:-}        # 空
        CORS_ALLOW_ORIGINS=${CORS_ORIGINS:-*}   # 通配符
    而 `app/core/config.py::_enforce_production_safety` 在 `ENV=production` 时
    拒绝空 JWT_SECRET 和 `*` 通配 CORS。结果 `Settings()` 在 import 阶段抛异常，
    uvicorn 秒退 → supervisor FATAL → nginx 对 /api/* 全部 502 → 页面打不开。

本脚本负责：
  1. 生成 JWT_SECRET（未显式提供时）
  2. 重装时复用旧密钥，避免轮换导致所有登录态失效
  3. 生成显式的 CORS 白名单（不用 *）
  4. 生成后立即用 App 自己的 Settings 校验，不通过则回滚并报错
  5. 拒绝生成 BROCA_CONFIG 指向 `configs.dev.json` 的生产配置
  6. 清理部署目录里残留的 `.env.local` / `.env.production` / `.env.development`
     —— 它们的优先级高于 `.env`（连 `_env_file` 显式指定都压不住），
     会把生产实例悄悄切回 dev 配置，因此必须在自检前删除

用法：
    python scripts/gen_backend_env.py \\
        --out ~/.broca/web/backend/.env \\
        --backend-dir ~/.broca/web/backend \\
        --broca-home ~/.broca \\
        --port 9000 --socketio-port 6868
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import shutil
import sys
import tempfile
from pathlib import Path

# Settings 里的 dev 默认密钥；生产环境禁止使用
DEV_JWT_DEFAULT = "broca-default-dev-secret-change-in-production"

# 开发环境专用的配置文件名。生产实例指向它 = 数据写进 backend/.local-data，
# 且 log_level=DEBUG、数据目录脱离 ~/.broca —— 属于静默的数据隔离事故。
DEV_CONFIG_FILENAME = "configs.dev.json"

# 会被 pydantic-settings 额外加载、且优先级高于 `.env` 的 env 文件。
# 只要部署目录里残留其中任何一个（例如有人照 .env.example 的注释把它复制成
# .env.local），里面若写着 BROCA_CONFIG=./configs.dev.json，就会盖掉本脚本
# 生成的生产配置。所以生成成功后必须清理掉它们。
STRAY_ENV_FILES = (".env.local", ".env.production", ".env.development")

# nginx 同域反代前端使用的端口（HTTP / HTTPS）
FRONTEND_HTTP_PORT = 5166
FRONTEND_HTTPS_PORT = 8443


def default_cors_origins() -> str:
    """nginx 同域反代下的默认 CORS 白名单。

    浏览器访问 http://localhost:5166 时，/api 请求是同源的，本身不触发 CORS；
    这里给显式白名单只是为了满足生产护栏（禁止 `*`），并兼容直连后端的调试场景。
    """
    origins: list[str] = []
    for host in ("localhost", "127.0.0.1"):
        for port in (FRONTEND_HTTP_PORT, FRONTEND_HTTPS_PORT):
            for scheme in ("http", "https"):
                origins.append(f"{scheme}://{host}:{port}")
    return ",".join(origins)


def read_existing_jwt_secret(env_path: Path) -> str:
    """从已有的 .env 中读取 JWT_SECRET（重装时复用，避免轮换）。"""
    if not env_path.is_file():
        return ""
    try:
        content = env_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(r"^JWT_SECRET=(.*)$", content, re.MULTILINE)
    if not match:
        return ""
    value = match.group(1).strip()
    if not value or value == DEV_JWT_DEFAULT:
        return ""
    return value


def resolve_jwt_secret(explicit: str, env_path: Path) -> str:
    """确定最终的 JWT_SECRET：显式指定 > 已有值 > 新生成。"""
    explicit = (explicit or "").strip()
    if explicit and explicit != DEV_JWT_DEFAULT:
        return explicit
    existing = read_existing_jwt_secret(env_path)
    if existing:
        return existing
    return secrets.token_hex(32)


def render_env(
    *,
    port: int,
    socketio_port: int,
    broca_home: Path,
    jwt_secret: str,
    cors_origins: str,
) -> str:
    """渲染 .env 内容。

    注意：只写入 Settings 里真实存在的字段。历史上这里写过
    BROCA_DATABASE_DIR / BROCA_LLM_CONFIG，但 Settings 没有对应字段
    （extra="ignore" 会静默丢弃），属于"看起来生效其实无效"的陷阱，已移除。
    """
    return (
        "# 生产环境配置（由 scripts/gen_backend_env.py 自动生成，请勿手工编辑）\n"
        "# 重新生成请执行: broca service install 或 scripts/install.sh\n"
        "ENV=production\n"
        f"PORT={port}\n"
        f"BROCA_SOCKETIO_PORT={socketio_port}\n"
        f"BROCA_CONFIG={broca_home}/configs/configs.json\n"
        f"SQLITE_DATABASE_PATH=sqlite:///{broca_home}/data/backend.db\n"
        f"JWT_SECRET={jwt_secret}\n"
        f"CORS_ALLOW_ORIGINS={cors_origins}\n"
    )


def assert_not_dev_config(content: str) -> None:
    """禁止生成指向 configs.dev.json 的生产配置。

    Raises:
        RuntimeError: BROCA_CONFIG 指向 dev 配置。
    """
    for line in content.splitlines():
        key, sep, value = line.strip().partition("=")
        if not sep or key.strip() != "BROCA_CONFIG":
            continue
        value = value.strip()
        if value and Path(value).name == DEV_CONFIG_FILENAME:
            raise RuntimeError(
                f"生产配置的 BROCA_CONFIG 指向 {DEV_CONFIG_FILENAME}（{value}）—— "
                "这会让生产实例使用 dev 数据目录/DEBUG 日志，必须指向 "
                "~/.broca/configs/configs.json"
            )


def purge_stray_env_files(env_path: Path) -> list[Path]:
    """删除会覆盖 `.env` 的残留 env 文件（.env.local 等）。

    Returns:
        实际被删除的文件路径列表（空列表 = 本来就没有）。
    """
    removed: list[Path] = []
    for name in STRAY_ENV_FILES:
        candidate = env_path.parent / name
        if candidate.is_file():
            candidate.unlink(missing_ok=True)
            removed.append(candidate)
    return removed


def validate_env_file(env_path: Path, backend_dir: Path) -> None:
    """用 App 自己的 Settings 校验生成的 .env。

    Raises:
        RuntimeError: 校验失败（含无法导入 Settings 的情况）。
    """
    backend_dir = backend_dir.resolve()
    if not (backend_dir / "app" / "core" / "config.py").is_file():
        raise RuntimeError(f"未找到 {backend_dir}/app/core/config.py，无法自检")

    sys.path.insert(0, str(backend_dir))
    old_cwd = Path.cwd()
    try:
        os.chdir(backend_dir)
        from app.core.config import Settings

        Settings(_env_file=str(env_path))  # noqa: F841 — 触发校验
    except Exception as exc:  # noqa: BLE001 — 需要把任何失败都转成可读信息
        raise RuntimeError(f"{type(exc).__name__}: {exc}") from exc
    finally:
        os.chdir(old_cwd)
        if str(backend_dir) in sys.path:
            sys.path.remove(str(backend_dir))


def write_env_atomic(env_path: Path, content: str) -> None:
    """原子写入，避免半截文件。"""
    env_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(env_path.parent), prefix=".env.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_name, env_path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def generate(
    *,
    out: Path,
    broca_home: Path,
    port: int = 9000,
    socketio_port: int = 6868,
    jwt_secret: str = "",
    cors_origins: str = "",
    backend_dir: Path | None = None,
    validate: bool = True,
) -> Path:
    """生成 .env；返回写入路径。

    Raises:
        RuntimeError: 自检未通过（此时已回滚到原文件）。
    """
    cors = (cors_origins or "").strip()
    if not cors or cors == "*":
        cors = default_cors_origins()

    secret = resolve_jwt_secret(jwt_secret, out)
    content = render_env(
        port=port,
        socketio_port=socketio_port,
        broca_home=broca_home,
        jwt_secret=secret,
        cors_origins=cors,
    )
    # 写盘前先拦：生产配置绝不能指向 dev 配置
    assert_not_dev_config(content)

    # 清理残留的高优先级 env 文件（.env.local 等）必须在**自检之前**：
    # pydantic-settings 会把这些文件一并加载且优先级高于 `.env`，
    # 不先删掉的话自检读到的根本不是我们刚写的内容。
    for stray in purge_stray_env_files(out):
        print(f"[gen_backend_env] 已删除残留 env 文件（会覆盖 .env）: {stray}", file=sys.stderr)

    backup: Path | None = None
    if out.is_file():
        fd, backup_name = tempfile.mkstemp(dir=str(out.parent), prefix=".env.bak.", suffix=".tmp")
        os.close(fd)
        backup = Path(backup_name)
        shutil.copy2(out, backup)

    write_env_atomic(out, content)

    if validate and backend_dir is not None:
        try:
            validate_env_file(out, backend_dir)
        except RuntimeError:
            if backup is not None:
                os.replace(backup, out)
            else:
                out.unlink(missing_ok=True)
            raise
    if backup is not None:
        backup.unlink(missing_ok=True)

    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成生产环境后端 .env 并自检")
    parser.add_argument("--out", required=True, help=".env 输出路径")
    parser.add_argument(
        "--backend-dir",
        default="",
        help="已部署的 backend 目录（用于导入 Settings 自检）；留空则跳过自检",
    )
    parser.add_argument("--broca-home", default=str(Path.home() / ".broca"))
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--socketio-port", type=int, default=6868)
    parser.add_argument("--jwt-secret", default="", help="留空则复用旧值或自动生成")
    parser.add_argument("--cors-origins", default="", help="留空/`*` 则使用显式默认白名单")
    parser.add_argument("--no-validate", action="store_true", help="跳过自检")
    args = parser.parse_args(argv)

    out = Path(args.out).expanduser()
    backend_dir = Path(args.backend_dir).expanduser() if args.backend_dir else None
    broca_home = Path(args.broca_home).expanduser()

    try:
        generate(
            out=out,
            broca_home=broca_home,
            port=args.port,
            socketio_port=args.socketio_port,
            jwt_secret=args.jwt_secret,
            cors_origins=args.cors_origins,
            backend_dir=backend_dir,
            validate=not args.no_validate,
        )
    except RuntimeError as exc:
        print(f"[gen_backend_env] 自检失败，已回滚 {out}: {exc}", file=sys.stderr)
        return 1

    print(f"[gen_backend_env] 已生成 {out}（自检{'通过' if backend_dir and not args.no_validate else '已跳过'}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
