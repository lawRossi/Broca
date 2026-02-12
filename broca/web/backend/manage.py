# ruff: noqa: S603, S607
# type: ignore

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

# 设置项目根目录
PROJECT_ROOT = Path(__file__).parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def get_poetry_cmd(base_cmd):
    # 检查是否在 Poetry 项目中
    poetry_lock = PROJECT_ROOT / "poetry.lock"
    pyproject = PROJECT_ROOT / "pyproject.toml"

    if poetry_lock.exists() and pyproject.exists():
        return ["poetry", "run", *base_cmd]
    else:
        return base_cmd


class DatabaseManager:
    """数据库管理类"""

    def __init__(self):
        self.alembic_cfg = PROJECT_ROOT / "alembic.ini"

    def init_db(self):
        """初始化数据库"""
        logger.info("正在初始化数据库...")
        try:
            # 创建数据库迁移环境
            cmd = get_poetry_cmd(["alembic", "init", "alembic"])
            subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)
            logger.info("数据库迁移环境初始化完成")
        except subprocess.CalledProcessError as e:
            logger.error(f"初始化数据库失败: {e}")
            raise

    def create_migration(self, message: str):
        """创建数据库迁移"""
        logger.info(f"正在创建迁移: {message}")
        try:
            cmd = get_poetry_cmd(["alembic", "revision", "--autogenerate", "-m", message])
            subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)
            logger.info("迁移文件创建成功")
        except subprocess.CalledProcessError as e:
            logger.error(f"创建迁移失败: {e}")
            raise

    def upgrade(self, revision: str = "head"):
        """升级数据库到指定版本"""
        logger.info(f"正在升级数据库到版本: {revision}")
        try:
            cmd = get_poetry_cmd(["alembic", "upgrade", revision])
            subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)
            logger.info("数据库升级成功")
        except subprocess.CalledProcessError as e:
            logger.error(f"升级数据库失败: {e}")
            raise

    def downgrade(self, revision: str = "-1"):
        """降级数据库"""
        logger.info(f"正在降级数据库到版本: {revision}")
        try:
            cmd = get_poetry_cmd(["alembic", "downgrade", revision])
            subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)
            logger.info("数据库降级成功")
        except subprocess.CalledProcessError as e:
            logger.error(f"降级数据库失败: {e}")
            raise

    def show_history(self):
        """显示迁移历史"""
        logger.info("数据库迁移历史:")
        try:
            cmd = get_poetry_cmd(["alembic", "history", "--verbose"])
            subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"获取迁移历史失败: {e}")
            raise

    def show_current(self):
        """显示当前数据库版本"""
        logger.info("当前数据库版本:")
        try:
            cmd = get_poetry_cmd(["alembic", "current"])
            subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"获取当前版本失败: {e}")
            raise


class ServerManager:
    """服务管理类"""

    def __init__(self):
        self.app_module = "app.main:app"
        self.host = os.getenv("HOST", "127.0.0.1")
        self.port = int(os.getenv("PORT", "9000"))
        self.reload = os.getenv("RELOAD", "true").lower() == "true"

    def start(self, host: str | None = None, port: int | None = None, reload: bool | None = None):
        """启动服务"""
        host = host or self.host
        port = port or self.port
        reload = reload if reload is not None else self.reload

        logger.info(f"正在启动服务... {host}:{port}")
        logger.info(f"热重载: {'开启' if reload else '关闭'}")

        cmd = get_poetry_cmd(
            [
                "uvicorn",
                self.app_module,
                "--host",
                host,
                "--port",
                str(port),
            ]
        )

        if reload:
            cmd.append("--reload")

        try:
            subprocess.run(cmd, cwd=PROJECT_ROOT)
        except KeyboardInterrupt:
            logger.info("服务已停止")
        except Exception as e:
            logger.error(f"启动服务失败: {e}")
            raise

    def start_dev(self):
        """开发环境启动"""
        logger.info("开发环境启动")
        self.start(reload=True)

    def start_prod(self):
        """生产环境启动"""
        logger.info("生产环境启动")
        self.start(reload=False)


class TestManager:
    """测试管理类"""

    def run_tests(self, test_path: str | None = None):
        """运行测试"""
        test_path = test_path or "app/tests"
        logger.info(f"正在运行测试: {test_path}")

        try:
            cmd = get_poetry_cmd(["pytest", test_path, "-v"])
            subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)
            logger.info("所有测试通过")
        except subprocess.CalledProcessError as e:
            logger.error(f"测试失败: {e}")
            raise


