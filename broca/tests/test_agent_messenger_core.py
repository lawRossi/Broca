"""Integration tests for agent-to-agent communication (Phase 3, Task 3.2).

Covers ``DefaultAgentMessenger`` (request / notify / delegate / reply /
handle_request_response), the ``Communicate`` tool, and the ``Agent`` handler
methods (``_handle_incoming_request`` / ``_handle_incoming_delegate`` /
``run`` chain entry / mid-turn drain / agent 发起的 turn 自动带 drainer).

Scope note (user constraint "可选增强不用做"): ``CommunicationBudget`` and
optional notify/delegate chain detection are **not** implemented — there are
therefore no budget / toggle two-state tests here.  Core mechanisms (ACL,
delegate task-existence check, reply guarantee, request timeout, request
forced cycle detection) are fully covered.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from broca.agent import Agent
from broca.agent_configs import CommunicationPolicy
from broca.agent_messenger.call_chain import CallChain
from broca.agent_messenger.message_models import AgentCommunication
from broca.agent_messenger.messenger import AgentCommunicationError, DefaultAgentMessenger
from broca.communication.socketio_client import SocketIOClient
from broca.components.loop_engine import ExecutionResult, ExecutionStatus
from broca.session.models import Message, MessageProtocol, MessageType
from broca.tools.agent_interaction import Communicate
from broca.tools.tool import ToolCallContext, ToolStatus


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeTarget:
    def __init__(self, agent_id: str):
        self.agent_id = agent_id


class FakeAgentFactory:
    """Maps agent name -> FakeTarget; returns None for unknown names."""

    def __init__(self, mapping: dict[str, str] | None = None):
        self.mapping = mapping or {}

    def get_agent(self, session_id, name):
        if name in self.mapping:
            return FakeTarget(self.mapping[name])
        return None


class FakeTaskManager:
    def __init__(self, existing: set[str] | None = None):
        self.existing = existing or set()

    async def get_task(self, task_id):
        return object() if task_id in self.existing else None


class FakeCommunicator:
    """Records ``send`` calls; returns a configurable ACK."""

    def __init__(self, ack: dict | None = None):
        self.ack = ack if ack is not None else {"status": "routed"}
        self.sent: list[dict] = []

    async def send(self, content, data, receiver_id):
        self.sent.append(
            {"content": content, "data": data, "receiver_id": receiver_id}
        )
        return self.ack


class FakeConfig:
    def __init__(self, policy: CommunicationPolicy | None = None, workspace: str = ""):
        self.communication_policy = policy or CommunicationPolicy()
        self.workspace = workspace


async def _wait_until(predicate, timeout: float = 2.0):
    """Poll until ``predicate()`` is truthy or timeout."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.001)
    raise AssertionError("condition not met within timeout")


async def make_messenger(
    *,
    agent_id: str = "A",
    name: str = "A",
    session_id: str = "sess",
    communicator: FakeCommunicator | None = None,
    factory: FakeAgentFactory | None = None,
    task_manager=None,
    policy: CommunicationPolicy | None = None,
    workspace: str = "",
) -> DefaultAgentMessenger:
    m = DefaultAgentMessenger()
    await m.initialize(
        agent_id=agent_id,
        name=name,
        session_id=session_id,
        communicator=communicator or FakeCommunicator(),
        agent_factory=factory or FakeAgentFactory({"A": "A", "B": "B", "C": "C"}),
        task_manager=task_manager,
        config=FakeConfig(policy, workspace),
    )
    return m


def _reply_message(request_id: str, content: str, status: str = "success") -> Message:
    # Message has no ``content`` field — content lives in ``data``.
    return Message(
        message_type=MessageType.AGENT_REQUEST_RESPONSE,
        role="agent",
        sender_id="B",
        subscription="sess",
        data={"request_id": request_id, "status": status, "content": content},
    )


# ---------------------------------------------------------------------------
# request — sync semantics
# ---------------------------------------------------------------------------


