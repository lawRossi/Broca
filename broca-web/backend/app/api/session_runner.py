"""Session Runner 管理 API

提供 Session 进程的生命周期管理和状态查询功能。
"""

import asyncio

from broca.session_runner import RunnerManager
from broca.session_runner.manager import RunnerManagerError
from fastapi import APIRouter, HTTPException
from loguru import logger

from app.schemas.schemas import ApiResponse

router = APIRouter()

# 后台任务必须持引用：裸 asyncio.create_task() 的返回值没有强引用，
# 任务可能在执行中被 GC 回收（P1-4 同类缺陷），且异常会静默丢失。
_background_tasks: set[asyncio.Task] = set()


def _spawn_background(coro) -> None:
    """启动一个后台任务并持引用，结束后自动清理。"""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


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
        status = runner_manager.get_status(session_id)

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

        _spawn_background(_start_bg())

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

        # 只依赖 ABC 的 request_stop：内部完成标记 + 发 CMD_SHUTDOWN，
        # 不再直接访问管理器的私有状态字典（抽象泄漏）
        result = await runner_manager.request_stop(session_id)
        if result.get("status") == "stopped":
            return ApiResponse.success(result, msg="No runner to stop")

        # 后台完成：等进程退出 + 清理资源
        async def _stop_bg():
            try:
                await runner_manager.stop_session(session_id, timeout=10.0)
            except Exception as e:
                logger.exception(f"Error stopping runner for {session_id} in background: {e}")

        _spawn_background(_stop_bg())

        return ApiResponse.success(result, msg="Runner is stopping")
    except Exception as e:
        logger.exception(f"Error stopping runner for {session_id}")
        raise HTTPException(500, f"Internal server error: {e!s}") from e
