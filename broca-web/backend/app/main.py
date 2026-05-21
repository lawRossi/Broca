import os
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger

from app.api import api_router
from app.core.socketio_runtime import SocketIOServerConfig, SocketIOServerRuntime
from app.services.auth_service import AuthService

# 初始化日志（stderr + 文件），必须在任何 import 之后、app 创建之前
from broca.logging_config import init_logging

init_logging()

WHITE_LIST = {
    "/api/auth/login",
    "/api/auth/register",
    "/api/health",
    "/api/user/login",
}
security = HTTPBearer(auto_error=False)


def verify_token(req: Request, cred: HTTPAuthorizationCredentials = Depends(security)) -> None:
    if req.url.path in WHITE_LIST:
        return
    if not cred:
        raise HTTPException(401, "Unauthorized")
    try:
        payload = AuthService.decode_access_token(cred.credentials)
        req.state.user_id = payload.get("sub")
        req.state.username = payload.get("username")
    except Exception as e:
        raise HTTPException(401, "Unauthorized") from e


app = FastAPI(dependencies=[Depends(verify_token)])

# CORS 中间件 — 允许前端跨域访问（vite preview / nginx 均需）
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def setup() -> None:
    """应用启动时初始化"""
    logger.info("Starting up")

    # === 1. 启动 SocketIO Server ===
    enabled = os.getenv("BROCA_SOCKETIO_ENABLED", "true").lower() == "true"
    host = os.getenv("BROCA_SOCKETIO_HOST", "0.0.0.0")
    port = int(os.getenv("BROCA_SOCKETIO_PORT", "6868"))
    cors = os.getenv("BROCA_SOCKETIO_CORS", "*")

    app.state.socketio_runtime = SocketIOServerRuntime(
        SocketIOServerConfig(enabled=enabled, host=host, port=port, cors_allowed_origins=cors)
    )
    await app.state.socketio_runtime.start()

    # === 2. 初始化 Runner Manager 并恢复活跃 Session ===
    try:
        from broca.session_runner import RunnerManager

        runner_manager = RunnerManager()
        app.state.runner_manager = runner_manager

        # 启动心跳监控
        await runner_manager.start_heartbeat_monitor()

        # 恢复数据库中所有 active 状态的 Session
        checked = await runner_manager.restore_active_sessions()
        logger.info(f"Startup session check complete: {checked} records verified")

    except Exception as e:
        logger.error(f"Failed to initialize RunnerManager: {e}")


@app.on_event("shutdown")
async def shutdown() -> None:
    """应用关闭时清理"""
    logger.info("Shutting down")

    # === 1. 关闭 SocketIO Server ===
    runtime = getattr(app.state, "socketio_runtime", None)
    if runtime:
        await runtime.stop()

    # === 2. 关闭所有 Runner 进程 ===
    try:
        runner_manager = getattr(app.state, "runner_manager", None)
        if runner_manager:
            stopped = await runner_manager.shutdown_all()
            logger.info(f"Stopped {stopped} session runners")
    except Exception as e:
        logger.error(f"Failed to shutdown runners: {e}")


@app.get("/api/health")
async def health_check():
    """健康检查"""
    runner_manager = getattr(app.state, "runner_manager", None)
    runner_stats = runner_manager.get_stats() if runner_manager else {"total_runners": 0}

    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "runners": runner_stats,
    }


app.include_router(api_router, prefix="/api")