class TestRequest:
    @pytest.mark.asyncio
    async def test_request_blocks_until_reply(self):
        comm = FakeCommunicator()
        m = await make_messenger(communicator=comm)

        task = asyncio.create_task(m.request("B", "ping"))
        await _wait_until(lambda: len(m._pending_requests) == 1)

        # Not returned yet (still blocked awaiting reply).
        assert not task.done()
        request_id = next(iter(m._pending_requests))
        assert comm.sent[-1]["data"]["mode"] == "request"
        assert comm.sent[-1]["data"]["request_id"] == request_id

        await m.handle_request_response(_reply_message(request_id, "pong"))
        reply, status = await asyncio.wait_for(task, timeout=1)
        assert reply == "pong"
        assert status == "success"

    @pytest.mark.asyncio
    async def test_request_id_pairing_two_concurrent(self):
        comm = FakeCommunicator()
        m = await make_messenger(communicator=comm)

        t1 = asyncio.create_task(m.request("B", "first"))
        t2 = asyncio.create_task(m.request("C", "second"))
        await _wait_until(lambda: len(m._pending_requests) == 2)

        ids = list(m._pending_requests)
        rid1, rid2 = ids[0], ids[1]
        # Reply in reverse order to prove pairing (not FIFO).
        await m.handle_request_response(_reply_message(rid2, "reply-2"))
        await m.handle_request_response(_reply_message(rid1, "reply-1"))

        r1, s1 = await asyncio.wait_for(t1, timeout=1)
        r2, s2 = await asyncio.wait_for(t2, timeout=1)
        assert (r1, s1) == ("reply-1", "success")
        assert (r2, s2) == ("reply-2", "success")

    @pytest.mark.asyncio
    async def test_request_reply_not_enqueued_directly_consumed(self):
        """AGENT_REQUEST_RESPONSE is consumed by handle_request_response — the
        request() future is woken directly, not via any queue."""
        comm = FakeCommunicator()
        m = await make_messenger(communicator=comm)
        task = asyncio.create_task(m.request("B", "hi"))
        await _wait_until(lambda: len(m._pending_requests) == 1)
        request_id = next(iter(m._pending_requests))
        await m.handle_request_response(_reply_message(request_id, "done"))
        reply, _ = await asyncio.wait_for(task, timeout=1)
        assert reply == "done"
        # No leftover pending and no queue involved.
        assert m._pending_requests == {}

    @pytest.mark.asyncio
    async def test_request_status_maps_from_reply(self):
        comm = FakeCommunicator()
        m = await make_messenger(communicator=comm)
        task = asyncio.create_task(m.request("B", "hi"))
        await _wait_until(lambda: len(m._pending_requests) == 1)
        request_id = next(iter(m._pending_requests))
        await m.handle_request_response(
            _reply_message(request_id, "boom", status="error")
        )
        reply, status = await asyncio.wait_for(task, timeout=1)
        assert status == "error"


class TestRequestTimeoutAndLateReply:
    @pytest.mark.asyncio
    async def test_request_timeout_raises_and_cleans_pending(self):
        policy = CommunicationPolicy(request_timeout=0.05)
        m = await make_messenger(policy=policy)

        with pytest.raises(AgentCommunicationError) as ei:
            await m.request("B", "never answered")
        assert ei.value.reason == "request_timeout"
        assert m._pending_requests == {}

    @pytest.mark.asyncio
    async def test_late_reply_after_timeout_is_ignored(self):
        policy = CommunicationPolicy(request_timeout=0.05)
        m = await make_messenger(policy=policy)

        with pytest.raises(AgentCommunicationError):
            await m.request("B", "never answered")

        # Late reply for a request that already timed out: no pending, ignored.
        await m.handle_request_response(_reply_message("stale-id", "too late"))
        assert m._pending_requests == {}

        # A fresh request still works afterwards.
        task = asyncio.create_task(m.request("B", "again"))
        await _wait_until(lambda: len(m._pending_requests) == 1)
        rid = next(iter(m._pending_requests))
        await m.handle_request_response(_reply_message(rid, "ok"))
        reply, status = await asyncio.wait_for(task, timeout=1)
        assert (reply, status) == ("ok", "success")

    @pytest.mark.asyncio
    async def test_reply_without_request_id_is_ignored(self):
        m = await make_messenger()
        msg = Message(
            message_type=MessageType.AGENT_REQUEST_RESPONSE,
            role="agent",
            content="x",
            data={},
        )
        await m.handle_request_response(msg)  # must not raise
        assert m._pending_requests == {}


