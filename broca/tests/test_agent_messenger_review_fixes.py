"""Regression tests for the AgentMessenger code-review fixes.

Covers:

- M1: rejection paths now write an audit line with ``result="rejected"`` and a
  populated ``rejection_reason`` (ACL / chain / task / target-not-found).
- M2: ``reply()`` is truly best-effort — an unresolvable target is audited, not
  raised (the requester may already be gone).
- L2: ``delegate()`` fails closed when no task manager is wired.
- L3: a falsy / status-less ACK is treated as a delivery failure (whitelist),
  matching ``routing_failed`` for request / notify / delegate.
- L4: audit ``call_depth`` is a snapshot taken at send time.
- L5: ``from_message_data`` tolerates malformed payloads (no ``KeyError``).
"""

from __future__ import annotations

import json
import os

import pytest

from broca.agent_configs import CommunicationPolicy
from broca.agent_messenger.call_chain import CallChain
from broca.agent_messenger.message_models import AgentCommunication
from broca.agent_messenger.messenger import AgentCommunicationError
from broca.tests.test_agent_messenger_core import (
    FakeAgentFactory,
    FakeCommunicator,
    FakeTaskManager,
    make_messenger,
)

AUDIT_REL = os.path.join(".broca", "agent_messenger_audit.jsonl")

# asyncio_mode = STRICT in pyproject → mark the whole module async.
pytestmark = pytest.mark.asyncio


def _read_audit(workspace) -> list[dict]:
    path = os.path.join(str(workspace), AUDIT_REL)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# ---------------------------------------------------------------------------
# M1 — rejection paths are audited
# ---------------------------------------------------------------------------


class TestRejectionAudit:
    async def test_request_acl_denied_is_audited(self, tmp_path):
        policy = CommunicationPolicy(allowed_targets=set())
        m = await make_messenger(policy=policy, workspace=str(tmp_path))
        with pytest.raises(AgentCommunicationError) as ei:
            await m.request("B", "hi")
        assert ei.value.reason == "acl_denied"

        lines = _read_audit(tmp_path)
        assert len(lines) == 1
        assert lines[0]["mode"] == "request"
        assert lines[0]["result"] == "rejected"
        assert lines[0]["rejection_reason"] == "acl_denied"

    async def test_request_target_not_found_is_audited(self, tmp_path):
        m = await make_messenger(
            factory=FakeAgentFactory({}), workspace=str(tmp_path)
        )
        with pytest.raises(AgentCommunicationError) as ei:
            await m.request("B", "hi")
        assert ei.value.reason == "target_not_found"

        lines = _read_audit(tmp_path)
        assert len(lines) == 1
        assert lines[0]["result"] == "rejected"
        assert lines[0]["rejection_reason"] == "target_not_found"

    async def test_request_chain_cycle_is_audited(self, tmp_path):
        m = await make_messenger(workspace=str(tmp_path))
        # Target agent id "B" already in the chain → cycle.
        m.set_call_chain(CallChain(agent_ids=["A", "B"]))
        with pytest.raises(AgentCommunicationError) as ei:
            await m.request("B", "hi")
        assert ei.value.reason == "chain_cycle"

        lines = _read_audit(tmp_path)
        assert len(lines) == 1
        assert lines[0]["result"] == "rejected"
        assert lines[0]["rejection_reason"] == "chain_cycle"

    async def test_notify_acl_denied_is_audited(self, tmp_path):
        policy = CommunicationPolicy(allowed_targets=set())
        m = await make_messenger(policy=policy, workspace=str(tmp_path))
        with pytest.raises(AgentCommunicationError) as ei:
            await m.notify("B", "hey")
        assert ei.value.reason == "acl_denied"

        lines = _read_audit(tmp_path)
        assert len(lines) == 1
        assert lines[0]["mode"] == "notify"
        assert lines[0]["result"] == "rejected"
        assert lines[0]["rejection_reason"] == "acl_denied"

    async def test_delegate_task_id_required_is_audited(self, tmp_path):
        tm = FakeTaskManager(existing={"task-1"})
        m = await make_messenger(task_manager=tm, workspace=str(tmp_path))
        with pytest.raises(AgentCommunicationError) as ei:
            await m.delegate("B", "", "do it")
        assert ei.value.reason == "task_id_required"

        lines = _read_audit(tmp_path)
        assert len(lines) == 1
        assert lines[0]["mode"] == "delegate"
        assert lines[0]["result"] == "rejected"
        assert lines[0]["rejection_reason"] == "task_id_required"

    async def test_delegate_task_not_found_is_audited(self, tmp_path):
        tm = FakeTaskManager(existing=set())
        m = await make_messenger(task_manager=tm, workspace=str(tmp_path))
        with pytest.raises(AgentCommunicationError) as ei:
            await m.delegate("B", "missing", "do it")
        assert ei.value.reason == "task_not_found"

        lines = _read_audit(tmp_path)
        assert len(lines) == 1
        assert lines[0]["result"] == "rejected"
        assert lines[0]["rejection_reason"] == "task_not_found"

    async def test_delegate_target_not_found_is_audited(self, tmp_path):
        tm = FakeTaskManager(existing={"task-1"})
        m = await make_messenger(
            factory=FakeAgentFactory({}), task_manager=tm, workspace=str(tmp_path)
        )
        with pytest.raises(AgentCommunicationError) as ei:
            await m.delegate("B", "task-1", "do it")
        assert ei.value.reason == "target_not_found"

        lines = _read_audit(tmp_path)
        assert len(lines) == 1
        assert lines[0]["result"] == "rejected"
        assert lines[0]["rejection_reason"] == "target_not_found"

    async def test_successful_send_is_not_marked_rejected(self, tmp_path):
        m = await make_messenger(workspace=str(tmp_path))
        await m.notify("B", "hey")
        lines = _read_audit(tmp_path)
        assert len(lines) == 1
        assert lines[0]["result"] == "routed"
        assert lines[0]["rejection_reason"] is None


