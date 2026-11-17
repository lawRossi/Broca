"""Default AgentMessenger implementation.

Implements the three interaction modes (request / notify / delegate) plus
reply / handle_request_response on top of the unified SocketIO transport.

Control mechanisms (always on):

- static ACL (``allowed_targets`` / ``allowed_modes``)
- self-target guard (an agent may never message itself)
- delegate task-existence pre-check
- reply guarantee (caller-side try/finally, see ``Agent._handle_incoming_request``)
- request timeout
- request forced cycle detection (deadlock prevention)

Optional enhancements (per-turn budget, notify/delegate chain detection) are
**not** implemented in this iteration per user request — no ``_budget`` here.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass

from broca.agent_configs import CommunicationPolicy
from broca.agent_messenger.audit import AuditLogger, CommunicationEvent, now_iso
from broca.agent_messenger.call_chain import CallChain
from broca.agent_messenger.message_models import AgentCommunication
from broca.components.agent_messenger import AgentMessenger


class AgentCommunicationError(Exception):
    """Raised on agent-to-agent communication failures.

    ``reason`` is one of: task_id_required / task_not_found / target_not_found /
    acl_denied / self_target / chain_cycle / chain_depth_exceeded /
    request_timeout / routing_failed.
    """

    def __init__(self, message: str, reason: str | None = None):
        super().__init__(message)
        self.reason = reason


@dataclass
class _PendingRequest:
    """Bookkeeping for an outstanding ``request`` awaiting its reply."""

    event: asyncio.Event
    target_name: str
    started_at: float
    reply: str = ""
    status: str = "success"


class DefaultAgentMessenger(AgentMessenger):
    """Default messenger backed by the SocketIO communicator."""

    def __init__(self):
        self.agent_id = ""
        self.name = ""
        self.session_id = ""
        self.communicator = None
        self._agent_factory = None
        self._task_manager = None
        self._config: CommunicationPolicy = CommunicationPolicy()
        self._call_chain = CallChain()
        self._audit: AuditLogger | None = None
        self._pending_requests: dict[str, _PendingRequest] = {}
        self._lock = asyncio.Lock()

    async def initialize(
        self,
        agent_id,
        name,
        session_id,
        communicator,
        agent_factory,
        task_manager=None,
        config=None,
    ) -> None:
        self.agent_id = agent_id
        self.name = name
        self.session_id = session_id
        self.communicator = communicator
        self._agent_factory = agent_factory
        self._task_manager = task_manager
        self._config = (
            config.communication_policy
            if config is not None
            else CommunicationPolicy()
        )
        self._audit = AuditLogger(config.workspace if config is not None else "")

    # ------------------------------------------------------------------ request
    async def request(self, target_name, message):
        """Synchronous request (ask_user-style): deliver → block → return reply."""
        started = time.monotonic()
        request_id = uuid.uuid4().hex[:16]
        chain_depth = self._call_chain.depth
        final_result = "routing_failed"
        rejection_reason = None
        try:
            try:
                target_id = self._resolve_agent_id(target_name)
            except AgentCommunicationError as e:
                final_result = "rejected"
                rejection_reason = e.reason
                raise
            ok, reason = self._check_permissions(target_name, target_id, "request")
            if not ok:
                final_result = "rejected"
                rejection_reason = reason
                raise AgentCommunicationError(
                    f"Request to '{target_name}' rejected: {reason}", reason=reason
                )

            event = asyncio.Event()
            async with self._lock:
                self._pending_requests[request_id] = _PendingRequest(
                    event=event, target_name=target_name, started_at=started
                )

            comm = AgentCommunication(
                source_agent=self.name,
                target_agent=target_name,
                mode="request",
                content=message,
                request_id=request_id,
                call_chain=self._call_chain.to_dict(),
            )
            try:
                # 1. Deliver (routing_failed ACK → fast-fail before waiting).
                await self._send_and_check_ack(comm, target_id)
                final_result = "routed"

                # 2. Block until the reply arrives (pairing by request_id).
                try:
                    await asyncio.wait_for(
                        event.wait(), timeout=self._config.request_timeout
                    )
                except asyncio.TimeoutError:
                    final_result = "timeout"
                    raise AgentCommunicationError(
                        f"Request {request_id} to '{target_name}' timed out",
                        reason="request_timeout",
                    )

                # 3. Read reply text + status.
                async with self._lock:
                    pending = self._pending_requests[request_id]
                    reply, reply_status = pending.reply, pending.status
                final_result = "replied"
                return reply, reply_status
            finally:
                async with self._lock:
                    self._pending_requests.pop(request_id, None)
        finally:
            self._log_audit(
                target_agent=target_name,
                mode="request",
                message_summary=message[:200],
                request_id=request_id,
                result=final_result,
                rejection_reason=rejection_reason,
                call_depth=chain_depth,
                duration_ms=(time.monotonic() - started) * 1000,
            )

    # -------------------------------------------------------------------- reply
    async def reply(self, request_id, target_name, content, status="success"):
        """Reply to a request (receiver side); sends AGENT_REQUEST_RESPONSE.

        **Best-effort, never raises**: the requester may already have timed out
        or gone offline, so both an unresolvable target (``target_not_found``)
        and a ``routing_failed`` ACK are *not* raised here — they are only
        audited.  ``Agent._handle_incoming_request`` relies on this contract
        (it must guarantee a reply attempt without masking its own result).
        """
        chain_depth = self._call_chain.depth
        try:
            target_id = self._resolve_agent_id(target_name)
        except AgentCommunicationError as e:
            # Requester already gone — audit and give up (best-effort).
            self._log_audit(
                target_agent=target_name,
                mode="request_reply",
                message_summary=content[:200],
                request_id=request_id,
                result="routing_failed",
                rejection_reason=e.reason,
                call_depth=chain_depth,
                duration_ms=0.0,
            )
            return
        comm = AgentCommunication(
            source_agent=self.name,
            target_agent=target_name,
            mode="request_reply",
            content=content,
            request_id=request_id,
            status=status,
            call_chain=self._call_chain.to_dict(),
        )
        result = await self.communicator.send(
            content=content, data=comm.to_dict(), receiver_id=target_id
        )
        ok = bool(result) and result.get("status") == "routed"
        self._log_audit(
            target_agent=target_name,
            mode="request_reply",
            message_summary=content[:200],
            request_id=request_id,
            result="replied" if ok else "routing_failed",
            call_depth=chain_depth,
            duration_ms=0.0,
        )

    async def handle_request_response(self, message):
        """Invoked by the ``agent_request_response`` event handler directly."""
        data = message.data or {}
        request_id = data.get("request_id")
        if not request_id:
            return
        async with self._lock:
            pending = self._pending_requests.get(request_id)
            if pending is None:
                # Late reply after timeout/abort — ignore.
                return
            # Reply text lives in message.data["content"] (Message has no
            # ``content`` attribute — content is stored in the ``data`` dict).
            pending.reply = (message.data or {}).get("content", "")
            pending.status = data.get("status", "success")
            pending.event.set()

    # ------------------------------------------------------------------- notify
    async def notify(self, target_name, message, task_id=None, kind="notify"):
        """Wait for ACK, do not wait for a business receipt.

        Delegate receipts also route through here (``kind="delegate_receipt"``).
        """
        started = time.monotonic()
        chain_depth = self._call_chain.depth
        final_result = "routing_failed"
        rejection_reason = None
        try:
            try:
                target_id = self._resolve_agent_id(target_name)
            except AgentCommunicationError as e:
                final_result = "rejected"
                rejection_reason = e.reason
                raise
            ok, reason = self._check_permissions(target_name, target_id, "notify")
            if not ok:
                final_result = "rejected"
                rejection_reason = reason
                raise AgentCommunicationError(
                    f"Notify to '{target_name}' rejected: {reason}", reason=reason
                )
            comm = AgentCommunication(
                source_agent=self.name,
                target_agent=target_name,
                mode="notify",
                content=message,
                task_id=task_id,
                kind=kind,
                call_chain=self._call_chain.to_dict(),
            )
            await self._send_and_check_ack(comm, target_id)
            final_result = "routed"
        finally:
            self._log_audit(
                target_agent=target_name,
                mode="notify",
                message_summary=message[:200],
                task_id=task_id,
                kind=kind,
                result=final_result,
                rejection_reason=rejection_reason,
                call_depth=chain_depth,
                duration_ms=(time.monotonic() - started) * 1000,
            )

    # ----------------------------------------------------------------- delegate
    async def delegate(self, target_name, task_id, message):
        """Wait for ACK, do not wait for a receipt; ``task_id`` must exist."""
        started = time.monotonic()
        chain_depth = self._call_chain.depth
        final_result = "routing_failed"
        rejection_reason = None
        try:
            ok, reason = await self._check_task_exists(task_id)
            if not ok:
                final_result = "rejected"
                rejection_reason = reason
                raise AgentCommunicationError(
                    f"Delegate failed: {reason}", reason=reason
                )
            try:
                target_id = self._resolve_agent_id(target_name)
            except AgentCommunicationError as e:
                final_result = "rejected"
                rejection_reason = e.reason
                raise
            ok, reason = self._check_permissions(target_name, target_id, "delegate")
            if not ok:
                final_result = "rejected"
                rejection_reason = reason
                raise AgentCommunicationError(
                    f"Delegate to '{target_name}' rejected: {reason}", reason=reason
                )
            comm = AgentCommunication(
                source_agent=self.name,
                target_agent=target_name,
                mode="delegate",
                content=message,
                task_id=task_id,
                call_chain=self._call_chain.to_dict(),
            )
            await self._send_and_check_ack(comm, target_id)
            final_result = "routed"
        finally:
            self._log_audit(
                target_agent=target_name,
                mode="delegate",
                message_summary=message[:200],
                task_id=task_id,
                result=final_result,
                rejection_reason=rejection_reason,
                call_depth=chain_depth,
                duration_ms=(time.monotonic() - started) * 1000,
            )

    # ------------------------------------------------------------- validators
    async def _check_task_exists(self, task_id):
        if not task_id:
            return False, "task_id_required"
        if self._task_manager is None:
            # No task manager wired — the "task must exist" hard constraint
            # cannot be verified, so fail closed.  Production always wires one
            # (``Agent.create`` passes ``TaskManager()``); this only affects
            # embedded/test contexts that deliberately omit it.
            return False, "task_not_found"
        if await self._task_manager.get_task(task_id) is None:
            return False, "task_not_found"
        return True, None

    def _check_permissions(self, target_name, target_id, mode):
        """Self-target guard + ACL + request forced cycle detection.

        No budget / no optional chain (skipped per user request).
        """
        # Core: never message yourself.  A self ``request`` would block forever
        # waiting on its own reply (deadlock); self ``notify``/``delegate`` would
        # loop the agent's own message queue.  Reject up front.
        if target_id and target_id == self.agent_id:
            return False, "self_target"
        # Core: static ACL.
        if (
            self._config.allowed_targets is not None
            and target_name not in self._config.allowed_targets
        ):
            return False, "acl_denied"
        if (
            self._config.allowed_modes is not None
            and mode not in self._config.allowed_modes
        ):
            return False, "acl_denied"
        # Core: request forced cycle detection (deadlock prevention).
        if mode == "request":
            if self._call_chain.would_create_cycle(target_id):
                return False, "chain_cycle"
            if not self._call_chain.is_within_depth(self._config.max_chain_depth):
                return False, "chain_depth_exceeded"
        return True, None

    async def _send_and_check_ack(self, comm, target_id):
        result = await self.communicator.send(
            content=comm.content, data=comm.to_dict(), receiver_id=target_id
        )
        # Whitelist the ACK: only an explicit ``routed`` counts as success, so a
        # falsy / status-less ACK (e.g. a ``None``-returning Communicator) fails
        # the same way as ``routing_failed`` instead of silently "succeeding".
        if not result or result.get("status") != "routed":
            reason = (result or {}).get("reason") or "routing_failed"
            raise AgentCommunicationError(
                f"Agent unreachable: {reason}", reason="routing_failed"
            )

    def _resolve_agent_id(self, target_name):
        """Sync: DefaultAgentFactory.get_agent is a sync ``def`` (no await)."""
        target = self._agent_factory.get_agent(self.session_id, target_name)
        if target is None:
            raise AgentCommunicationError(
                f"Agent '{target_name}' not found in session",
                reason="target_not_found",
            )
        return target.agent_id

    # ------------------------------------------------------------- lifecycle
    def set_call_chain(self, chain: CallChain) -> None:
        self._call_chain = chain

    def reset_budget(self) -> None:
        # No budget in this iteration (optional enhancement skipped) — no-op.
        return None

    # --------------------------------------------------------------- helpers
    def _log_audit(
        self,
        *,
        target_agent: str,
        mode: str,
        message_summary: str,
        result: str,
        duration_ms: float,
        request_id: str = "",
        task_id: str | None = None,
        kind: str = "notify",
        rejection_reason: str | None = None,
        call_depth: int | None = None,
    ) -> None:
        if self._audit is None:
            return
        self._audit.log(
            CommunicationEvent(
                timestamp=now_iso(),
                source_agent=self.name,
                target_agent=target_agent,
                mode=mode,
                message_summary=message_summary,
                task_id=task_id,
                kind=kind,
                request_id=request_id,
                result=result,
                rejection_reason=rejection_reason,
                call_depth=(
                    self._call_chain.depth if call_depth is None else call_depth
                ),
                duration_ms=duration_ms,
            )
        )