# ---------------------------------------------------------------------------
# request — core control: cycle detection + ACL + depth
# ---------------------------------------------------------------------------


class TestRequestCycleAndACL:
    @pytest.mark.asyncio
    async def test_request_cycle_detection_rejects_before_delivery(self):
        comm = FakeCommunicator()
        m = await make_messenger(communicator=comm)
        m.set_call_chain(CallChain(agent_ids=["B"]))
        with pytest.raises(AgentCommunicationError) as ei:
            await m.request("B", "hi")
        assert ei.value.reason == "chain_cycle"
        assert comm.sent == []  # not delivered

    @pytest.mark.asyncio
    async def test_request_chain_depth_exceeded(self):
        comm = FakeCommunicator()
        policy = CommunicationPolicy(max_chain_depth=3)
        m = await make_messenger(communicator=comm, policy=policy)
        m.set_call_chain(CallChain(agent_ids=["X", "Y", "Z"]))  # depth 3 == max
        with pytest.raises(AgentCommunicationError) as ei:
            await m.request("B", "hi")
        assert ei.value.reason == "chain_depth_exceeded"
        assert comm.sent == []

    @pytest.mark.asyncio
    async def test_request_acl_denied(self):
        comm = FakeCommunicator()
        policy = CommunicationPolicy(allowed_targets=["A"])
        m = await make_messenger(communicator=comm, policy=policy)
        with pytest.raises(AgentCommunicationError) as ei:
            await m.request("C", "hi")
        assert ei.value.reason == "acl_denied"
        assert comm.sent == []

    @pytest.mark.asyncio
    async def test_request_acl_mode_denied(self):
        comm = FakeCommunicator()
        policy = CommunicationPolicy(allowed_modes=["notify"])
        m = await make_messenger(communicator=comm, policy=policy)
        with pytest.raises(AgentCommunicationError) as ei:
            await m.request("B", "hi")
        assert ei.value.reason == "acl_denied"

    @pytest.mark.asyncio
    async def test_a_to_b_mutual_request_rejected_first_hop(self):
        """A→B request carries chain=[A]; B (chain=[A,B]) requesting A back is
        rejected with chain_cycle on the *first hop* (not via timeout)."""
        comm_b = FakeCommunicator()
        m_b = await make_messenger(agent_id="B", name="B", communicator=comm_b)
        # B entered run() with the inbound request's chain [A], then added itself.
        m_b.set_call_chain(CallChain.from_dict({"agent_ids": ["A"]}).add("B"))
        with pytest.raises(AgentCommunicationError) as ei:
            await m_b.request("A", "reply please")
        assert ei.value.reason == "chain_cycle"
        assert comm_b.sent == []


# ---------------------------------------------------------------------------
# routing_failed fast-fail (all three modes)
# ---------------------------------------------------------------------------


class TestRoutingFailed:
    @pytest.mark.asyncio
    async def test_request_routing_failed_fast(self):
        comm = FakeCommunicator(ack={"status": "routing_failed", "reason": "offline"})
        m = await make_messenger(communicator=comm)
        with pytest.raises(AgentCommunicationError) as ei:
            await m.request("B", "hi")
        assert ei.value.reason == "routing_failed"
        assert m._pending_requests == {}

    @pytest.mark.asyncio
    async def test_notify_routing_failed_fast(self):
        comm = FakeCommunicator(ack={"status": "routing_failed", "reason": "offline"})
        m = await make_messenger(communicator=comm)
        with pytest.raises(AgentCommunicationError) as ei:
            await m.notify("B", "hi")
        assert ei.value.reason == "routing_failed"

    @pytest.mark.asyncio
    async def test_delegate_routing_failed_fast(self):
        comm = FakeCommunicator(ack={"status": "routing_failed", "reason": "offline"})
        tm = FakeTaskManager(existing={"task-1"})
        m = await make_messenger(communicator=comm, task_manager=tm)
        with pytest.raises(AgentCommunicationError) as ei:
            await m.delegate("B", "task-1", "do it")
        assert ei.value.reason == "routing_failed"