# ---------------------------------------------------------------------------
# M2 — reply() is best-effort (never raises on unresolvable target)
# ---------------------------------------------------------------------------


class TestReplyBestEffort:
    async def test_reply_to_missing_target_does_not_raise(self, tmp_path):
        m = await make_messenger(
            factory=FakeAgentFactory({}), workspace=str(tmp_path)
        )
        # Must NOT raise even though target cannot be resolved.
        await m.reply("rid-1", "B", "the answer")

        lines = _read_audit(tmp_path)
        assert len(lines) == 1
        assert lines[0]["mode"] == "request_reply"
        assert lines[0]["result"] == "routing_failed"
        assert lines[0]["rejection_reason"] == "target_not_found"

    async def test_reply_to_resolvable_target_sends(self, tmp_path):
        comm = FakeCommunicator(ack={"status": "routed"})
        m = await make_messenger(communicator=comm, workspace=str(tmp_path))
        await m.reply("rid-2", "B", "ok")
        assert len(comm.sent) == 1
        assert comm.sent[0]["data"]["mode"] == "request_reply"
        lines = _read_audit(tmp_path)
        assert lines[0]["result"] == "replied"


# ---------------------------------------------------------------------------
# L2 — delegate fails closed without a task manager
# ---------------------------------------------------------------------------


class TestDelegateFailsClosed:
    async def test_delegate_without_task_manager_rejected(self, tmp_path):
        m = await make_messenger(task_manager=None, workspace=str(tmp_path))
        with pytest.raises(AgentCommunicationError) as ei:
            await m.delegate("B", "task-1", "do it")
        assert ei.value.reason == "task_not_found"


# ---------------------------------------------------------------------------
# L3 — falsy / status-less ACK is treated as failure (whitelist)
# ---------------------------------------------------------------------------


