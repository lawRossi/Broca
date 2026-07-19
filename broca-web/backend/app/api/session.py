"""Session API

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
    get_turn_service,
)
from broca.session_runner import RunnerManager
from broca.session_runner.manager import RunnerManagerError
from broca.utils.datetime_util import serialize_dt
from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from app.schemas.schemas import ApiResponse, CreateSessionRequest, UpdateSessionRequest

router = APIRouter()


async def _start_runner_background(
    session_id: str,
    workspace: str,
    provider: str | None = None,
    model: str | None = None,
) -> None:
    """后台启动 Runner 进程（失败仅记录日志，不影响会话记录）"""
    try:
        runner_manager = RunnerManager()
        await runner_manager.start_session(
            session_id=session_id,
            workspace=workspace,
            provider=provider,
            model=model,
        )
        logger.info(f"Runner started for session {session_id}")
    except RunnerManagerError:
        logger.exception(f"Failed to start runner for session {session_id} in background")
    except Exception:
        logger.exception(f"Unexpected error starting runner for session {session_id}")


async def _cleanup_failed_session(session_id: str) -> None:
    """清理创建失败的 session（删除数据库记录）"""
    try:
        from broca.session.service import get_session_service

        service = get_session_service()
        await service.delete(session_id)
        logger.info(f"Cleaned up failed session: {session_id}")
    except Exception as e:
        logger.warning(f"Failed to clean up session {session_id}: {e}")


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
    session_id = None
    try:
        workspace = request.workspace
        if workspace is None:
            workspace = tempfile.mkdtemp(prefix="broca_session_")
            logger.info(f"Created temporary workspace: {workspace}")

        # === 阶段1: 在数据库中创建 Session 和 Agent 记录 ===
        factory = AgentFactory()
        agents, session_id = await factory.init_session_agents(
            workspace=workspace,
            provider=request.provider,
            model=request.model,
            category=request.category or "normal",
        )

        category = request.category or "normal"
        if not agents:
            if category == "agent-orchestration":
                raise HTTPException(
                    400, "workspace中未找到Agent配置。请在workspace的.agents/agents/目录下创建Agent配置文件"
                )
            else:
                raise HTTPException(500, "No agents were initialized")

        # === 阶段2: 更新 Session 信息 ===
        session_service = get_session_service()
        update_data = {}
        if request.description:
            update_data["description"] = request.description
        if workspace:
            update_data["workspace"] = workspace
        if request.category:
            update_data["category"] = request.category
        if update_data:
            await session_service.update(session_id, **update_data)

        # === 阶段3: 后台启动 Runner 进程（不阻塞响应，失败不清理数据库） ===
        start_runner_task = asyncio.create_task(
            _start_runner_background(
                session_id=session_id,
                workspace=workspace,
                provider=request.provider,
                model=request.model,
            )
        )
        start_runner_task.add_done_callback(lambda task: logger.info(f"Runner started for session {session_id}"))

        logger.info(
            f"Session created (runner starting in background): {session_id}, workspace: {workspace}, "
            f"provider: {request.provider}, model: {request.model}"
        )

        return ApiResponse.success(
            {
                "session_id": session_id,
                "workspace": workspace,
                "description": request.description,
                "provider": request.provider,
                "model": request.model,
                "category": request.category or "normal",
            },
            msg="Session created successfully",
        )
    except HTTPException:
        if session_id:
            await _cleanup_failed_session(session_id)
        raise

    except Exception as e:
        # 创建失败时清理已入库的 session 记录
        if session_id:
            await _cleanup_failed_session(session_id)
        raise HTTPException(500, f"Failed to create session: {e!s}") from e


@router.get("/sessions", response_model=ApiResponse)
async def get_sessions(skip: int = 0, limit: int = 20, keyword: str | None = None) -> ApiResponse:
    """获取会话列表，支持分页和关键词搜索"""
    try:
        session_service = get_session_service()

        # 获取所有会话
        sessions = await session_service.get_batch(order_by="created_at desc")

        # 关键词过滤（在分页之前，确保搜索能查到所有匹配的记录）
        if keyword:
            keyword_lower = keyword.lower()
            sessions = [
                s
                for s in sessions
                if (s.description and keyword_lower in s.description.lower()) or keyword_lower in s.session_id.lower()
            ]

        # 分页
        total = len(sessions)
        sessions = sessions[skip : skip + limit]

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
        logger.exception("Error getting sessions")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.get("/{session_id}", response_model=ApiResponse)
async def get_session(session_id: str) -> ApiResponse:
    """直接根据 session_id 获取单个会话详情"""
    try:
        session_service = get_session_service()
        session = await session_service.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        session_dict = session.model_dump()
        runner_manager = RunnerManager()
        runner_status = runner_manager.get_session_status(session_id)
        session_dict["runner_status"] = runner_status["status"] if runner_status else "none"

        return ApiResponse.success(session_dict, msg="Session retrieved successfully")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting session")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.get("/{session_id}/agents", response_model=ApiResponse)
async def get_session_agents(session_id: str, req: Request) -> ApiResponse:
    """获取会话的Agent列表（从数据库读取真实 agent_status）"""
    try:
        # 获取会话的Agent
        agent_service = get_agent_service()
        agents = await agent_service.get_agents_by_session(session_id)
        if not agents:
            raise HTTPException(status_code=404, detail="Session not found")

        response_agents: list[dict] = []
        for db_agent in agents:
            response_agent = db_agent.model_dump()
            # 直接使用数据库中持久化的 agent_status（由 Runner 心跳同步更新）
            # 可能的值: idle / running / disconnected
            # 保留 agent_status 供 TUI 客户端使用，同时添加 status 别名供 Web 前端使用
            response_agent["status"] = response_agent.get("agent_status", "disconnected")
            response_agents.append(response_agent)

        return ApiResponse.success(response_agents)
    except Exception as e:
        logger.exception("Error getting session agents")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.get("/{session_id}/messages", response_model=ApiResponse)
async def get_session_messages(
    session_id: str,
    skip: int = 0,
    limit: int = 50,
    execution_id: str | None = None,
) -> ApiResponse:
    """获取会话的消息历史（按时间正序），支持分页

    Args:
        session_id: 会话ID
        skip: 跳过的记录数
        limit: 返回的最大记录数
        execution_id: 可选，按编排执行ID过滤（只返回该编排产生的消息）

    """
    try:
        session_service = get_session_service()
        session = await session_service.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        message_service = get_message_service()

        if execution_id:
            # 按 execution_id 过滤时：降序取最新消息，reverse 后返回（与无过滤一致）
            total = await message_service.count_messages_by_execution(session_id, execution_id)
            messages = await message_service.get_messages_by_session(
                session_id,
                order_by="sequence_number desc",
                skip=skip,
                limit=limit,
                execution_id=execution_id,
            )
            messages.reverse()
        else:
            total = await message_service.count({"session_id": session_id})
            messages = await message_service.get_messages_by_session(
                session_id, order_by="sequence_number desc", skip=skip, limit=limit
            )
            messages.reverse()

        return ApiResponse.success({"messages": messages, "total": total, "skip": skip, "limit": limit})
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting session messages")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.get("/{session_id}/messages/search", response_model=ApiResponse)
async def search_session_messages(
    session_id: str,
    keyword: str | None = None,
    message_type: str | None = None,
    sender_id: str | None = None,
    tool_name: str | None = None,
    order: str = "desc",
    skip: int = 0,
    limit: int = 50,
) -> ApiResponse:
    """搜索会话中的消息，支持关键词和多个字段筛选

    Args:
        session_id: 会话ID
        keyword: 搜索关键词，匹配 data 字段中的文本内容
        message_type: 按消息类型过滤（如 user_message, agent_response, tool_call）
        sender_id: 按发送者ID过滤
        tool_name: 按工具名称过滤（仅 tool_call 消息）
        order: 排序方向，desc（最新在前）或 asc（最早在前）
        skip: 分页偏移
        limit: 每页数量（最大 200）

    """
    try:
        session_service = get_session_service()
        session = await session_service.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        limit = min(limit, 200)

        message_service = get_message_service()
        messages, total = await message_service.search_messages(
            session_id=session_id,
            keyword=keyword,
            message_type=message_type,
            sender_id=sender_id,
            tool_name=tool_name,
            order=order,
            skip=skip,
            limit=limit,
        )

        return ApiResponse.success({
            "messages": messages,
            "total": total,
            "skip": skip,
            "limit": limit,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error searching session messages")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.get("/{session_id}/messages/search/filters", response_model=ApiResponse)
async def get_search_filters(session_id: str) -> ApiResponse:
    """获取搜索筛选选项（可用的消息类型、工具名称等）"""
    try:
        session_service = get_session_service()
        session = await session_service.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        message_service = get_message_service()
        tool_names = await message_service.get_distinct_tool_names(session_id)

        return ApiResponse.success({
            "tool_names": tool_names,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting search filters")
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

        # 先停止所有 Runner 进程（超时缩短至2秒）
        for session_id in session_ids:
            await runner_manager.stop_session(session_id, timeout=2.0)

        # 再从数据库删除
        deleted_count = await session_service.delete_batch(session_ids)

        logger.info(f"Batch delete sessions: {session_ids}, deleted: {deleted_count}")
        return ApiResponse.success(
            {"deleted_count": deleted_count}, msg=f"Successfully deleted {deleted_count} sessions"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error batch deleting sessions")
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
        logger.exception("Error updating session")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.delete("/{session_id}", response_model=ApiResponse)
async def delete_session(session_id: str) -> ApiResponse:
    """删除单个会话（先停止 Runner，再删除数据库记录）"""
    try:
        session_service = get_session_service()
        session = await session_service.get(session_id)

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # 先停止 Runner 进程（超时缩短至2秒，避免用户等待太久）
        runner_manager = RunnerManager()
        await runner_manager.stop_session(session_id, timeout=2.0)

        # 再从数据库删除
        success = await session_service.delete(session_id)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete session")

        logger.info(f"Session deleted: {session_id}")
        return ApiResponse.success(msg="Session deleted successfully")

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error deleting session")

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
        except json.JSONDecodeError:
            logger.exception("Failed to parse agent config JSON")
            config_content = {"error": "Failed to parse config content", "raw_content": agent_config.config_content}

        # 返回完整的配置信息
        config_data = {
            "agent_id": agent.agent_id,
            "agent_name": agent.name,
            "agent_role": agent.role,
            "config_id": agent_config.config_id,
            "config_name": agent_config.name,
            "config_content": config_content,
            "created_at": serialize_dt(agent_config.created_at),
            "raw_config_content": agent_config.config_content,
        }

        return ApiResponse.success(config_data, msg="Agent config retrieved successfully")

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting agent config")

        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.put("/{session_id}/agents/{agent_id}/config", response_model=ApiResponse)
async def update_agent_config(session_id: str, agent_id: str, request: Request) -> ApiResponse:
    """更新指定Agent的配置信息"""
    try:
        import json
        from pathlib import Path

        # 获取请求体
        body = await request.json()
        config_content = body.get("config_content")

        if not config_content:
            raise HTTPException(status_code=400, detail="config_content is required")

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

        # 更新配置内容到数据库
        updated_config_content = json.dumps(config_content, ensure_ascii=False, indent=4)
        await agent_config_service.update(agent_config.config_id, config_content=updated_config_content)

        # 更新 workspace 下的 agent 配置缓存文件
        # session 加载时优先读取该缓存文件 (AgentManager.restore_agent)
        workspace = config_content.get("workspace") or session.workspace
        agent_name = config_content.get("name") or agent.name
        if workspace:
            cache_path = Path(workspace) / ".broca" / session_id / "agents" / f"{agent_name}.json"
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(updated_config_content)
            logger.info(f"Updated agent config cache file: {cache_path}")

        # 返回更新后的配置
        config_data = {
            "agent_id": agent.agent_id,
            "agent_name": agent.name,
            "agent_role": agent.role,
            "config_id": agent_config.config_id,
            "config_name": agent_config.name,
            "config_content": config_content,
            "created_at": serialize_dt(agent_config.created_at),
        }

        return ApiResponse.success(config_data, msg="Agent config updated successfully")

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error updating agent config")
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
        logger.exception("Error getting session stats")

        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.get("/{session_id}/turns", response_model=ApiResponse)
async def get_session_turns(
    session_id: str,
    skip: int = 0,
    limit: int = 20,
    execution_id: str | None = None,
) -> ApiResponse:
    """获取会话的 turn 摘要列表（简洁模式使用）。

    按 sequence_number desc 排序（最新的 turn 在前），
    返回时反转（最早的在前）。

    每个 turn 带有 is_reverted 标记，前端自行过滤已撤销的 turn。
    支持按 execution_id 过滤（仅返回指定编排执行的 turn）。
    """
    try:
        session_service = get_session_service()
        session = await session_service.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        turn_service = get_turn_service()
        agent_service = get_agent_service()

        total = await turn_service.count_turns_by_session(session_id, execution_id=execution_id)
        turns = await turn_service.get_turns_by_session(
            session_id, order_by="sequence_number desc",
            skip=skip, limit=limit, execution_id=execution_id,
        )

        turn_list = []
        for t in turns:
            start_time, end_time = await turn_service.get_turn_time_range(t.turn_id)
            duration = None
            if start_time and end_time:
                duration = (end_time - start_time).total_seconds()

            agent = await agent_service.get(t.agent_id) if t.agent_id else None
            stats = await turn_service.get_turn_stats(t.turn_id)

            # turn 状态：'active', 'completed', 'error'
            # 兼容旧数据/活跃 turn：None → 'active'
            # 只有调用了 process_turn_end 后 status 才会被设为 'completed' 或 'error'
            turn_status = t.status or "active"

            # is_active: 没有 turn_end 消息且状态为 active 的 turn 为活跃 turn
            is_active = turn_status == "active" and end_time is None

            turn_list.append({
                "turn_id": t.turn_id,
                "sequence_number": t.sequence_number,
                "agent_id": t.agent_id,
                "agent_name": agent.name if agent else None,
                "status": turn_status,
                "is_active": is_active,
                "started_at": serialize_dt(start_time),
                "ended_at": serialize_dt(end_time),
                "duration_seconds": round(duration, 1) if duration else None,
                "created_at": serialize_dt(t.created_at),
                # 统计数据
                "is_reverted": stats.get("is_reverted", False),
                "user_message": stats["user_message"],
                "total_steps": stats["total_steps"],
                "tool_call_stats": stats["tool_call_stats"],
                "current_file_path": stats["current_file_path"],
                "current_todo_list": stats["current_todo_list"],
                "final_response": stats["final_response"],
                "last_message_id": stats.get("last_message_id"),
                "changed_files": stats.get("changed_files", {}),
            })

        turn_list.reverse()

        return ApiResponse.success({
            "turns": turn_list,
            "total": total,
            "skip": skip,
            "limit": limit,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting session turns")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.get("/{session_id}/turns/{turn_id}/file-diff", response_model=ApiResponse)
async def get_turn_file_diff(
    session_id: str,
    turn_id: str,
    path: str,
) -> ApiResponse:
    """获取 turn 中指定文件的 unified diff。

    后端从 turn_end 消息中提取最早/最晚快照哈希，
    实时计算该文件的 diff 并返回。
    """
    try:
        turn_service = get_turn_service()
        diff = await turn_service.get_file_diff(session_id, turn_id, path)
        if diff is None:
            return ApiResponse.success({
                "diff": "",
                "file_path": path,
            })
        return ApiResponse.success({
            "diff": diff,
            "file_path": path,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting file diff for {path}")
        raise HTTPException(500, f"Internal server error: {e!s}") from e