# ---------------------------------------------------------------------------
# notify
# ---------------------------------------------------------------------------


class TestNotify:
    @pytest.mark.asyncio
    async def test_notify_delivers_as_agent_notify(self):
        comm = FakeCommunicator()
        m = await make_messenger(communicator=comm)
        await m.notify("B", "heads up")
        assert len(comm.sent) == 1
        data = comm.sent[0]["data"]
        assert data["mode"] == "notify"
        assert data["kind"] == "notify"
        # Transport maps mode "notify" -> AGENT_NOTIFY.
        assert SocketIOClient._SEND_TYPE_BY_MODE["notify"] == MessageType.AGENT_NOTIFY

    @pytest.mark.asyncio
    async def test_notify_acl_denied(self):
        comm = FakeCommunicator()
        policy = CommunicationPolicy(allowed_targets=["A"])
        m = await make_messenger(communicator=comm, policy=policy)
        with pytest.raises(AgentCommunicationError) as ei:
            await m.notify("C", "hi")
        assert ei.value.reason == "acl_denied"
        assert comm.sent == []


# ---------------------------------------------------------------------------
# delegate
# ---------------------------------------------------------------------------


class TestDelegate:
    @pytest.mark.asyncio
    async def test_delegate_success_waits_ack_not_receipt(self):
        comm = FakeCommunicator(ack={"status": "routed"})
        tm = FakeTaskManager(existing={"task-1"})
        m = await make_messenger(communicator=comm, task_manager=tm)
        # Returns immediately after ACK (does not block on a receipt).
        await asyncio.wait_for(m.delegate("B", "task-1", "do it"), timeout=1)
        assert comm.sent[-1]["data"]["mode"] == "delegate"
        assert comm.sent[-1]["data"]["task_id"] == "task-1"

    @pytest.mark.asyncio
    async def test_delegate_task_id_required(self):
        comm = FakeCommunicator()
        tm = FakeTaskManager()
        m = await make_messenger(communicator=comm, task_manager=tm)
        with pytest.raises(AgentCommunicationError) as ei:
            await m.delegate("B", "", "do it")
        assert ei.value.reason == "task_id_required"
        assert comm.sent == []

    @pytest.mark.asyncio
    async def test_delegate_task_not_found(self):
        comm = FakeCommunicator()
        tm = FakeTaskManager(existing=set())  # nothing exists
        m = await make_messenger(communicator=comm, task_manager=tm)
        with pytest.raises(AgentCommunicationError) as ei:
            await m.delegate("B", "missing", "do it")
        assert ei.value.reason == "task_not_found"
        assert comm.sent == []

    @pytest.mark.asyncio
    async def test_delegate_acl_denied(self):
        comm = FakeCommunicator()
        tm = FakeTaskManager(existing={"task-1"})
        policy = CommunicationPolicy(allowed_targets=["A"])
        m = await make_messenger(communicator=comm, task_manager=tm, policy=policy)
        with pytest.raises(AgentCommunicationError) as ei:
            await m.delegate("C", "task-1", "do it")
        assert ei.value.reason == "acl_denied"
        assert comm.sent == []


# ---------------------------------------------------------------------------
# Agent handler methods: reply guarantee + delegate receipt
# ---------------------------------------------------------------------------


class _FakeContext:
    def __init__(self, latest: str = ""):
        self._latest = latest

    def get_latest_assistant_message(self):
        return self._latest


class FakeHandlerAgent:
    """Minimal object exposing what the Agent handler methods touch."""

    def __init__(self, messenger, run_result=None, run_raises=None, latest=""):
        self.agent_id = messenger.agent_id
        self.messenger = messenger
        self.context = _FakeContext(latest)
        self._run_result = run_result
        self._run_raises = run_raises

    async def run(self, message, from_agent=False, call_chain=None):
        if self._run_raises is not None:
            raise self._run_raises
        return self._run_result


