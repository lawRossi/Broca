"""
Session Cleanup Service

在 Session 删除后清理所有关联资源：
- Workspace 本地文件（session memory、agent config cache 等）
- Runner 日志文件
- 孤立的 ScheduledJob 记录
- Git 快照仓库（当 workspace 下无其他 session 时）

容错原则：每个清理步骤独立 try/except，单项失败仅 log warning，不向上抛异常。
"""

import shutil
from pathlib import Path
from typing import Optional

from sqlmodel import select, func

from broca.logging_config import get_logger

logger = get_logger(__name__)


class SessionCleanupService:
    """
    Session 清理服务

    单例，封装 session 删除后的所有资源清理逻辑。
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def cleanup_session(
        self, workspace: Optional[str], session_id: str
    ) -> None:
        """
        清理 session 删除后的所有残留资源

        每个子方法独立容错，单项失败不影响其他项。

        Args:
            workspace: 工作空间路径（可能为 None）
            session_id: 要清理的 session ID
        """
        logger.info(f"Cleaning up session {session_id} artifacts...")

        # 1. 清理 workspace 本地文件
        try:
            await self.cleanup_workspace_files(workspace, session_id)
        except Exception as e:
            logger.warning(
                f"Failed to cleanup workspace files for session {session_id}: {e}"
            )

        # 2. 清理 runner 日志
        try:
            await self.cleanup_runner_logs(session_id)
        except Exception as e:
            logger.warning(
                f"Failed to cleanup runner logs for session {session_id}: {e}"
            )

        # 3. 清理孤立的 scheduled jobs
        try:
            deleted_jobs = await self.cleanup_orphaned_jobs(session_id)
            if deleted_jobs:
                logger.info(
                    f"Cleaned up {deleted_jobs} orphaned scheduled job(s) "
                    f"for session {session_id}"
                )
        except Exception as e:
            logger.warning(
                f"Failed to cleanup orphaned jobs for session {session_id}: {e}"
            )

        # 4. 如果是 workspace 下最后一个 session，清理 git 快照
        try:
            await self.cleanup_snapshots_if_last_session(workspace)
        except Exception as e:
            logger.warning(
                f"Failed to cleanup snapshots for workspace {workspace}: {e}"
            )

    async def cleanup_workspace_files(
        self, workspace: Optional[str], session_id: str
    ) -> None:
        """
        删除 workspace 下的 session 本地文件

        删除 {workspace}/.broca/{session_id}/ 目录，包含：
        - session-memory.md / session-memory_latest.md
        - agents/{agent_name}.json (agent config cache)
        - 其他 session 级文件

        Args:
            workspace: 工作空间路径
            session_id: session ID
        """
        if not workspace:
            logger.debug(
                f"Skipping workspace file cleanup for session {session_id}: "
                f"no workspace specified"
            )
            return

        session_dir = Path(workspace) / ".broca" / session_id
        if session_dir.exists():
            logger.info(f"Removing session workspace dir: {session_dir}")
            shutil.rmtree(str(session_dir), ignore_errors=True)
        else:
            logger.debug(
                f"No workspace dir to cleanup: {session_dir} (does not exist)"
            )

    async def cleanup_runner_logs(self, session_id: str) -> None:
        """
        删除 runner 日志目录

        删除 ~/.broca/logs/runners/{session_id}/ 目录

        Args:
            session_id: session ID
        """
        log_dir = Path.home() / ".broca" / "logs" / "runners" / session_id
        if log_dir.exists():
            logger.info(f"Removing runner log dir: {log_dir}")
            shutil.rmtree(str(log_dir), ignore_errors=True)
        else:
            logger.debug(
                f"No runner log dir to cleanup: {log_dir} (does not exist)"
            )

    async def cleanup_orphaned_jobs(self, session_id: str) -> int:
        """
        取消并删除与该 session 关联的 scheduled jobs

        对每条记录先将 status 设为 CANCELLED，然后删除（CASCADE 删除 job_execution）。

        Args:
            session_id: session ID

        Returns:
            删除的 job 数量
        """
        from broca.session.database import db_manager
        from broca.session.models import ScheduledJob, JobStatus

        from datetime import datetime, timezone

        async with db_manager.get_session() as db_session:
            stmt = select(ScheduledJob).where(
                ScheduledJob.session_id == session_id
            )
            result = await db_session.exec(stmt)
            jobs = result.all()

            count = 0
            for job in jobs:
                # 先标记为取消（审计意义），再删除记录（CASCADE 删除 job_execution）
                if job.status != JobStatus.CANCELLED:
                    job.status = JobStatus.CANCELLED
                    job.updated_at = datetime.now(timezone.utc)
                    db_session.add(job)
                await db_session.delete(job)
                count += 1

            if count:
                await db_session.commit()
                logger.info(
                    f"Cancelled and deleted {count} scheduled job(s) for session {session_id}"
                )

            return count

    async def cleanup_snapshots_if_last_session(
        self, workspace: Optional[str]
    ) -> None:
        """
        如果该 workspace 下没有剩余 session，清理 git 快照仓库

        Args:
            workspace: 工作空间路径
        """
        if not workspace:
            logger.debug(
                "Skipping snapshot cleanup: no workspace specified"
            )
            return

        # 查询该 workspace 下剩余的 session 数量
        from broca.session.database import db_manager
        from broca.session.models import Session

        async with db_manager.get_session() as db_session:
            stmt = select(func.count(Session.session_id)).where(
                Session.workspace == workspace
            )
            result = await db_session.exec(stmt)
            remaining_count = result.one()

        if remaining_count > 0:
            logger.debug(
                f"Skipping snapshot cleanup for workspace {workspace}: "
                f"{remaining_count} session(s) still exist"
            )
            return

        # 最后一个 session 已被删除，清理 git 快照仓库
        from broca.snapshot.git_manager import GitManager

        git_manager = GitManager(workspace)

        # 使用文件锁保护，防止并发操作
        if git_manager.repo_path.exists():
            logger.info(
                f"Cleaning up snapshot repo for workspace {workspace}: "
                f"{git_manager.repo_path}"
            )
            try:
                git_manager.acquire_lock(blocking=True)
                try:
                    git_manager.cleanup()
                finally:
                    git_manager.release_lock()
            except Exception as e:
                logger.warning(
                    f"Failed to acquire lock for snapshot cleanup: {e}"
                )
                raise
        else:
            logger.debug(
                f"No snapshot repo to cleanup for workspace {workspace}"
            )
