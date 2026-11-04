"""Runner 持久化仓库。

把原先散落在 ``manager.py`` 中 5 处 ``async with db_manager.get_session()``
的 SQLModel 直写逻辑收敛到一处：

- ``upsert`` / ``upsert_many``   —— 替代「先 SELECT 再 UPDATE」的两次往返
- ``delete`` / ``get`` / ``list_active``
- ``set_agent_status`` / ``set_agent_statuses`` / ``mark_agents_disconnected``

``upsert_many`` 在**单个 DB session 内**批量写入并只 ``commit()`` 一次，
把 N 个 runner 的 2N 次往返降为 1 次（P1-5 的「单事务批量」部分；
时间维度聚合由 ``HeartbeatMonitor`` / manager 侧的 flush 窗口负责，两者不重叠）。

``set_agent_statuses`` 是跨 session 的批量版本：一次
``SELECT ... WHERE session_id IN (...)`` + 一次 ``commit()``，
把 N 个 session 的 N 次往返降为 1 次（Task 4.3）。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Optional

from sqlmodel import select

from broca.session_runner.models import RunnerProcessInfo, RunnerStatus

logger = logging.getLogger(__name__)

# upsert 时需要覆盖的列（不含主键 runner_id / created_at / session_id）
_UPDATABLE_COLUMNS = (
    "pid",
    "status",
    "ipc_address",
    "ipc_family",
    "started_at",
    "last_heartbeat",
    "restart_count",
    "resource_info",
    "error_message",
)


def runner_row_id(session_id: str) -> str:
    """生成 runner 主键。

    使用 sha1 摘要而非 ``session_id[:16]``：后者在前 16 字符相同的两个
    session 之间会撞主键，upsert 会静默写错行。
    """
    import hashlib

    digest = hashlib.sha1(session_id.encode()).hexdigest()[:16]
    return f"runner_{digest}"


class RunnerRepository:
    """SessionRunner / Agent 状态的持久化入口。"""

    def __init__(self, db: Any = None):
        # db 需提供 ``get_session()`` 异步上下文管理器；默认使用全局 db_manager
        self._db = db

    @property
    def db(self) -> Any:
        if self._db is None:
            from broca.session.database import db_manager

            return db_manager
        return self._db

    # ------------------------------------------------------------------
    # 行转换
    # ------------------------------------------------------------------

    @staticmethod
    def _to_row_values(info: RunnerProcessInfo) -> dict[str, Any]:
        return {
            "runner_id": runner_row_id(info.session_id),
            "session_id": info.session_id,
            "pid": info.pid,
            "status": info.status.value,
            "ipc_address": info.ipc_address,
            "ipc_family": info.ipc_family,
            "started_at": info.started_at,
            "last_heartbeat": info.last_heartbeat,
            "restart_count": info.restart_count,
            "resource_info": info.resource_usage,
            "error_message": info.error_message,
            "created_at": datetime.now(UTC),
        }

    @staticmethod
    def _to_info(row: Any) -> RunnerProcessInfo:
        try:
            status = RunnerStatus(row.status)
        except ValueError:
            status = RunnerStatus.UNKNOWN
        return RunnerProcessInfo(
            session_id=row.session_id,
            process=None,
            pid=row.pid,
            status=status,
            started_at=row.started_at,
            ipc_address=row.ipc_address,
            ipc_family=row.ipc_family,
            last_heartbeat=row.last_heartbeat,
            restart_count=row.restart_count,
            resource_usage=row.resource_info,
            error_message=row.error_message,
        )

    @staticmethod
    def _dialect_name(session: Any) -> str:
        try:
            return session.get_bind().dialect.name
        except Exception:  # pragma: no cover - 兜底
            return "sqlite"

    # ------------------------------------------------------------------
    # Runner 记录
    # ------------------------------------------------------------------

    async def upsert(self, info: RunnerProcessInfo) -> None:
        """插入或更新单条 runner 记录。"""
        await self.upsert_many([info])

    async def upsert_many(self, infos: Iterable[RunnerProcessInfo]) -> int:
        """批量插入/更新（单事务、一次 commit）。

        Returns:
            写入的记录条数
        """
        values_list = [self._to_row_values(info) for info in infos]
        if not values_list:
            return 0

        from broca.session.models import SessionRunner

        async with self.db.get_session() as session:
            dialect = self._dialect_name(session)

            if dialect == "sqlite":
                # 当前只有 SQLite；扩展点：其它方言走下面的通用分支
                from sqlalchemy.dialects.sqlite import insert as sqlite_insert

                for values in values_list:
                    stmt = sqlite_insert(SessionRunner).values(**values)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["session_id"],
                        set_={col: values[col] for col in _UPDATABLE_COLUMNS},
                    )
                    await session.execute(stmt)
            else:  # pragma: no cover - 当前无此方言
                for values in values_list:
                    existing = (
                        await session.exec(
                            select(SessionRunner).where(
                                SessionRunner.session_id == values["session_id"]
                            )
                        )
                    ).first()
                    if existing is None:
                        session.add(SessionRunner(**values))
                    else:
                        for col in _UPDATABLE_COLUMNS:
                            setattr(existing, col, values[col])
                        session.add(existing)

            await session.commit()

        return len(values_list)

    async def delete(self, session_id: str) -> bool:
        """删除 runner 记录。Returns: 是否真的删除了记录。"""
        from broca.session.models import SessionRunner

        async with self.db.get_session() as session:
            row = (
                await session.exec(
                    select(SessionRunner).where(
                        SessionRunner.session_id == session_id
                    )
                )
            ).first()
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def get(self, session_id: str) -> Optional[RunnerProcessInfo]:
        """读取单条 runner 记录（不存在返回 None）。"""
        from broca.session.models import SessionRunner

        async with self.db.get_session() as session:
            row = (
                await session.exec(
                    select(SessionRunner).where(
                        SessionRunner.session_id == session_id
                    )
                )
            ).first()
            return None if row is None else self._to_info(row)

    async def list_active(self) -> list[RunnerProcessInfo]:
        """列出所有非 dead 状态的 runner 记录（纯数据，无 detached ORM 对象）。"""
        from broca.session.models import SessionRunner

        async with self.db.get_session() as session:
            rows = (
                await session.exec(
                    select(SessionRunner).where(SessionRunner.status != "dead")  # type: ignore[arg-type]
                )
            ).all()
            return [self._to_info(row) for row in rows]

    # ------------------------------------------------------------------
    # Agent 状态
    # ------------------------------------------------------------------

    async def set_agent_status(
        self, session_id: str, statuses: dict[str, str]
    ) -> int:
        """按 ``{agent_id: status}`` 同步该 session 下的 Agent 状态。

        Returns:
            实际发生变化的行数
        """
        from broca.session.models import Agent

        async with self.db.get_session() as session:
            agents = (
                await session.exec(
                    select(Agent).where(Agent.session_id == session_id)
                )
            ).all()

            changed = []
            for agent in agents:
                new_status = statuses.get(agent.agent_id)
                if new_status and new_status != agent.agent_status:
                    agent.agent_status = new_status
                    changed.append(agent)

            if changed:
                session.add_all(changed)
                await session.commit()

            return len(changed)

    async def set_agent_statuses(
        self, statuses_by_session: dict[str, dict[str, str]]
    ) -> int:
        """跨 session 批量同步 Agent 状态（单次 SELECT + 单次 commit）。

        历史问题（P1-5）：心跳每 5s 一次，每个 session 一次
        ``SELECT + commit``；10 个 session 就是每秒 2 次 commit，
        写放大与 session 数线性相关。

        Args:
            statuses_by_session: ``{session_id: {agent_id: status}}``

        Returns:
            实际发生变化的行数
        """
        from broca.session.models import Agent

        wanted = {sid: dict(m) for sid, m in statuses_by_session.items() if m}
        if not wanted:
            return 0

        async with self.db.get_session() as session:
            agents = (
                await session.exec(
                    select(Agent).where(
                        Agent.session_id.in_(list(wanted))  # type: ignore[attr-defined]
                    )
                )
            ).all()

            changed = []
            for agent in agents:
                new_status = wanted.get(agent.session_id, {}).get(agent.agent_id)
                if new_status and new_status != agent.agent_status:
                    agent.agent_status = new_status
                    changed.append(agent)

            if changed:
                session.add_all(changed)
                await session.commit()

            return len(changed)

    async def mark_agents_disconnected(self, session_id: str) -> int:
        """把该 session 下所有 Agent 标记为 disconnected。

        Returns:
            受影响的行数
        """
        from broca.session.models import Agent

        async with self.db.get_session() as session:
            agents = (
                await session.exec(
                    select(Agent).where(Agent.session_id == session_id)
                )
            ).all()

            changed = [a for a in agents if a.agent_status != "disconnected"]
            for agent in changed:
                agent.agent_status = "disconnected"

            if changed:
                session.add_all(changed)
                await session.commit()

            return len(changed)