def _incoming_request_comm(request_id: str = "req-1", source="B") -> AgentCommunication:
    return AgentCommunication(
        source_agent=source,
        target_agent="A",
        mode="request",
        content="please answer",
        request_id=request_id,
        call_chain={"agent_ids": [source]},
    )


class TestRequestReplyGuarantee:
    @pytest.mark.asyncio
    async def test_normal_path_replies_success(self):
        comm = FakeCommunicator()
        m = await make_messenger(communicator=comm)
        agent = FakeHandlerAgent(
            m,
            run_result=ExecutionResult(status=ExecutionStatus.COMPLETED, message="ok"),
            latest="the answer",
        )
        await Agent._handle_incoming_request(agent, _incoming_request_comm("req-1"))
        reply = comm.sent[-1]["data"]
        assert reply["mode"] == "request_reply"
        assert reply["request_id"] == "req-1"
        assert reply["status"] == "success"
        assert reply["content"] == "the answer"

    @pytest.mark.asyncio
    async def test_error_path_replies_error(self):
        comm = FakeCommunicator()
        m = await make_messenger(communicator=comm)
        agent = FakeHandlerAgent(
            m,
            run_result=ExecutionResult(
                status=ExecutionStatus.ERROR, message="boom", error="boom"
            ),
        )
        await Agent._handle_incoming_request(agent, _incoming_request_comm("req-2"))
        reply = comm.sent[-1]["data"]
        assert reply["request_id"] == "req-2"
        assert reply["status"] == "error"

    @pytest.mark.asyncio
    async def test_abort_path_replies_aborted(self):
        comm = FakeCommunicator()
        m = await make_messenger(communicator=comm)
        agent = FakeHandlerAgent(
            m, run_result=ExecutionResult(status=ExecutionStatus.ABORTED)
        )
        await Agent._handle_incoming_request(agent, _incoming_request_comm("req-3"))
        reply = comm.sent[-1]["data"]
        assert reply["request_id"] == "req-3"
        assert reply["status"] == "aborted"

    @pytest.mark.asyncio
    async def test_exception_path_still_replies(self):
        comm = FakeCommunicator()
        m = await make_messenger(communicator=comm)
        agent = FakeHandlerAgent(m, run_raises=RuntimeError("kaboom"))
        await Agent._handle_incoming_request(agent, _incoming_request_comm("req-4"))
        reply = comm.sent[-1]["data"]
        assert reply["request_id"] == "req-4"
        assert reply["status"] == "error"
        assert "kaboom" in reply["content"]


def _incoming_delegate_comm(task_id="task-1", source="B") -> AgentCommunication:
    return AgentCommunication(
        source_agent=source,
        target_agent="A",
        mode="delegate",
        content="do the task",
        task_id=task_id,
        call_chain={"agent_ids": [source]},
    )


