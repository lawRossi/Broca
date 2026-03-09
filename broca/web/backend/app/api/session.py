import asyncio
import logging
import tempfile

from broca.agent_manager import AgentFactory
from broca.session.service import (
    get_agent_service,
    get_message_service,
    get_session_service,
    get_turn_service,
)
from fastapi import APIRouter, HTTPException

from app.schemas.schemas import ApiResponse, CreateSessionRequest

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/sessions", response_model=ApiResponse)
async def create_session(request: CreateSessionRequest) -> ApiResponse:
    """创建新会话，初始化 Agent 并设置 workspace

    - 如果指定了 workspace，使用用户指定的目录
    - 如果没有指定 workspace，创建临时目录作为 workspace
    """
    try:
        # 确定 workspace
        workspace = request.workspace
        if workspace is None:
            # 创建临时目录作为 workspace
            workspace = tempfile.mkdtemp(prefix="broca_session_")
            logger.info(f"Created temporary workspace: {workspace}")

        # 初始化 Agent
        factory = AgentFactory()
        agents = await factory.init_session_agents(workspace=workspace)
        session_id = None
        for agent in agents:
            await agent.connect()
            if session_id is None:
                session_id = agent.session_manager.session_id
            await agent.subscribe(session_id)
            task = asyncio.create_task(agent.run())
            task.add_done_callback(lambda _: agent.stop())

        # 更新会话描述（如果提供）
        if request.description:
            session_service = get_session_service()
            await session_service.update(session_id, description=request.description)

        logger.info(f"Session created: {session_id}, workspace: {workspace}")

        return ApiResponse.success(
            {
                "session_id": session_id,
                "workspace": workspace,
                "agent_id": agent.agent_id if hasattr(agent, "agent_id") else "main_agent",
                "description": request.description,
            },
            msg="Session created successfully",
        )

    except Exception as e:
        logger.error(f"Error creating session: {e}")
        import traceback

        logger.error(traceback.format_exc())
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

        # 获取总数
        total = await session_service.count(filters=filters if filters else None)

        # 获取分页数据
        sessions = await session_service.get_all(
            skip=skip, limit=limit, filters=filters if filters else None, order_by="created_at desc"
        )

        # 关键词过滤（在内存中过滤）
        if keyword and sessions:
            keyword_lower = keyword.lower()
            sessions = [
                s
                for s in sessions
                if (s.description and keyword_lower in s.description.lower()) or keyword_lower in s.session_id.lower()
            ]
            total = len(sessions)

        return ApiResponse.success({"sessions": sessions, "total": total, "skip": skip, "limit": limit})
    except Exception as e:
        logger.error(f"Error getting sessions: {e}")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.get("/{session_id}", response_model=ApiResponse)
async def get_session(session_id: str) -> ApiResponse:
    """获取会话详情"""
    try:
        session_service = get_session_service()
        session = await session_service.get(session_id)

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        return ApiResponse.success(session)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session: {e}")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.get("/{session_id}/agents", response_model=ApiResponse)
async def get_session_agents(session_id: str) -> ApiResponse:
    """获取会话的Agent列表"""
    try:
        # 验证会话是否存在
        session_service = get_session_service()
        session = await session_service.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # 获取会话的Agent
        agent_service = get_agent_service()
        agents = await agent_service.get_agents_by_session(session_id)

        return ApiResponse.success(agents)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session agents: {e}")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.get("/{session_id}/messages", response_model=ApiResponse)
async def get_session_messages(session_id: str, skip: int = 0, limit: int = 50) -> ApiResponse:
    """获取会话的消息历史（按时间正序），支持分页"""
    try:
        # 验证会话是否存在
        session_service = get_session_service()
        session = await session_service.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # 获取消息
        message_service = get_message_service()
        messages = await message_service.get_messages_by_session(session_id)

        # 按时间正序排列后分页
        messages_sorted = sorted(messages, key=lambda m: m.timestamp, reverse=True)
        total = len(messages_sorted)
        paginated_messages = messages_sorted[skip : skip + limit]
        paginated_messages.reverse()
        print(total)
        return ApiResponse.success({"messages": paginated_messages, "total": total, "skip": skip, "limit": limit})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session messages: {e}")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.get("/{session_id}/turns", response_model=ApiResponse)
async def get_session_turns(session_id: str, skip: int = 0, limit: int = 100) -> ApiResponse:
    """获取会话的轮次"""
    try:
        # 验证会话是否存在
        session_service = get_session_service()
        session = await session_service.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # 获取会话的轮次
        turn_service = get_turn_service()
        turns = await turn_service.get_turns_by_session(session_id)

        # 应用分页
        paginated_turns = turns[skip : skip + limit]

        return ApiResponse.success({"turns": paginated_turns, "total": len(turns), "skip": skip, "limit": limit})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session turns: {e}")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.get("/{session_id}/latest-agent", response_model=ApiResponse)
async def get_session_latest_agent(session_id: str) -> ApiResponse:
    """获取会话的最新Agent（用于Chat.vue自动获取agent_id）"""
    try:
        # 验证会话是否存在
        session_service = get_session_service()
        session = await session_service.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # 获取会话的Agent
        agent_service = get_agent_service()
        agents = await agent_service.get_agents_by_session(session_id)

        if not agents:
            # 如果没有Agent，返回默认值
            return ApiResponse.success({"agent_id": "main_agent", "has_agents": False})

        # 获取最新的Agent（假设按创建时间排序）
        latest_agent = agents[-1] if agents else None

        return ApiResponse.success(
            {
                "agent_id": latest_agent.agent_id if latest_agent else "main_agent",
                "agent_name": latest_agent.name if latest_agent else "Main Agent",
                "has_agents": True,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session latest agent: {e}")
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

        session_service = get_session_service()
        deleted_count = await session_service.delete_batch(session_ids)

        logger.info(f"Batch delete sessions: {session_ids}, deleted: {deleted_count}")
        return ApiResponse.success(
            {"deleted_count": deleted_count}, msg=f"Successfully deleted {deleted_count} sessions"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error batch deleting sessions: {e}")
        import traceback

        logger.error(traceback.format_exc())
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.delete("/{session_id}", response_model=ApiResponse)
async def delete_session(session_id: str) -> ApiResponse:
    """删除单个会话"""
    try:
        session_service = get_session_service()
        session = await session_service.get(session_id)

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # 删除会话（级联删除关联的turns、messages、agents等）
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
