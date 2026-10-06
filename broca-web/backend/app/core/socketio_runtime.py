"""Runtime helpers to start/stop Broca SocketIO server alongside FastAPI.

We intentionally reuse Broca/comm/socketio_server.py (SocketIOServer) and start it
as a background asyncio task during FastAPI startup.

Notes:
- SocketIOServer.start() internally runs an uvicorn.Server.serve() coroutine.
- When FastAPI (uvicorn) shuts down, we cancel the background task.

"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from broca.communication.socketio_server import SocketIOServer

logger = logging.getLogger(__name__)


@dataclass
class SocketIOServerConfig:
    enabled: bool = True
    host: str = "0.0.0.0"  # noqa: S104
    port: int = 6868
    cors_allowed_origins: str = "*"


class SocketIOServerRuntime:
    def __init__(self, config: SocketIOServerConfig):
        self.config = config
        self._task: asyncio.Task | None = None
        self._server: SocketIOServer | None = None

    async def start(self) -> None:
        if not self.config.enabled:
            logger.info("SocketIOServer disabled by config")
            return

        if self._task and not self._task.done():
            logger.warning("SocketIOServer already started")
            return

        # 从 Broca 全局配置计算 pending message 缓存 TTL：
        # 取 agent 侧两个超时的较大值 + 60s 重连缓冲，保证服务端缓存
        # 在 agent 超时放弃之前始终有效，超时后额外保留一小段重连窗口
        from broca.configs import get_configs

        exec_cfg = get_configs().execution
        ttl = max(
            getattr(exec_cfg, "permission_request_timeout", 90),
            getattr(exec_cfg, "agent_query_timeout", 300),
        ) + 60

        self._server = SocketIOServer(
            host=self.config.host,
            port=self.config.port,
            cors_allowed_origins=self.config.cors_allowed_origins,
            pending_message_ttl=ttl,
        )

        async def _runner() -> None:
            try:
                assert self._server is not None
                await self._server.start()
            except asyncio.CancelledError:
                logger.info("SocketIOServer task cancelled")
                raise
            except Exception:
                logger.exception("SocketIOServer crashed")

        self._task = asyncio.create_task(_runner(), name="broca-socketio-server")
        logger.info(
            "SocketIOServer started in background: %s:%s",
            self.config.host,
            self.config.port,
        )

    async def stop(self) -> None:
        if not self._task:
            return

        if not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self._task = None
        self._server = None
        logger.info("SocketIOServer stopped")

    def is_client_connected(self, client_id: str) -> bool:
        return self._server is not None and self._server.is_client_connected(client_id)