class TestDelegateReceiptGuarantee:
    @pytest.mark.asyncio
    async def test_normal_path_sends_receipt(self):
        comm = FakeCommunicator()
        tm = FakeTaskManager(existing={"task-1"})
        m = await make_messenger(communicator=comm, task_manager=tm)
        agent = FakeHandlerAgent(
            m,
            run_result=ExecutionResult(status=ExecutionStatus.COMPLETED, message="done!"),
        )
        await Agent._handle_incoming_delegate(agent, _incoming_delegate_comm("task-1"))
        receipt = comm.sent[-1]["data"]
        assert receipt["mode"] == "notify"
        assert receipt["kind"] == "delegate_receipt"
        assert receipt["task_id"] == "task-1"
        # Transport maps this to AGENT_NOTIFY (no AGENT_DELEGATE_RESPONSE exists).
        assert (
            SocketIOClient._SEND_TYPE_BY_MODE["notify"] == MessageType.AGENT_NOTIFY
        )

    @pytest.mark.asyncio
    async def test_task_not_found_sends_receipt_without_running(self):
        comm = FakeCommunicator()
        tm = FakeTaskManager(existing=set())  # task deleted mid-flight
        m = await make_messenger(communicator=comm, task_manager=tm)
        # run must NOT be called; receipt says "Task not found".
        agent = FakeHandlerAgent(
            m,
            run_result=ExecutionResult(status=ExecutionStatus.COMPLETED, message="X"),
        )
        await Agent._handle_incoming_delegate(agent, _incoming_delegate_comm("gone"))
        receipt = comm.sent[-1]["data"]
        assert receipt["kind"] == "delegate_receipt"
        assert "Task not found" in receipt["content"]

    @pytest.mark.asyncio
    async def test_exception_path_sends_receipt(self):
        comm = FakeCommunicator()
        tm = FakeTaskManager(existing={"task-1"})
        m = await make_messenger(communicator=comm, task_manager=tm)
        agent = FakeHandlerAgent(m, run_raises=RuntimeError("kaboom"))
        await Agent._handle_incoming_delegate(agent, _incoming_delegate_comm("task-1"))
        receipt = comm.sent[-1]["data"]
        assert receipt["kind"] == "delegate_receipt"
        assert "kaboom" in receipt["content"]

    @pytest.mark.asyncio
    async def test_abort_path_sends_receipt(self):
        comm = FakeCommunicator()
        tm = FakeTaskManager(existing={"task-1"})
        m = await make_messenger(communicator=comm, task_manager=tm)
        agent = FakeHandlerAgent(
            m, run_result=ExecutionResult(status=ExecutionStatus.ABORTED)
        )
        await Agent._handle_incoming_delegate(agent, _incoming_delegate_comm("task-1"))
        receipt = comm.sent[-1]["data"]
        assert receipt["kind"] == "delegate_receipt"
        assert "aborted" in receipt["content"]


# ---------------------------------------------------------------------------
# Communicate tool mapping
# ---------------------------------------------------------------------------


def _make_tool_context(messenger) -> ToolCallContext:
    ctx = ToolCallContext()
    agent = type("A", (), {})()
    agent.messenger = messenger
    ctx.agent = agent
    return ctx


class TestCommunicateTool:
    @pytest.mark.asyncio
    async def test_request_success_maps_success(self):
        comm = FakeCommunicator()
        m = await make_messenger(communicator=comm)
        ctx = _make_tool_context(m)
        tool = Communicate()

        coro = tool._execute(
            {"target": "B", "mode": "request", "message": "hi"}, ctx
        )
        task = asyncio.create_task(coro)
        await _wait_until(lambda: len(m._pending_requests) == 1)
        rid = next(iter(m._pending_requests))
        await m.handle_request_response(_reply_message(rid, "answer"))
        result = await asyncio.wait_for(task, timeout=1)
        assert result.status == ToolStatus.SUCCESS
        assert "answer" in result.content

    @pytest.mark.asyncio
    async def test_request_error_status_maps_error(self):
        comm = FakeCommunicator()
        m = await make_messenger(communicator=comm)
        ctx = _make_tool_context(m)
        tool = Communicate()
        task = asyncio.create_task(
            tool._execute({"target": "B", "mode": "request", "message": "hi"}, ctx)
        )
        await _wait_until(lambda: len(m._pending_requests) == 1)
        rid = next(iter(m._pending_requests))
        await m.handle_request_response(
            _reply_message(rid, "oops", status="error")
        )
        result = await asyncio.wait_for(task, timeout=1)
        assert result.status == ToolStatus.ERROR
        assert "[status=error]" in result.content

    @pytest.mark.asyncio
    async def test_notify_success_maps_success(self):
        comm = FakeCommunicator()
        m = await make_messenger(communicator=comm)
        result = await Communicate()._execute(
            {"target": "B", "mode": "notify", "message": "hi"},
            _make_tool_context(m),
        )
        assert result.status == ToolStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_delegate_success_maps_success(self):
        comm = FakeCommunicator()
        tm = FakeTaskManager(existing={"task-1"})
        m = await make_messenger(communicator=comm, task_manager=tm)
        result = await Communicate()._execute(
            {
                "target": "B",
                "mode": "delegate",
                "message": "do it",
                "task_id": "task-1",
            },
            _make_tool_context(m),
        )
        assert result.status == ToolStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_routing_failed_maps_error(self):
        comm = FakeCommunicator(ack={"status": "routing_failed", "reason": "offline"})
        m = await make_messenger(communicator=comm)
        result = await Communicate()._execute(
            {"target": "B", "mode": "notify", "message": "hi"},
            _make_tool_context(m),
        )
        assert result.status == ToolStatus.ERROR
        assert "routing_failed" in result.content

    @pytest.mark.asyncio
    async def test_delegate_routing_failed_not_false_success(self):
        comm = FakeCommunicator(ack={"status": "routing_failed", "reason": "offline"})
        tm = FakeTaskManager(existing={"task-1"})
        m = await make_messenger(communicator=comm, task_manager=tm)
        result = await Communicate()._execute(
            {"target": "B", "mode": "delegate", "message": "x", "task_id": "task-1"},
            _make_tool_context(m),
        )
        assert result.status == ToolStatus.ERROR  # never a false SUCCESS

    @pytest.mark.asyncio
    async def test_unknown_mode_errors(self):
        m = await make_messenger()
        result = await Communicate()._execute(
            {"target": "B", "mode": "bogus", "message": "hi"}, _make_tool_context(m)
        )
        assert result.status == ToolStatus.ERROR

    @pytest.mark.asyncio
    async def test_messenger_none_errors(self):
        result = await Communicate()._execute(
            {"target": "B", "mode": "notify", "message": "hi"},
            _make_tool_context(None),
        )
        assert result.status == ToolStatus.ERROR


