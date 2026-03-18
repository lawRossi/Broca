"""
数据库迁移管理模块

提供Alembic迁移的封装，方便在代码中管理数据库迁移。
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional


class DatabaseMigrationManager:
    """数据库迁移管理器"""

    def __init__(self, project_root: Optional[str] = None):
        """
        初始化迁移管理器

        Args:
            project_root: 项目根目录路径，如果为None则自动检测
        """
        if project_root is None:
            # 尝试自动检测项目根目录
            current_dir = Path(__file__).parent.parent.parent
            if (current_dir / "pyproject.toml").exists():
                self.project_root = str(current_dir)
            else:
                raise ValueError("无法自动检测项目根目录，请显式指定project_root参数")
        else:
            self.project_root = project_root

        self.alembic_ini = os.path.join(self.project_root, "alembic.ini")
        if not os.path.exists(self.alembic_ini):
            raise FileNotFoundError(f"未找到alembic配置文件: {self.alembic_ini}")

    def run_alembic_command(self, command: str, *args: str) -> bool:
        """
        运行Alembic命令

        Args:
            command: Alembic命令（如upgrade, downgrade, revision等）
            *args: 命令参数

        Returns:
            bool: 命令是否成功执行
        """
        cmd = [sys.executable, "-m", "alembic", command] + list(args)

        try:
            result = subprocess.run(
                cmd, cwd=self.project_root, capture_output=True, text=True, check=True
            )
            print(f"Alembic命令执行成功: {' '.join(cmd)}")
            if result.stdout:
                print(f"输出: {result.stdout}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"Alembic命令执行失败: {' '.join(cmd)}")
            print(f"错误输出: {e.stderr}")
            if e.stdout:
                print(f"标准输出: {e.stdout}")
            return False

    def create_migration(self, message: str, autogenerate: bool = True) -> bool:
        """
        创建新的迁移文件

        Args:
            message: 迁移描述
            autogenerate: 是否自动生成迁移脚本

        Returns:
            bool: 是否成功
        """
        if autogenerate:
            return self.run_alembic_command("revision", "--autogenerate", "-m", message)
        else:
            return self.run_alembic_command("revision", "-m", message)

    def upgrade_database(self, revision: str = "head") -> bool:
        """
        升级数据库到指定版本

        Args:
            revision: 目标版本，默认为最新版本（head）

        Returns:
            bool: 是否成功
        """
        return self.run_alembic_command("upgrade", revision)

    def downgrade_database(self, revision: str = "-1") -> bool:
        """
        降级数据库到指定版本

        Args:
            revision: 目标版本，默认为上一个版本（-1）

        Returns:
            bool: 是否成功
        """
        return self.run_alembic_command("downgrade", revision)

    def show_current_revision(self) -> bool:
        """
        显示当前数据库版本

        Returns:
            bool: 是否成功
        """
        return self.run_alembic_command("current")

    def show_migration_history(self) -> bool:
        """
        显示迁移历史

        Returns:
            bool: 是否成功
        """
        return self.run_alembic_command("history")

    def check_migration_status(self) -> bool:
        """
        检查迁移状态（是否有待应用的迁移）

        Returns:
            bool: 是否成功
        """
        return self.run_alembic_command("check")


# 全局迁移管理器实例
migration_manager = DatabaseMigrationManager()


# CLI命令接口
def handle_migration_command(command: str, *args: str) -> bool:
    """
    处理迁移命令

    Args:
        command: 命令名称
        *args: 命令参数

    Returns:
        bool: 是否成功
    """
    commands = {
        "create": lambda: migration_manager.create_migration(*args),
        "upgrade": lambda: migration_manager.upgrade_database(*args),
        "downgrade": lambda: migration_manager.downgrade_database(*args),
        "current": lambda: migration_manager.show_current_revision(),
        "history": lambda: migration_manager.show_migration_history(),
        "check": lambda: migration_manager.check_migration_status(),
    }

    if command not in commands:
        print(f"未知命令: {command}")
        print("可用命令: init, create, upgrade, downgrade, current, history, check")
        return False

    return commands[command]()
