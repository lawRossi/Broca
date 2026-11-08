"""回归测试：权限 / ask_user 弹窗"有时不出现"的修复。

覆盖两类根因：

1. **服务端订阅/缓存竞态** —— ``_send_to_subscription`` 的"检查订阅者 + 写缓存"
   与 ``_handle_subscription`` 的"加订阅 + 快照 pending"必须原子（同一把锁），
   否则请求会在客户端正好订阅的那一刻被缓存但永远不投递。

2. **引擎 flush 顺序** —— 进入工具执行前必须把缓冲的流式 chunk 刷干净，
   保证线序 ``agent_response`` → ``tool_call`` → ``permission_request``；
   否则延迟 flush 的 ``agent_response`` 会晚于权限请求到达并关掉前端弹窗。

对应前端修复见 ``broca-web/frontend/src/stores/chat.ts``（弹窗按 turnId 精确关闭）
与 ``AgentQueryDialog.vue``（去掉 ``@close`` 自动回空答案）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from broca.communication.socketio_server import ClientInfo, SocketIOServer
from broca.session.models import Message, MessageProtocol, MessageType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def server() -> SocketIOServer:
    """不启动网络的 SocketIOServer 实例。"""
    s = SocketIOServer(host="127.0.0.1", port=0)
    s.sio = MagicMock()
    s.sio.emit = AsyncMock()
    return s


def _register_client(server: SocketIOServer, client_id: str, sid: str) -> None:
    server.clients[sid] = ClientInfo(client_id=client_id, client_type="browser")
    server.client_sids[client_id] = sid


def _permission_request(request_id: str = "req-1") -> Message:
    return MessageProtocol.create_permission_request(
        message="工具需要授权",
        request_id=request_id,
        request_type="tool",
        sender_id="agent-1",
        subscription="sess-1",
        turn_id="turn-1",
    )


def _agent_query(request_id: str = "q-1") -> Message:
    return Message(
        message_type=MessageType.AGENT_QUERY,
        role="agent",
        sender_id="agent-1",
        subscription="sess-1",
        turn_id="turn-1",
        content="你选哪个？",
        data={"question": "你选哪个？", "options": [], "request_id": request_id},
    )


def _emitted_message_types(server: SocketIOServer) -> list[str]:
    return [
        call.args[1]["message_type"]
        for call in server.sio.emit.await_args_list
        if len(call.args) >= 2 and isinstance(call.args[1], dict)
    ]


# ---------------------------------------------------------------------------
# 1. 订阅 / 缓存竞态
# ---------------------------------------------------------------------------


class TestPendingMessageDelivery:
    @pytest.mark.asyncio
    async def test_request_before_subscribe_is_delivered_on_subscribe(self, server):
        """请求先于订阅到达 → 缓存 → 订阅时补投递（弹窗不会丢）。"""
        _register_client(server, "c1", "sid-1")

        result = await server._send_to_subscription("sess-1", _permission_request())
        assert result == {"total": 0, "sent": 0, "failed": 0}
        assert "sess-1" in server._pending_messages

        server.sio.emit.reset_mock()
        await server._handle_subscription("sid-1", {"subscription": "sess-1"}, subscribe=True)

        types = _emitted_message_types(server)
        assert MessageType.SUBSCRIBE.value in types  # ack
        assert MessageType.PERMISSION_REQUEST.value in types  # 补投递

    @pytest.mark.asyncio
    async def test_request_after_subscribe_is_delivered_directly(self, server):
        """订阅先完成 → 请求直接推送（且仍然缓存供重连使用）。"""
        _register_client(server, "c1", "sid-1")
        await server._handle_subscription("sid-1", {"subscription": "sess-1"}, subscribe=True)

        server.sio.emit.reset_mock()
        result = await server._send_to_subscription("sess-1", _permission_request())

        assert result["sent"] == 1
        assert MessageType.PERMISSION_REQUEST.value in _emitted_message_types(server)
        # 仍然缓存，供后续订阅/重连的客户端接收
        assert "sess-1" in server._pending_messages

    @pytest.mark.asyncio
    async def test_interleaved_subscribe_and_request_never_loses_request(self, server):
        """模拟"订阅中"的竞态：无论两个协程如何交错，请求都必须最终到达客户端。

        这里通过并发执行 subscribe 与 send 来放大交错概率，并断言客户端
        最终一定收到了该请求（要么直推、要么补投递），且只收到一次。
        """
        import asyncio

        _register_client(server, "c1", "sid-1")
        msg = _permission_request("req-race")

        await asyncio.gather(
            server._handle_subscription("sid-1", {"subscription": "sess-1"}, subscribe=True),
            server._send_to_subscription("sess-1", msg),
        )

        delivered = [
            call
            for call in server.sio.emit.await_args_list
            if len(call.args) >= 2
            and isinstance(call.args[1], dict)
            and call.args[1]["message_type"] == MessageType.PERMISSION_REQUEST.value
        ]
        assert len(delivered) == 1, "权限请求必须且只能投递一次"

    @pytest.mark.asyncio
    async def test_agent_query_is_cached_and_delivered(self, server):
        """ask_user 的 agent_query 走同样的缓存/补投递路径。"""
        _register_client(server, "c1", "sid-1")

        await server._send_to_subscription("sess-1", _agent_query())
        assert "sess-1" in server._pending_messages

        server.sio.emit.reset_mock()
        await server._handle_subscription("sid-1", {"subscription": "sess-1"}, subscribe=True)
        assert MessageType.AGENT_QUERY.value in _emitted_message_types(server)

    @pytest.mark.asyncio
    async def test_response_removes_pending_request(self, server):
        """收到 PERMISSION_RESPONSE 后缓存条目被清理，避免重复弹窗。"""
        _register_client(server, "c1", "sid-1")
        await server._send_to_subscription("sess-1", _permission_request("req-x"))
        assert "req-x" in server._request_to_subscription

        await server._remove_pending_message_by_request_id("req-x")
        assert "req-x" not in server._request_to_subscription
        assert "sess-1" not in server._pending_messages

    @pytest.mark.asyncio
    async def test_permission_request_carries_turn_id(self, server):
        """权限请求消息必须带 turn_id，前端才能按 turn 精确关闭弹窗。"""
        msg = _permission_request()
        assert msg.turn_id == "turn-1"
        assert MessageProtocol.to_dict(msg)["turn_id"] == "turn-1"


# ---------------------------------------------------------------------------
# 2. 引擎 flush 顺序
# ---------------------------------------------------------------------------


def _build_engine():
    """复用既有 fixture 构造引擎（见 test_engine_event_flow）。"""
    from broca.tests.test_engine_event_flow import _build

    engine, comm = _build([], interactive=True)
    engine.turn_id = "turn-1"
    engine.agent_id = "agent-1"
    engine.session_id = "sess-1"
    return engine, comm


class TestChunkFlushOrdering:
    @pytest.mark.asyncio
    async def test_tool_call_chunk_flushes_pending_content_first(self):
        """content 还在缓冲里时收到 tool_call，必须先 flush content 再发 tool_call。"""
        engine, comm = _build_engine()
        handler = engine._make_chunk_handler()

        # 一小段 content：低于 128 字符阈值 → 进入缓冲，等待 0.1s 定时 flush
        await handler({"type": "content", "data": "正在思考", "index": 0, "message_id": "m1"})
        assert engine._chunk_buffer, "content 应被缓冲而非立即发送"
        assert comm.names() == []

        # tool_call 到达 → 必须先把 content 刷出去
        tool_call = MagicMock()
        tool_call.id = "call-1"
        tool_call.function.name = "ask_user"
        await handler({"type": "tool_call", "data": tool_call})

        assert engine._chunk_buffer == [], "tool_call 前缓冲必须被清空"
        names = comm.names()
        assert names == ["agent_response", "tool_call"], (
            f"顺序必须是 agent_response → tool_call，实际为 {names}"
        )

    @pytest.mark.asyncio
    async def test_flush_now_is_noop_when_buffer_empty(self):
        engine, comm = _build_engine()
        await engine._flush_now()
        assert comm.names() == []


# ---------------------------------------------------------------------------
# 3. 请求消息携带 turn_id（前端据此精确管理弹窗生命周期）
# ---------------------------------------------------------------------------


class TestRequestCarriesTurnId:
    @pytest.mark.asyncio
    async def test_executor_syncs_provider_turn_id(self):
        """工具执行器必须在请求权限前把 context.turn_id 同步给 provider。"""
        from broca.tests.test_tool_execution_behavior import (
            _InstantTool,
            _ctx,
            _init_executor,
            _make_executor,
        )

        executor, pp, comm, config = _make_executor(permission="ask")
        pp.set_turn_id = MagicMock()
        tool = _InstantTool()
        await _init_executor(
            executor, pp, comm, config, tool_mapping={"write_file": tool}
        )

        await executor.execute_tool("write_file", "{}", "call-1", _ctx(), tool)

        pp.set_turn_id.assert_called_with("turn-1")

    @pytest.mark.asyncio
    async def test_permission_request_message_carries_turn_id(self):
        """DefaultPermissionProvider 发出的 permission_request 必须带 turn_id。"""
        from broca.permission_provider import DefaultPermissionProvider

        provider = DefaultPermissionProvider()
        comm = MagicMock()
        comm.send_permission_request = AsyncMock()
        session_manager = MagicMock()
        session_manager.save_message = AsyncMock()

        config = MagicMock()
        config.workspace = None
        config.execution_config = MagicMock(permission_request_timeout=0.05)

        await provider.initialize(
            communicator=comm,
            session_manager=session_manager,
            config=config,
            agent_id="agent-1",
            session_id="sess-1",
        )
        provider.set_turn_id("turn-1")

        await provider.request_tool_permission("write_file", "{}")

        kwargs = comm.send_permission_request.await_args.kwargs
        assert kwargs["turn_id"] == "turn-1"

    @pytest.mark.asyncio
    async def test_ask_user_query_carries_turn_id(self):
        """AskUser 发出的 agent_query 必须带 context.turn_id。"""
        from broca.tools.agent_interaction import AskUser
        from broca.tools.tool import ToolCallContext

        tool = AskUser()
        agent = MagicMock()
        agent.agent_id = "agent-1"
        agent.turn_id = "turn-1"
        agent.session_manager = MagicMock()
        agent.session_manager.save_message = AsyncMock()
        agent.config = MagicMock()
        agent.config.execution_config = MagicMock(agent_query_timeout=0.05)
        agent.communicator = MagicMock()
        agent.communicator.send_message = AsyncMock()

        ctx = ToolCallContext()
        ctx.agent = agent
        ctx.session_id = "sess-1"
        ctx.turn_id = "turn-1"

        await tool._execute({"question": "选哪个？"}, ctx)

        sent = agent.communicator.send_message.await_args.args[0]
        assert sent.message_type == MessageType.AGENT_QUERY
        assert sent.turn_id == "turn-1"

    @pytest.mark.asyncio
    async def test_flush_now_waits_for_inflight_flush(self):
        """在途的定时 flush 未完成时，``_flush_now`` 必须等它结束。

        否则 ``_flush_now`` 会以为 buffer 已空而立即返回，调用方随即发出
        ``tool_call`` / ``permission_request``，而 ``agent_response`` 的
        emit 还在进行中 → 线序错乱、弹窗被关。
        """
        import asyncio

        engine, comm = _build_engine()
        order: list[str] = []
        gate = asyncio.Event()

        async def slow_send(**kwargs):
            order.append("start:" + kwargs["content"])
            await gate.wait()
            order.append("end:" + kwargs["content"])

        comm.send_agent_response = slow_send

        handler = engine._make_chunk_handler()
        await handler({"type": "content", "data": "A", "index": 0, "message_id": "m1"})
        assert engine._chunk_buffer

        # 模拟定时器到期开始 flush，并卡在 emit 上
        inflight = asyncio.create_task(engine._do_flush())
        await asyncio.sleep(0)
        assert order == ["start:A"]

        # 此时再来一次 flush_now：必须等待在途 flush，而不是立刻返回
        flush_now = asyncio.create_task(engine._flush_now())
        await asyncio.sleep(0.01)
        assert not flush_now.done(), "_flush_now 不应在在途 flush 完成前返回"

        gate.set()
        await asyncio.gather(inflight, flush_now)
        assert order == ["start:A", "end:A"]