# ---------------------------------------------------------------------------
# Agent.run() chain entry + mid-turn drain (real methods, fake self)
# ---------------------------------------------------------------------------


class _FakeUndoStack:
    def clear(self):
        pass


class _FakeRevertService:
    def __init__(self):
        self.undo_stack = _FakeUndoStack()


class _FakeEngine:
    def __init__(self):
        self.executed = None
        self.execute_kwargs = None

    async def execute(self, message, max_steps, from_agent, **kwargs):
        self.executed = message
        self.execute_kwargs = kwargs
        return ExecutionResult(status=ExecutionStatus.COMPLETED, message="ok")


class FakeRunAgent:
    """Minimal object exposing what ``Agent.run()`` touches."""

    STATUS_RUNNING = "running"
    STATUS_IDLE = "idle"

    def __init__(self, messenger, agent_id="A", execution_mode="non_blocking"):
        self.agent_id = agent_id
        self.messenger = messenger
        self._run_lock = asyncio.Lock()
        self._abort_task = None
        self.revert_service = _FakeRevertService()
        self.execution_engine = _FakeEngine()
        self.message_queue = asyncio.Queue()
        self._make_message_source = lambda: Agent._make_message_source(self)
        execution_config = type("EC", (), {"execution_mode": execution_mode})()
        self.config = type(
            "C", (), {"save_history": True, "execution_config": execution_config}
        )()
        self._status = None

    async def _set_status(self, status):
        self._status = status


