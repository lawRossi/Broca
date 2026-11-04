"""HeartbeatMonitor / HealthPolicy 测试（Phase 3 Task 3.1）

拆分前这些用例散在 `test_runner_heartbeat.py` 里、必须经过 manager 单例，
现在 `check_once()` 是可直接断言的纯入口。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from broca.session_runner.models import RunnerProcessInfo, RunnerStatus
from broca.session_runner.monitor import HealthPolicy, HeartbeatMonitor
from broca.session_runner.process.registry import RunnerHandle, RunnerRegistry

SESSION_ID = "session-monitor"


def _make_info(
    session_id: str = SESSION_ID,
    status: RunnerStatus = RunnerStatus.ALIVE,
    heartbeat_age: float | None = 1.0,
    poll_returncode: int | None = None,
    stop_requested: bool = False,
) -> RunnerProcessInfo:
    process = MagicMock()
    process.poll = MagicMock(return_value=poll_returncode)
    now = datetime.now(timezone.utc)
    info = RunnerProcessInfo(
        session_id=session_id,
        process=process,
        pid=4321,
        status=status,
        started_at=now - timedelta(seconds=600),
        last_heartbeat=(
            None if heartbeat_age is None else now - timedelta(seconds=heartbeat_age)
        ),
    )
    info.stop_requested = stop_requested
    return info


def _build(policy: HealthPolicy | None = None, repo=None, events=None):
    registry = RunnerRegistry()
    repo = repo or MagicMock(
        upsert=AsyncMock(),
        upsert_many=AsyncMock(),
        delete=AsyncMock(),
        mark_agents_disconnected=AsyncMock(return_value=0),
    )
    events = events or MagicMock(emit=AsyncMock(), emit_soon=MagicMock())
    monitor = HeartbeatMonitor(
        policy=policy or HealthPolicy(interval=5.0, timeout=45.0, check_interval=15.0),
        registry=registry,
        repo=repo,
        reaper=MagicMock(),
        events=events,
    )
    return monitor, registry, repo, events


# ---------------------------------------------------------------------------
# HealthPolicy
# ---------------------------------------------------------------------------


def test_policy_from_config_matches_configs_json():
    """三个阈值必须与 configs/configs.json 的 execution 组一致。"""
    import json
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    raw = json.loads((root / "configs" / "configs.json").read_text(encoding="utf-8"))
    execution = raw["execution"]

    policy = HealthPolicy.from_config()

    assert policy.interval == float(execution["runner_heartbeat_interval"])
    assert policy.timeout == float(execution["runner_heartbeat_timeout"])
    assert policy.check_interval == float(execution["runner_heartbeat_check_interval"])


def test_grace_is_multiplier_times_timeout():
    policy = HealthPolicy(interval=5.0, timeout=45.0, check_interval=15.0)
    assert policy.grace == 45.0 * policy.grace_multiplier


# ---------------------------------------------------------------------------
# 巡检判定
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grace_period_does_not_flip_status():
    """心跳超时但仍在宽限期内（进程存活）→ 只打标记，不改状态。"""
    monitor, registry, repo, events = _build()
    info = _make_info(heartbeat_age=50.0)  # > timeout(45) 但 < grace(135)
    registry.add(RunnerHandle(info=info))

    await monitor.check_once(45.0)

    assert info.status == RunnerStatus.ALIVE
    assert info.heartbeat_stale is True
    assert info.missed_heartbeats == 1
    events.emit.assert_not_awaited()
    repo.mark_agents_disconnected.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_exit_converges_to_dead():
    """进程已退出 → 收敛为 DEAD、写库、发 session_crashed、清理内存条目。"""
    monitor, registry, repo, events = _build()
    registry.add(RunnerHandle(info=_make_info(poll_returncode=-9, heartbeat_age=600.0)))

    await monitor.check_once(45.0)

    assert SESSION_ID not in registry
    repo.upsert.assert_awaited_once()
    assert repo.upsert.await_args.args[0].status == RunnerStatus.DEAD
    events.emit.assert_awaited_once()
    assert events.emit.await_args.args[0] == "session_crashed"
    repo.mark_agents_disconnected.assert_awaited_once_with(SESSION_ID)


@pytest.mark.asyncio
async def test_stop_requested_converges_to_stopped():
    """stop_requested 的已退出进程 → 走 stopped 而不是 crashed，且删除 DB 记录。"""
    monitor, registry, repo, events = _build()
    registry.add(
        RunnerHandle(
            info=_make_info(
                status=RunnerStatus.SHUTTING_DOWN,
                poll_returncode=0,
                stop_requested=True,
            )
        )
    )

    await monitor.check_once(45.0)

    assert SESSION_ID not in registry
    assert events.emit.await_args.args[0] == "session_stopped"
    repo.mark_agents_disconnected.assert_not_awaited()
    repo.delete.assert_awaited_once_with(SESSION_ID)


@pytest.mark.asyncio
async def test_check_once_is_callable_without_starting_loop():
    """check_once() 不依赖后台循环，可直接断言结果。"""
    monitor, registry, _, _ = _build()
    registry.add(RunnerHandle(info=_make_info(poll_returncode=1)))

    assert not monitor.running
    await monitor.check_once()
    assert not monitor.running
    assert SESSION_ID not in registry


# ---------------------------------------------------------------------------
# 状态落库
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_uses_single_commit_for_n_runners():
    """5 个 runner 的状态落库必须合并为一次 upsert_many（单事务一次 commit）。"""
    monitor, registry, repo, _ = _build()
    for idx in range(5):
        registry.add(RunnerHandle(info=_make_info(session_id=f"session-{idx}")))

    await monitor._persist_states()

    assert repo.upsert_many.await_count == 1
    assert len(repo.upsert_many.await_args.args[0]) == 5


@pytest.mark.asyncio
async def test_start_is_idempotent_and_stop_cancels():
    """重复 start 只告警不重启；stop 取消后台循环且幂等。"""
    monitor, _, _, _ = _build(policy=HealthPolicy(interval=1.0, timeout=3.0, check_interval=0.01))
    await monitor.start()
    first = monitor._task
    await monitor.start()  # 幂等
    assert monitor._task is first
    assert monitor.running

    await monitor.stop()
    assert not monitor.running
    await monitor.stop()  # 幂等
