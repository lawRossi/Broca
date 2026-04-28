"""
Session API

提供 Session 的 CRUD 操作。创建 Session 时会通过 RunnerManager 启动独立子进程，
不再在 Web 进程内直接运行 Agent。
"""

import asyncio
import os
import tempfile

from broca.agent_manager import AgentFactory
from broca.session.service import (
    get_agent_config_service,
    get_agent_service,
    get_message_service,
    get_session_service,
)
from broca.session_runner import RunnerManager
from broca.session_runner.manager import RunnerManagerError
from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from app.schemas.schemas import ApiResponse, CreateSessionRequest, UpdateSessionRequest

router = APIRouter()


@router.post("/sessions", response_model=ApiResponse)
async def create_session(request: CreateSessionRequest) -> ApiResponse:
    """创建新会话，在独立进程中初始化 Agent"""
    # 输入验证
    if request.workspace is not None:
        if not os.path.isabs(request.workspace):
            raise HTTPException(400, "workspace must be an absolute path")
        if not os.path.exists(request.workspace):
            raise HTTPException(400, "workspace directory does not exist")

    workspace = None
    try:
        workspace = request.workspace
        if workspace is None:
            workspace = tempfile.mkdtemp(prefix="broca_session_")
            logger.info(f"Created temporary workspace: {workspace}")

        # === 阶段1: 在数据库中创建 Session 和 Agent 记录 ===
        factory = AgentFactory()
        agents = await factory.init_session_agents(
            workspace=workspace,
            provider=request.provider,
            model=request.model,
        )

        if not agents:
            raise HTTPException(500, "No agents were initialized")

        # 获取 session_id
        session_ids = set()
        for agent in agents:
            if not hasattr(agent, "session_manager") or not hasattr(agent.session_manager, "session_id"):
                raise HTTPException(500, f"Agent {agent} does not have a valid session_manager.session_id")
            session_ids.add(agent.session_manager.session_id)

        if len(session_ids) != 1:
            raise HTTPException(500, f"Agents have inconsistent session_ids: {session_ids}")

        session_id = session_ids.pop()

        # === 阶段2: 通过 RunnerManager 启动独立子进程 ===
        runner_manager = RunnerManager()
        try:
            await runner_manager.start_session(
                session_id=session_id,
                workspace=workspace,
                provider=request.provider,
                model=request.model,
            )
        except RunnerManagerError as e:
            logger.error(f"Failed to start runner for session {session_id}: {e}")
            # 清理数据库记录
            session_service = get_session_service()
            await session_service.delete(session_id)
            raise HTTPException(500, f"Failed to start session runner: {e!s}") from e

        # === 阶段3: 更新 Session 信息 ===
        session_service = get_session_service()
        update_data = {}
        if request.description:
            update_data["description"] = request.description
        if workspace:
            update_data["workspace"] = workspace
        if update_data:
            await session_service.update(session_id, **update_data)

        logger.info(
            f"Session created with runner: {session_id}, workspace: {workspace}, "
            f"provider: {request.provider}, model: {request.model}"
        )

        return ApiResponse.success(
            {
                "session_id": session_id,
                "workspace": workspace,
                "description": request.description,
                "provider": request.provider,
                "model": request.model,
            },
            msg="Session created successfully",
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error(f"Error creating session: {e}")
        raise HTTPException(500, f"Failed to create session: {e!s}") from e


@router.get("/sessions", response_model=ApiResponse)
async def get_sessions(
    skip: int = 0, limit: int = 20, status: str | None = None, keyword: str | None = None
) -> ApiResponse:
    """获取会话列表，支持分页、状态筛选和关键词搜索"""
    try:
        session_service = get_session_service()

        # 构建过滤条件
        filters = {}
        if status:
            filters["status"] = status

        # 获取分页数据
        sessions = await session_service.get_batch(filters=filters if filters else None, order_by="created_at desc")
        total = len(sessions)
        sessions = sessions[skip : skip + limit]

        # 关键词过滤（在内存中过滤）
        if keyword and sessions:
            keyword_lower = keyword.lower()
            sessions = [
                s
                for s in sessions
                if (s.description and keyword_lower in s.description.lower()) or keyword_lower in s.session_id.lower()
            ]
            total = len(sessions)

        # 附加上 Runner 状态
        runner_manager = RunnerManager()
        session_list = []
        for session in sessions:
            session_dict = session.model_dump()
            runner_status = runner_manager.get_session_status(session.session_id)
            session_dict["runner_status"] = runner_status["status"] if runner_status else "none"
            session_list.append(session_dict)

        return ApiResponse.success({"sessions": session_list, "total": total, "skip": skip, "limit": limit})
    except Exception as e:
        logger.error(f"Error getting sessions: {e}")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.get("/{session_id}/agents", response_model=ApiResponse)
async def get_session_agents(session_id: str, req: Request) -> ApiResponse:
    """获取会话的Agent列表（从数据库读取）"""
    try:
        # 获取会话的Agent
        agent_service = get_agent_service()
        agents = await agent_service.get_agents_by_session(session_id)
        if not agents:
            raise HTTPException(status_code=404, detail="Session not found")

        # 获取 Runner 状态
        runner_manager = RunnerManager()
        runner_status = runner_manager.get_session_status(session_id)

        response_agents: list[dict] = []
        for db_agent in agents:
            response_agent = db_agent.model_dump()
            # 从 Runner 状态中获取 agent 的运行状态
            if runner_status:
                response_agent["status"] = runner_status["status"]
            else:
                response_agent["status"] = "disconnected"
            response_agents.append(response_agent)

        return ApiResponse.success(response_agents)
    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error(f"Error getting session agents: {e}")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.get("/{session_id}/messages", response_model=ApiResponse)
async def get_session_messages(session_id: str, skip: int = 0, limit: int = 50) -> ApiResponse:
    """获取会话的消息历史（按时间正序），支持分页"""
    try:
        session_service = get_session_service()
        session = await session_service.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        message_service = get_message_service()
        total = await message_service.count({"session_id": session_id})
        messages = await message_service.get_messages_by_session(
            session_id, order_by="sequence_number desc", skip=skip, limit=limit
        )
        messages.reverse()

        return ApiResponse.success({"messages": messages, "total": total, "skip": skip, "limit": limit})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session messages: {e}")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.delete("/sessions", response_model=ApiResponse)
async def delete_sessions(request: dict) -> ApiResponse:
    """批量删除会话"""
    try:
        session_ids = request.get("session_ids", [])
        if not session_ids:
            raise HTTPException(status_code=400, detail="No session IDs provided")

        if not isinstance(session_ids, list):
            raise HTTPException(status_code=400, detail="session_ids must be a list")

        runner_manager = RunnerManager()
        session_service = get_session_service()

        # 先停止所有 Runner 进程
        for session_id in session_ids:
            await runner_manager.stop_session(session_id)

        # 再从数据库删除
        deleted_count = await session_service.delete_batch(session_ids)

        logger.info(f"Batch delete sessions: {session_ids}, deleted: {deleted_count}")
        return ApiResponse.success(
            {"deleted_count": deleted_count}, msg=f"Successfully deleted {deleted_count} sessions"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error batch deleting sessions: {e}")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.put("/{session_id}", response_model=ApiResponse)
async def update_session(session_id: str, request: UpdateSessionRequest) -> ApiResponse:
    """更新会话信息（如描述）"""
    try:
        session_service = get_session_service()
        session = await session_service.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # 构建更新数据
        update_data = {}
        if request.description is not None:
            update_data["description"] = request.description

        if update_data:
            await session_service.update(session_id, **update_data)
            logger.info(f"Session updated: {session_id}, updates: {update_data}")

        return ApiResponse.success({"session_id": session_id, **update_data}, msg="Session updated successfully")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating session: {e}")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.delete("/{session_id}", response_model=ApiResponse)
async def delete_session(session_id: str) -> ApiResponse:
    """删除单个会话（先停止 Runner，再删除数据库记录）"""
    try:
        session_service = get_session_service()
        session = await session_service.get(session_id)

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # 先停止 Runner 进程
        runner_manager = RunnerManager()
        await runner_manager.stop_session(session_id)

        # 再从数据库删除
        success = await session_service.delete(session_id)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete session")

        logger.info(f"Session deleted: {session_id}")
        return ApiResponse.success(msg="Session deleted successfully")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting session: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.get("/{session_id}/agents/{agent_id}/config", response_model=ApiResponse)
async def get_agent_config(session_id: str, agent_id: str) -> ApiResponse:
    """获取指定Agent的配置信息"""
    try:
        # 验证会话是否存在
        session_service = get_session_service()
        session = await session_service.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # 获取Agent信息
        agent_service = get_agent_service()
        agent = await agent_service.get(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        # 验证Agent是否属于该会话
        if agent.session_id != session_id:
            raise HTTPException(status_code=400, detail="Agent does not belong to this session")

        # 获取Agent配置
        agent_config_service = get_agent_config_service()
        agent_config = await agent_config_service.get(agent.config_id)
        if not agent_config:
            raise HTTPException(status_code=404, detail="Agent config not found")

        # 解析配置内容
        import json

        try:
            config_content = json.loads(agent_config.config_content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse agent config JSON: {e}")
            config_content = {"error": "Failed to parse config content", "raw_content": agent_config.config_content}

        # 返回完整的配置信息
        config_data = {
            "agent_id": agent.agent_id,
            "agent_name": agent.name,
            "agent_role": agent.role,
            "config_id": agent_config.config_id,
            "config_name": agent_config.name,
            "config_content": config_content,
            "created_at": agent_config.created_at.isoformat() if agent_config.created_at else None,
            "raw_config_content": agent_config.config_content,
        }

        return ApiResponse.success(config_data, msg="Agent config retrieved successfully")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting agent config: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.get("/{session_id}/stats", response_model=ApiResponse)
async def get_session_stats(session_id: str) -> ApiResponse:
    """获取会话的统计信息"""
    try:
        session_service = get_session_service()
        session = await session_service.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        message_service = get_message_service()
        stats = await message_service.get_message_stats_by_session(session_id)

        # 附加工 Runner 信息
        runner_manager = RunnerManager()
        runner_status = runner_manager.get_session_status(session_id)
        if runner_status:
            stats["runner"] = runner_status

        return ApiResponse.success(stats, msg="Session stats retrieved successfully")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session stats: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(500, f"Internal server error: {e!s}") from e
