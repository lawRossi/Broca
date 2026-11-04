"""Session Runner REST 响应快照工具。

Task 4.1 要求「API 层改造前后响应结构一致」，本脚本把这条要求落成**可执行定义**：
用固定的 `RunnerManager` 桩把 4 个端点的响应体序列化到 JSON，改造前后各跑一次，
`diff` 必须为空。

用法::

    # 改造前
    venv/bin/python broca-web/tests/snapshot_runner_api.py \
        --out broca-web/tests/fixtures/session_runner_responses.before.json

    # 改造后
    venv/bin/python broca-web/tests/snapshot_runner_api.py \
        --out broca-web/tests/fixtures/session_runner_responses.after.json

    diff broca-web/tests/fixtures/session_runner_responses.before.json \
         broca-web/tests/fixtures/session_runner_responses.after.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

SESSION_ID = "snapshot-session-0001"

RUNNER_STATUS = {
    "session_id": SESSION_ID,
    "pid": 4321,
    "status": "alive",
    "started_at": "2026-01-01T00:00:00+00:00",
    "ipc_address": "/tmp/broca_runner_snapshot.sock",
    "resource_usage": {"cpu_percent": 1.5, "memory_rss": 1024},
    "last_heartbeat": "2026-01-01T00:01:00+00:00",
    "restart_count": 0,
    "error_message": None,
    "heartbeat_stale": False,
    "missed_heartbeats": 0,
    "uptime_seconds": 60.0,
}

RUNNER_STATS = {
    "total_runners": 1,
    "max_concurrent": 10,
    "available_slots": 9,
    "by_status": {"alive": 1},
    "runners": [RUNNER_STATUS],
}


def _fake_manager() -> MagicMock:
    manager = MagicMock()
    manager.get_stats = MagicMock(return_value=RUNNER_STATS)
    manager.get_status = MagicMock(return_value=RUNNER_STATUS)
    # 旧名保留桩：让改造前（调用 get_session_status）与改造后（调用 get_status）
    # 拿到**完全相同**的返回值，diff 才有意义
    manager.get_session_status = MagicMock(return_value=RUNNER_STATUS)
    manager.stop_session = AsyncMock(return_value=True)
    manager.start_session = AsyncMock(return_value=None)
    manager.request_stop = AsyncMock(
        return_value={
            "session_id": SESSION_ID,
            "status": "stopping",
            "message": "Runner stopping",
        }
    )
    return manager


async def _collect() -> dict:
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.api import session_runner as api

    app = FastAPI()
    app.include_router(api.router, prefix="/api/session")

    manager = _fake_manager()
    results: dict = {}

    fake_session = MagicMock()
    fake_session.workspace = "/tmp/snapshot-ws"
    fake_sm = MagicMock()
    fake_sm.get_session = AsyncMock(return_value=fake_session)

    with (
        patch.object(api, "RunnerManager", return_value=manager),
        patch("broca.session.SessionManager", return_value=fake_sm),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for key, method, url in [
                ("status", "GET", f"/api/session/{SESSION_ID}/runner/status"),
                ("list", "GET", "/api/session/runners"),
                ("start", "POST", f"/api/session/{SESSION_ID}/runner/start"),
                ("stop", "POST", f"/api/session/{SESSION_ID}/runner/stop"),
                ("restart", "POST", f"/api/session/{SESSION_ID}/runner/restart"),
            ]:
                response = await client.request(method, url)
                try:
                    body = response.json()
                except Exception:  # noqa: BLE001 - 非 JSON 响应也要记录下来
                    body = {"_raw": response.text}
                results[key] = {"status_code": response.status_code, "body": body}
                # 后台任务在 TestClient 关闭前跑完，避免悬挂协程
                await asyncio.sleep(0)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="输出 JSON 文件路径")
    args = parser.parse_args()

    results = asyncio.run(_collect())

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(results, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
