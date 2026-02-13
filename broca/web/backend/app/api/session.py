import logging

from broca.session.service import (
    get_agent_service,
    get_message_service,
    get_session_service,
    get_turn_service,
)
from fastapi import APIRouter, HTTPException

from app.schemas.schemas import ApiResponse

logger = logging.getLogger(__name__)
router = APIRouter()


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
async def get_session_messages(session_id: str, skip: int = 0, limit: int = 100) -> ApiResponse:
    """获取会话的消息历史"""
    try:
        # 验证会话是否存在
        session_service = get_session_service()
        session = await session_service.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # 获取会话的消息
        message_service = get_message_service()
        messages = await message_service.get_messages_by_session(session_id)

        # 应用分页
        paginated_messages = messages[skip : skip + limit]

        return ApiResponse.success(
            {"messages": paginated_messages, "total": len(messages), "skip": skip, "limit": limit}
        )
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