class TestFalsyAckFails:
    async def test_request_empty_ack_fails(self, tmp_path):
        comm = FakeCommunicator(ack={})
        m = await make_messenger(communicator=comm, workspace=str(tmp_path))
        with pytest.raises(AgentCommunicationError) as ei:
            await m.request("B", "hi")
        assert ei.value.reason == "routing_failed"

    async def test_notify_empty_ack_fails(self, tmp_path):
        comm = FakeCommunicator(ack={})
        m = await make_messenger(communicator=comm, workspace=str(tmp_path))
        with pytest.raises(AgentCommunicationError) as ei:
            await m.notify("B", "hi")
        assert ei.value.reason == "routing_failed"

    async def test_delegate_empty_ack_fails(self, tmp_path):
        comm = FakeCommunicator(ack={})
        tm = FakeTaskManager(existing={"task-1"})
        m = await make_messenger(
            communicator=comm, task_manager=tm, workspace=str(tmp_path)
        )
        with pytest.raises(AgentCommunicationError) as ei:
            await m.delegate("B", "task-1", "do it")
        assert ei.value.reason == "routing_failed"

    async def test_status_less_ack_fails(self, tmp_path):
        comm = FakeCommunicator(ack={"reason": "weird"})
        m = await make_messenger(communicator=comm, workspace=str(tmp_path))
        with pytest.raises(AgentCommunicationError) as ei:
            await m.notify("B", "hi")
        assert ei.value.reason == "routing_failed"


# ---------------------------------------------------------------------------
# L4 — audit call_depth is a snapshot at send time
# ---------------------------------------------------------------------------


class TestAuditDepthSnapshot:
    async def test_call_depth_recorded_from_send_time(self, tmp_path):
        m = await make_messenger(workspace=str(tmp_path))
        m.set_call_chain(CallChain(agent_ids=["A", "X"]))  # depth 2
        await m.notify("B", "hey")
        lines = _read_audit(tmp_path)
        assert lines[0]["call_depth"] == 2


# ---------------------------------------------------------------------------
# Self-target guard — an agent may never message itself
# ---------------------------------------------------------------------------


class TestSelfTargetGuard:
    async def test_request_to_self_rejected(self, tmp_path):
        # Default make_messenger: agent_id="A", name="A", factory maps A->A.
        m = await make_messenger(workspace=str(tmp_path))
        with pytest.raises(AgentCommunicationError) as ei:
            await m.request("A", "hi")
        assert ei.value.reason == "self_target"

        lines = _read_audit(tmp_path)
        assert len(lines) == 1
        assert lines[0]["mode"] == "request"
        assert lines[0]["result"] == "rejected"
        assert lines[0]["rejection_reason"] == "self_target"

    async def test_notify_to_self_rejected(self, tmp_path):
        m = await make_messenger(workspace=str(tmp_path))
        with pytest.raises(AgentCommunicationError) as ei:
            await m.notify("A", "hey")
        assert ei.value.reason == "self_target"

        lines = _read_audit(tmp_path)
        assert lines[0]["mode"] == "notify"
        assert lines[0]["rejection_reason"] == "self_target"

    async def test_delegate_to_self_rejected(self, tmp_path):
        tm = FakeTaskManager(existing={"task-1"})
        m = await make_messenger(task_manager=tm, workspace=str(tmp_path))
        with pytest.raises(AgentCommunicationError) as ei:
            await m.delegate("A", "task-1", "do it")
        assert ei.value.reason == "self_target"

        lines = _read_audit(tmp_path)
        assert lines[0]["mode"] == "delegate"
        assert lines[0]["rejection_reason"] == "self_target"

    async def test_sending_to_other_agent_still_works(self, tmp_path):
        comm = FakeCommunicator(ack={"status": "routed"})
        m = await make_messenger(communicator=comm, workspace=str(tmp_path))
        await m.notify("B", "hey")  # must NOT be treated as self-target
        assert len(comm.sent) == 1
        assert comm.sent[0]["receiver_id"] == "B"


# ---------------------------------------------------------------------------
# L5 — from_message_data tolerates malformed payloads
# ---------------------------------------------------------------------------


class TestFromMessageDataRobust:
    async def test_empty_data_does_not_raise(self):
        comm = AgentCommunication.from_message_data({})
        assert comm.content == ""
        assert comm.mode == ""
        assert comm.source_agent == ""
        assert comm.target_agent == ""

    async def test_partial_data_uses_defaults(self):
        comm = AgentCommunication.from_message_data({"source_agent": "A"})
        assert comm.source_agent == "A"
        assert comm.content == ""
        assert comm.kind == "notify"
        assert comm.status == "success"

    async def test_none_data_does_not_raise(self):
        comm = AgentCommunication.from_message_data(None)
        assert comm.content == ""