class UtilityManager:
    """工具管理类"""

    @staticmethod
    def check_dependencies():
        """检查依赖"""
        logger.info("检查项目依赖...")

        try:
            # 检查关键包
            packages = ["fastapi", "sqlalchemy", "alembic", "uvicorn", "pytest"]

            # 使用适当的Python解释器
            python_cmd = "python3" if Path("/usr/bin/python3").exists() else "python"

            for package in packages:
                result = subprocess.run(
                    [python_cmd, "-c", f"import {package}; print({package}.__version__)"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                logger.info(f"{package}: {result.stdout.strip()}")

        except subprocess.CalledProcessError as e:
            logger.error(f"依赖检查失败: {e}")
            raise

    @staticmethod
    def clean_cache():
        """清理缓存"""
        logger.info("清理缓存文件...")

        cache_patterns = ["__pycache__", "*.pyc", "*.pyo", ".pytest_cache", ".coverage", "htmlcov"]

        for pattern in cache_patterns:
            try:
                subprocess.run(["find", ".", "-name", pattern, "-type", "f", "-delete"], cwd=PROJECT_ROOT, check=True)
                logger.info(f"已清理: {pattern}")
            except subprocess.CalledProcessError as e:
                logger.warning(f"清理 {pattern} 失败: {e}")

        # 清理目录
        dirs_to_clean = ["__pycache__", ".pytest_cache", "htmlcov"]
        for dir_name in dirs_to_clean:
            dir_path = PROJECT_ROOT / dir_name
            if dir_path.exists():
                import shutil

                shutil.rmtree(dir_path)
                logger.info(f"已清理目录: {dir_name}")

    @staticmethod
    def install_dependencies():
        """安装依赖（Poetry）"""
        logger.info("安装项目依赖...")
        try:
            subprocess.run(["poetry", "install"], cwd=PROJECT_ROOT, check=True)
            logger.info("依赖安装完成")
        except subprocess.CalledProcessError as e:
            logger.error(f"依赖安装失败: {e}")
            raise

    @staticmethod
    def show_poetry_env():
        """显示 Poetry 环境信息"""
        logger.info("Poetry 环境信息:")
        try:
            subprocess.run(["poetry", "env", "info"], cwd=PROJECT_ROOT, check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"获取环境信息失败: {e}")
            raise


def main():
    parser = argparse.ArgumentParser(description="后端服务管理脚本")
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # 数据库命令
    db_parser = subparsers.add_parser("db", help="数据库管理")
    db_subparsers = db_parser.add_subparsers(dest="db_command")

    db_subparsers.add_parser("init", help="初始化数据库")
    db_subparsers.add_parser("history", help="显示迁移历史")
    db_subparsers.add_parser("current", help="显示当前版本")
    db_subparsers.add_parser("upgrade", help="升级数据库")
    db_subparsers.add_parser("downgrade", help="降级数据库")

    create_migration_parser = db_subparsers.add_parser("create", help="创建迁移")
    create_migration_parser.add_argument("message", help="迁移描述")

    upgrade_parser = db_subparsers.add_parser("upgrade_to", help="升级到指定版本")
    upgrade_parser.add_argument("revision", help="版本号")

    downgrade_parser = db_subparsers.add_parser("downgrade_to", help="降级到指定版本")
    downgrade_parser.add_argument("revision", help="版本号")

    # 服务器命令
    server_parser = subparsers.add_parser("server", help="服务管理")
    server_subparsers = server_parser.add_subparsers(dest="server_command")

    # 启动服务子命令
    run_parser = server_subparsers.add_parser("run", help="启动服务")
    run_parser.add_argument("--host", default="127.0.0.1", help="主机地址")
    run_parser.add_argument("--port", type=int, default=9000, help="端口号")
    run_parser.add_argument("--no-reload", action="store_true", help="禁用热重载")

    server_subparsers.add_parser("dev", help="开发环境启动")
    server_subparsers.add_parser("prod", help="生产环境启动")

    # 测试命令
    test_parser = subparsers.add_parser("test", help="测试管理")
    test_subparsers = test_parser.add_subparsers(dest="test_command")

    test_run_parser = test_subparsers.add_parser("run", help="运行测试")
    test_run_parser.add_argument("path", nargs="?", help="测试路径")

    # 工具命令
    util_parser = subparsers.add_parser("util", help="工具管理")
    util_subparsers = util_parser.add_subparsers(dest="util_command")

    util_subparsers.add_parser("check", help="检查依赖")
    util_subparsers.add_parser("clean", help="清理缓存")
    util_subparsers.add_parser("install", help="安装依赖")
    util_subparsers.add_parser("env", help="显示Poetry环境信息")

    # 解析参数
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        if args.command == "db":
            db_manager = DatabaseManager()

            if args.db_command == "init":
                db_manager.init_db()
            elif args.db_command == "history":
                db_manager.show_history()
            elif args.db_command == "current":
                db_manager.show_current()
            elif args.db_command == "upgrade":
                db_manager.upgrade()
            elif args.db_command == "downgrade":
                db_manager.downgrade()
            elif args.db_command == "create":
                db_manager.create_migration(args.message)
            elif args.db_command == "upgrade_to":
                db_manager.upgrade(args.revision)
            elif args.db_command == "downgrade_to":
                db_manager.downgrade(args.revision)

        elif args.command == "server":
            server_manager = ServerManager()

            if args.server_command == "run":
                reload = not args.no_reload
                server_manager.start(args.host, args.port, reload)
            elif args.server_command == "dev":
                server_manager.start_dev()
            elif args.server_command == "prod":
                server_manager.start_prod()

        elif args.command == "test":
            test_manager = TestManager()

            if args.test_command == "run":
                test_manager.run_tests(args.path)

        elif args.command == "util":
            util_manager = UtilityManager()

            if args.util_command == "check":
                util_manager.check_dependencies()
            elif args.util_command == "clean":
                util_manager.clean_cache()
            elif args.util_command == "install":
                util_manager.install_dependencies()
            elif args.util_command == "env":
                util_manager.show_poetry_env()

    except KeyboardInterrupt:
        logger.info("操作被用户中断")
    except Exception as e:
        logger.error(f"执行失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
