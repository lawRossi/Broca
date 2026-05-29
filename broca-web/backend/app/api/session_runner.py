"""
Session Runner 管理 API

提供 Session 进程的生命周期管理和状态查询功能。
"""

from fastapi import APIRouter, HTTPException
from loguru import logger

from broca.session_runner import RunnerManager
from broca.session_runner.manager import RunnerManagerError
from app.schemas.schemas import ApiResponse

router = APIRouter()


@router.get("/runners", response_model=ApiResponse)
async def list_runners():
    """获取所有 Session Runner 进程列表及状态"""
    try:
        runner_manager = RunnerManager()
        stats = runner_manager.get_stats()
        return ApiResponse.success(stats, msg="Runners retrieved successfully")
    except Exception as e:
        logger.exception("Error listing runners")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.get("/runners/stats", response_model=ApiResponse)
async def get_runner_stats():
    """获取 Runner 资源统计信息"""
    try:
        runner_manager = RunnerManager()
        stats = runner_manager.get_stats()
        return ApiResponse.success(stats, msg="Runner stats retrieved successfully")
    except Exception as e:
        logger.exception("Error getting runner stats")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.get("/{session_id}/runner/status", response_model=ApiResponse)
async def get_runner_status(session_id: str):
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
async def restart_runner(session_id: str):
    """重启指定 Session 的 Runner 进程"""
    try:
        runner_manager = RunnerManager()
        runner_info = await runner_manager.restart_session(session_id)

        return ApiResponse.success(
            {
                "session_id": session_id,
                "pid": runner_info.pid,
                "status": runner_info.status.value,
                "message": "Runner restarted successfully",
            },
            msg="Runner restarted successfully",
        )
    except RunnerManagerError as e:
        logger.exception(f"Error restarting runner for {session_id}")
        raise HTTPException(500, str(e)) from e
    except Exception as e:
        logger.exception(f"Error restarting runner for {session_id}")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.post("/{session_id}/runner/stop", response_model=ApiResponse)
async def stop_runner(session_id: str):
    """停止指定 Session 的 Runner 进程"""
    try:
        runner_manager = RunnerManager()
        success = await runner_manager.stop_session(session_id)

        if success:
            return ApiResponse.success(
                {"session_id": session_id, "message": "Runner stopped successfully"},
                msg="Runner stopped successfully",
            )
        else:
            return ApiResponse.success(
                {"session_id": session_id, "message": "No active runner to stop"},
                msg="No runner found",
            )
    except Exception as e:
        logger.exception(f"Error stopping runner for {session_id}")
        raise HTTPException(500, f"Internal server error: {e!s}") from e
