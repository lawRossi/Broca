"""Session Runner 管理 API

提供 Session 进程的生命周期管理和状态查询功能。
"""

import asyncio

from broca.session_runner import RunnerManager
from broca.session_runner.manager import RunnerManagerError
from broca.session_runner.models import RunnerStatus
from fastapi import APIRouter, HTTPException
from loguru import logger

from app.schemas.schemas import ApiResponse

router = APIRouter()


@router.get("/runners", response_model=ApiResponse)
async def list_runners() -> ApiResponse:
    """获取所有 Session Runner 进程列表及状态"""
    try:
        runner_manager = RunnerManager()
        stats = runner_manager.get_stats()
        return ApiResponse.success(stats, msg="Runners retrieved successfully")
    except Exception as e:
        logger.exception("Error listing runners")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.get("/runners/stats", response_model=ApiResponse)
async def get_runner_stats() -> ApiResponse:
    """获取 Runner 资源统计信息"""
    try:
        runner_manager = RunnerManager()
        stats = runner_manager.get_stats()
        return ApiResponse.success(stats, msg="Runner stats retrieved successfully")
    except Exception as e:
        logger.exception("Error getting runner stats")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.get("/{session_id}/runner/status", response_model=ApiResponse)
async def get_runner_status(session_id: str) -> ApiResponse:
    """获取指定 Session 的 Runner 进程状态"""
    try:
        runner_manager = RunnerManager()
        status = runner_manager.get_session_status(session_id)

        if not status:
            return ApiResponse.success(
                {"session_id": session_id, "status": "none", "message": "No runner process for this session"},
                msg="Runner not found",
            )

        return ApiResponse.success(status, msg="Runner status retrieved successfully")
    except Exception as e:
        logger.exception(f"Error getting runner status for {session_id}")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.post("/{session_id}/runner/restart", response_model=ApiResponse)
async def restart_runner(session_id: str) -> ApiResponse:
    """重启指定 Session 的 Runner 进程（异步：stop 后后台 start，立即返回）"""
    try:
        runner_manager = RunnerManager()

        # 1. 如果旧 runner 还在运行，先停止（快速，已优化）
        await runner_manager.stop_session(session_id)

        # 2. 获取 workspace 信息
        from broca.session import SessionManager
        sm = SessionManager()
        session = await sm.get_session(session_id)
        if not session:
            raise HTTPException(404, f"Session {session_id} not found")
        workspace = session.workspace

        # 3. 后台启动新 runner（不阻塞响应）
        async def _start_bg():
            try:
                await runner_manager.start_session(
                    session_id=session_id, workspace=workspace
                )
            except Exception as e:
                logger.exception(
                    f"Failed to start runner for {session_id} in background: {e}"
                )

        asyncio.create_task(_start_bg())

        return ApiResponse.success(
            {
                "session_id": session_id,
                "status": "starting",
                "message": "Runner starting",
            },
            msg="Runner is starting",
        )
    except HTTPException:
        raise
    except RunnerManagerError as e:
        logger.exception(f"Error restarting runner for {session_id}")
        raise HTTPException(500, str(e)) from e
    except Exception as e:
        logger.exception(f"Error restarting runner for {session_id}")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.post("/{session_id}/runner/stop", response_model=ApiResponse)
async def stop_runner(session_id: str) -> ApiResponse:
    """停止指定 Session 的 Runner 进程（非阻塞：发送 shutdown 后立即返回 stopping 状态）"""
    try:
        runner_manager = RunnerManager()
        runner_info = runner_manager._runners.get(session_id)

        if not runner_info:
            # 没有活跃 runner，直接清理 DB/IPC 残留
            await runner_manager.stop_session(session_id, timeout=2.0)
            return ApiResponse.success(
                {"session_id": session_id, "status": "stopped", "message": "No active runner"},
                msg="No runner to stop",
            )

        # 快速路径：标记 + 发 shutdown，立即返回
        runner_info.status = RunnerStatus.SHUTTING_DOWN
        ipc_server = runner_manager._ipc_servers.get(session_id)
        if ipc_server:
            from broca.session_runner.models import IPCMessageType, IPCStatusCode
            from broca.session_runner.ipc import create_ipc_message
            try:
                shutdown_msg = create_ipc_message(
                    IPCMessageType.CMD_SHUTDOWN,
                    session_id,
                    payload={"reason": "user_request"},
                )
                ipc_server.send_message(shutdown_msg)
            except Exception as e:
                logger.warning(f"Failed to send shutdown via IPC: {e}")

        # 后台完成：等进程退出 + 清理资源
        async def _stop_bg():
            try:
                await runner_manager.stop_session(session_id, timeout=10.0)
            except Exception as e:
                logger.exception(f"Error stopping runner for {session_id} in background: {e}")

        asyncio.create_task(_stop_bg())

        return ApiResponse.success(
            {"session_id": session_id, "status": "stopping", "message": "Runner stopping"},
            msg="Runner is stopping",
        )
    except Exception as e:
        logger.exception(f"Error stopping runner for {session_id}")
        raise HTTPException(500, f"Internal server error: {e!s}") from e