class TestRunChainEntry:
    @pytest.mark.asyncio
    async def test_top_level_originator_enters_chain(self):
        m = await make_messenger(agent_id="A", name="A")
        fake = FakeRunAgent(m, agent_id="A")
        msg = MessageProtocol.create_user_message("hello")
        await Agent.run(fake, msg, call_chain=None)
        # Top-level (call_chain=None) must still put own id into the chain.
        assert "A" in m._call_chain.agent_ids

    @pytest.mark.asyncio
    async def test_inbound_chain_is_extended_with_self(self):
        m = await make_messenger(agent_id="B", name="B")
        fake = FakeRunAgent(m, agent_id="B")
        msg = MessageProtocol.create_user_message("hi")
        await Agent.run(fake, msg, call_chain=CallChain(agent_ids=["A"]))
        assert m._call_chain.agent_ids == ["A", "B"]

    @pytest.mark.asyncio
    async def test_agent_initiated_turn_auto_attaches_message_source(self):
        """request/delegate/notify 触发的 turn 也要能在 step 之间注入回执。"""
        m = await make_messenger(agent_id="A", name="A")
        fake = FakeRunAgent(m, agent_id="A")
        receipt = Message(
            message_type=MessageType.AGENT_NOTIFY,
            role="agent",
            data={
                "source_agent": "B",
                "kind": "delegate_receipt",
                "task_id": "t-1",
                "content": "done",
            },
        )
        fake.message_queue.put_nowait(receipt)

        msg = MessageProtocol.create_user_message("hi")
        await Agent.run(fake, msg, from_agent=True)

        source = fake.execution_engine.execute_kwargs["message_source"]
        assert source is not None
        assert await source.drain() == [receipt]

    @pytest.mark.asyncio
    async def test_blocking_mode_keeps_no_message_source(self):
        m = await make_messenger(agent_id="A", name="A")
        fake = FakeRunAgent(m, agent_id="A", execution_mode="blocking")
        msg = MessageProtocol.create_user_message("hi")
        await Agent.run(fake, msg)

        assert fake.execution_engine.execute_kwargs["message_source"] is None

    @pytest.mark.asyncio
    async def test_explicit_message_source_is_not_overridden(self):
        m = await make_messenger(agent_id="A", name="A")
        fake = FakeRunAgent(m, agent_id="A")
        explicit = MagicMock()
        msg = MessageProtocol.create_user_message("hi")
        await Agent.run(fake, msg, message_source=explicit)

        assert fake.execution_engine.execute_kwargs["message_source"] is explicit


class TestMidTurnDrain:
    @pytest.mark.asyncio
    async def test_message_source_drains_agent_notify(self):
        m = await make_messenger()
        fake = FakeRunAgent(m)
        fake.message_queue = asyncio.Queue()
        notify = Message(
            message_type=MessageType.AGENT_NOTIFY,
            role="agent",
            content="n",
            data={"source_agent": "B"},
        )
        fake.message_queue.put_nowait(notify)

        source = Agent._make_message_source(fake)
        drained = await source.drain()
        assert len(drained) == 1
        assert drained[0].message_type == MessageType.AGENT_NOTIFY

    @pytest.mark.asyncio
    async def test_initial_drain_includes_agent_notify(self):
        m = await make_messenger()
        fake = FakeRunAgent(m)
        fake.message_queue = asyncio.Queue()
        first = Message(
            message_type=MessageType.USER_MESSAGE, role="user", content="u", data={}
        )
        notify = Message(
            message_type=MessageType.AGENT_NOTIFY, role="agent", content="n", data={}
        )
        fake.message_queue.put_nowait(notify)
        drained = Agent._drain_user_messages(fake, first)
        types = {msg.message_type for msg in drained}
        assert MessageType.USER_MESSAGE in types
        assert MessageType.AGENT_NOTIFY in types


class TestReceiveMessageEnqueues:
    @pytest.mark.asyncio
    async def test_receive_message_enqueues_agent_notify(self):
        m = await make_messenger()
        fake = FakeRunAgent(m)
        fake.message_queue = asyncio.Queue()
        fake._seen_message_ids = set()
        fake._DEDUP_MAX_SIZE = 1000
        notify = Message(
            message_type=MessageType.AGENT_NOTIFY,
            role="agent",
            content="n",
            data={"source_agent": "B"},
        )
        await Agent._receive_message(fake, notify)
        assert fake.message_queue.qsize() == 1


# ---------------------------------------------------------------------------
# Global invariants
# ---------------------------------------------------------------------------


class TestGlobalInvariants:
    def test_no_agent_delegate_response_type(self):
        assert not hasattr(MessageType, "AGENT_DELEGATE_RESPONSE")

    def test_request_response_type_exists(self):
        assert MessageType.AGENT_REQUEST_RESPONSE.value == "agent_request_response"

    def test_send_type_map_has_no_delegate_response(self):
        mapping = SocketIOClient._SEND_TYPE_BY_MODE
        assert MessageType.AGENT_DELEGATE in mapping.values()
        assert "AGENT_DELEGATE_RESPONSE" not in mapping
