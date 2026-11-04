"""心跳健康策略与监控循环。

历史问题（本模块要根治的）：
1. 阈值散落三处：``configs.json`` 的 execution 组、manager 的默认参数、
   已删除的死代码 ``session_runner/heartbeat.py`` 里的 30/60 另一套值。
2. 判定逻辑与 manager 的其它 40 个方法搅在一起，无法单测。
3. 进程已退出却只把状态改成 ERROR、条目永不出清 → ``/runner/status``
   永久返回 error，前端永久显示「进程异常」。

拆分后 ``HeartbeatMonitor`` 只依赖 4 个协作者（registry / repo / reaper /
events），``check_once()`` 是可直接断言的纯入口，不需要启动后台循环。
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from broca.session_runner.models import RunnerProcessInfo, RunnerStatus
from broca.session_runner.process.reaper import RunnerReaper
from broca.session_runner.process.registry import RunnerHandle, RunnerRegistry
from broca.session_runner.repository import RunnerRepository
from broca.logging_config import get_logger

logger = get_logger(__name__)

# 心跳宽限倍数：连续 N 次巡检都超时才升级为 ERROR，
# 避免 runner 事件循环短暂卡顿（长工具调用、快照加锁等）被误判为异常
HEARTBEAT_GRACE_MULTIPLIER = 3.0
# 心跳落库的最小间隔（秒）：避免每次巡检都写库，又保证 DB 不会长期陈旧
HEARTBEAT_PERSIST_INTERVAL = 60.0


@dataclass(frozen=True)
class HealthPolicy:
    """心跳健康策略（不可变，便于在测试里直接构造）。"""

    interval: float = 5.0  # runner 上报间隔
    timeout: float = 45.0  # 判定超时
    check_interval: float = 15.0  # 巡检间隔
    grace_multiplier: float = HEARTBEAT_GRACE_MULTIPLIER
    persist_interval: float = HEARTBEAT_PERSIST_INTERVAL

    @classmethod
    def from_config(cls) -> "HealthPolicy":
        """从 ``configs.json`` 的 execution 组读取阈值；读不到则用默认值。"""
        interval, timeout, check_interval = 5.0, 45.0, 15.0
        try:
            from broca.configs import get_configs

            cfg = get_configs().execution
            interval = float(getattr(cfg, "runner_heartbeat_interval", interval))
            timeout = float(getattr(cfg, "runner_heartbeat_timeout", timeout))
            check_interval = float(
                getattr(cfg, "runner_heartbeat_check_interval", check_interval)
            )
        except Exception as exc:  # noqa: BLE001 - 配置缺失不应阻断启动
            logger.debug("HealthPolicy.from_config fallback to defaults: %s", exc)
        return cls(interval=interval, timeout=timeout, check_interval=check_interval)

    @property
    def grace(self) -> float:
        """宽限期（秒）：超时后仍允许的抖动窗口。"""
        return self.timeout * self.grace_multiplier


def release_handle(handle: RunnerHandle) -> None:
    """释放一个 handle 的运行时资源（取消监听任务 + 关闭 IPC）。

    约定：**只有 ``IPCServer.close()`` 负责删除 socket 文件**，这里不手动 unlink
    —— 否则会与 ``close()`` 内部的 unlink 竞争，出现 ``FileNotFoundError``。
    """
    task = handle.poll_task
    handle.poll_task = None
    if task is not None and not task.done():
        task.cancel()
    handle.poll_thread = None

    ipc = handle.ipc
    handle.ipc = None
    if ipc is not None:
        try:
            ipc.close()
        except Exception:  # noqa: BLE001 - 关闭失败不应阻断清理
            pass


class HeartbeatMonitor:
    """心跳巡检 + 状态落库 + 死亡/停止收敛。"""

    def __init__(
        self,
        policy: HealthPolicy,
        registry: RunnerRegistry,
        repo: RunnerRepository,
        reaper: RunnerReaper,
        events: Any,
    ) -> None:
        self._policy = policy
        self._registry = registry
        self._repo = repo
        self._reaper = reaper
        self._events = events
        self._task: Optional[asyncio.Task] = None

    @property
    def policy(self) -> HealthPolicy:
        return self._policy

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(
        self,
        *,
        interval: Optional[float] = None,
        timeout: Optional[float] = None,
    ) -> None:
        """启动后台巡检循环（幂等：已在跑时只告警不重启）。"""
        if self.running:
            logger.warning(
                "Heartbeat monitor already running in pid=%d, skip", os.getpid()
            )
            return

        check_interval = (
            self._policy.check_interval if interval is None else float(interval)
        )
        effective_timeout = self._policy.timeout if timeout is None else float(timeout)

        if effective_timeout < self._policy.interval * 3:
            logger.warning(
                "Heartbeat timeout (%ss) is too close to the report interval (%ss); "
                "false positives are likely. Recommended: timeout >= 3 x interval.",
                effective_timeout,
                self._policy.interval,
            )

        self._task = asyncio.create_task(
            self._loop(check_interval, effective_timeout),
            name="heartbeat-monitor",
        )
        logger.info(
            "Heartbeat monitor started (pid=%d, interval=%ss, timeout=%ss, grace=%ss)",
            os.getpid(),
            check_interval,
            effective_timeout,
            effective_timeout * self._policy.grace_multiplier,
        )

    async def stop(self) -> None:
        """停止后台巡检循环（幂等）。"""
        task = self._task
        self._task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        logger.info("Heartbeat monitor stopped (pid=%d)", os.getpid())

    async def _loop(self, interval: float, timeout: float) -> None:
        while True:
            try:
                await asyncio.sleep(interval)
                await self.check_once(timeout)
                await self._persist_states()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 - 巡检失败不能拖垮循环
                logger.error("Heartbeat monitor error: %s", exc)

    # ------------------------------------------------------------------
    # 巡检（可直接单测的入口）
    # ------------------------------------------------------------------

    async def check_once(self, timeout: Optional[float] = None) -> None:
        """巡检所有 Runner 的存活状态。

        判定顺序（重要）：
        1. 进程已退出（``process.poll()`` 非 None）→ 立即收敛为 DEAD 并清理，
            不再让条目永久停留在 error 状态。
        2. 进程存活但心跳超时 → 先打「心跳陈旧」标记并宽限 ``grace_multiplier``
            倍阈值，仍无心跳才升级为 ERROR；升级后继续巡检，心跳恢复即回到 ALIVE。

        Args:
            timeout: 心跳超时阈值（秒），None 时用 policy 的 timeout
        """
        effective_timeout = self._policy.timeout if timeout is None else float(timeout)
        grace = effective_timeout * self._policy.grace_multiplier
        now = datetime.now(timezone.utc)
        dead_sessions: list[str] = []
        stopped_sessions: list[str] = []

        for handle in list(self._registry.all()):
            runner_info = handle.info
            session_id = runner_info.session_id

            # STARTING 阶段由 start_session 自己负责（它会等 READY 并自行清理），
            # 这里只在明显卡死后兜底，避免与启动流程竞态重复清理
            if runner_info.status == RunnerStatus.STARTING:
                started_at = runner_info.started_at
                if started_at is not None:
                    if (now - started_at).total_seconds() < grace:
                        continue

            # ---- 1) 进程维度：进程没了就是死了，与心跳无关 ----
            process = runner_info.process
            if process is not None:
                returncode = process.poll()
                if returncode is not None:
                    # 区分「用户主动停止」与「意外崩溃」：主动停止只置了
                    # SHUTTING_DOWN / stop_requested，若这里一律判死并触发
                    # session_crashed，前端会把正常停止误报为崩溃。
                    if (
                        runner_info.stop_requested
                        or runner_info.status == RunnerStatus.SHUTTING_DOWN
                    ):
                        logger.info(
                            "Runner %s (pid=%s) exited after stop request (code=%s)",
                            session_id,
                            runner_info.pid,
                            returncode,
                        )
                        stopped_sessions.append(session_id)
                    else:
                        logger.error(
                            "Runner %s (pid=%s) has exited with code %s",
                            session_id,
                            runner_info.pid,
                            returncode,
                        )
                        runner_info.status = RunnerStatus.DEAD
                        runner_info.error_message = (
                            f"Process exited with code {returncode}"
                        )
                        dead_sessions.append(session_id)
                    continue

            # ---- 2) 心跳维度：只对「本应活着」的状态做判定 ----
            if runner_info.status not in (RunnerStatus.ALIVE, RunnerStatus.ERROR):
                continue
            if runner_info.last_heartbeat is None:
                continue

            elapsed = (now - runner_info.last_heartbeat).total_seconds()
            if elapsed <= effective_timeout:
                runner_info.heartbeat_stale = False
                runner_info.missed_heartbeats = 0
                continue

            runner_info.missed_heartbeats += 1
            runner_info.heartbeat_stale = True

            if elapsed <= grace:
                # 宽限期内：只记录，不改状态，避免事件循环短暂卡顿被误判
                logger.warning(
                    "Runner %s heartbeat delayed (elapsed=%.1fs, timeout=%ss, "
                    "missed=%d, grace=%ss)",
                    session_id,
                    elapsed,
                    effective_timeout,
                    runner_info.missed_heartbeats,
                    grace,
                )
                continue

            if runner_info.status != RunnerStatus.ERROR:
                logger.error(
                    "Runner %s heartbeat lost (elapsed=%.1fs > grace=%ss, pid=%s alive)",
                    session_id,
                    elapsed,
                    grace,
                    runner_info.pid,
                )
                runner_info.status = RunnerStatus.ERROR
                runner_info.error_message = f"Heartbeat lost ({elapsed:.0f}s)"
                # 进程还活着，条目保留继续巡检，心跳恢复会自动回到 ALIVE；
                # 此时不把 agent 标记为 disconnected，避免前端反复闪断。
                await self._events.emit("session_crashed", runner_info)

        # ---- 3) 收敛真正死亡/已停止的 runner ----
        for session_id in stopped_sessions:
            await self.converge_stopped(session_id)
        for session_id in dead_sessions:
            await self.converge_dead(session_id)

    # ------------------------------------------------------------------
    # 状态落库
    # ------------------------------------------------------------------

    async def _persist_states(self) -> None:
        """把内存中的 Runner 状态与心跳时间同步到 DB（只写有变化的行）。

        历史问题：写库只在 ``start_session`` 时发生一次，DB 里的
        status/last_heartbeat 永远停留在启动瞬间，``restore_active_sessions``
        读到脏数据。

        实现要点（P1-5「单事务批量」）：先按 ``persist_interval`` 过滤出**有变化**
        的行，再把 N 行合并成**一次** ``upsert_many``（单事务、一次 commit），
        而不是逐 runner 串行 SELECT+UPDATE（2N 次往返）。
        """
        now = datetime.now(timezone.utc)
        pending: list[RunnerProcessInfo] = []

        for handle in list(self._registry.all()):
            info = handle.info
            prev = handle.db_state_cache
            if prev is not None:
                prev_status, prev_hb = prev
                hb_fresh = (
                    prev_hb is not None
                    and (now - prev_hb).total_seconds() < self._policy.persist_interval
                )
                if prev_status == info.status.value and hb_fresh:
                    continue
            pending.append(info)

        if not pending:
            return

        await self._repo.upsert_many(pending)
        for info in pending:
            handle = self._registry.get(info.session_id)
            if handle is not None:
                handle.db_state_cache = (info.status.value, now)

    # ------------------------------------------------------------------
    # 收敛
    # ------------------------------------------------------------------

    async def converge_stopped(self, session_id: str) -> None:
        """把「用户主动停止」的 Runner 收敛掉：发 session_stopped，不发 session_crashed。

        与 :meth:`converge_dead` 的区别：
        - 事件名不同（session_stopped vs session_crashed）
        - 不把该 session 下的 Agent 标记为 disconnected（主动停止不产生断连告警）
        - 停止完成后删除 DB 记录（停止 = 清理；崩溃则保留 dead 记录便于排查）
        """
        handle = self._registry.get(session_id)
        if handle is None:
            return
        runner_info = handle.info

        runner_info.status = RunnerStatus.DEAD
        runner_info.error_message = "Stopped by user"
        runner_info.heartbeat_stale = False
        runner_info.missed_heartbeats = 0

        await self._persist_one(handle, "stopped")
        await self._events.emit("session_stopped", runner_info)

        handle.agent_status_cache = None
        release_handle(handle)
        self._registry.pop(session_id)
        await self._delete_record(session_id)
        logger.info("Runner for session %s converged to STOPPED", session_id)

    async def converge_dead(self, session_id: str) -> None:
        """把已死亡的 Runner 收敛掉：置 DEAD、写库、通知前端、清理内存与 IPC。

        历史问题：进程退出后只把状态改成 ERROR，既不移除内存条目也不写库，
        导致 ``/runner/status`` 永远返回 error（前端永久「进程异常」）。
        """
        handle = self._registry.get(session_id)
        if handle is None:
            return
        runner_info = handle.info

        runner_info.status = RunnerStatus.DEAD
        runner_info.heartbeat_stale = False
        runner_info.missed_heartbeats = 0
        reason = runner_info.error_message or "Process exited"

        await self._persist_one(handle, "dead")
        await self._events.emit("session_crashed", runner_info)
        await self.mark_agents_disconnected(session_id)

        # 内存条目必须移除，否则 /runner/status 会一直返回这条僵尸记录。
        # DB 记录保留为 dead，便于排查历史失败原因。
        handle.agent_status_cache = None
        release_handle(handle)
        self._registry.pop(session_id)
        logger.warning("Runner for session %s converged to DEAD (%s)", session_id, reason)

    async def mark_agents_disconnected(self, session_id: str) -> None:
        """Runner 进程死亡时，把该 Session 下所有 Agent 标记为 disconnected。"""
        try:
            count = await self._repo.mark_agents_disconnected(session_id)
            if count:
                logger.info(
                    "Marked %d agents as disconnected for session %s",
                    count,
                    session_id,
                )
            # 清除状态缓存，确保后续心跳恢复时能重新同步真实状态
            # （否则缓存与心跳 payload 相同会跳过写入，DB 永远停留在 disconnected）
            handle = self._registry.get(session_id)
            if handle is not None:
                handle.agent_status_cache = None
        except Exception as exc:  # noqa: BLE001 - 清理失败不应中断收敛
            logger.error(
                "Failed to mark agents disconnected for session %s: %s",
                session_id,
                exc,
            )

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    async def _persist_one(self, handle: RunnerHandle, label: str) -> None:
        """收敛前先落库，保证外部读 DB 能看到真实状态。"""
        try:
            await self._repo.upsert(handle.info)
            handle.db_state_cache = (handle.info.status.value, None)
        except Exception as exc:  # noqa: BLE001 - 落库失败不阻断收敛
            logger.warning(
                "Failed to persist %s runner for session %s: %s",
                label,
                handle.info.session_id,
                exc,
            )

    async def _delete_record(self, session_id: str) -> None:
        try:
            await self._repo.delete(session_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to remove runner record for session %s: %s", session_id, exc
            )
