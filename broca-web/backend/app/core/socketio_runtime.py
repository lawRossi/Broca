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
    host: str = "0.0.0.0"
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

        self._server = SocketIOServer(
            host=self.config.host,
            port=self.config.port,
            cors_allowed_origins=self.config.cors_allowed_origins,
        )

        async def _runner():
            try:
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
