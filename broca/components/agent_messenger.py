"""AgentMessenger ABC — interface for agent-to-agent communication.

A per-agent component providing three interaction modes:

- ``request``  : ask target to do something, **block** until it replies
                 (ask_user-style sync link; dedicated ``AGENT_REQUEST_RESPONSE``
                 + ``request_id`` pairing + ``asyncio.Event`` + timeout).
- ``notify``   : inform target, no business receipt (fire-and-forget only w.r.t.
                 the receipt) — but still waits for the transport ACK.
- ``delegate`` : assign a pre-existing task (``task_id`` required) to target;
                 target must send a receipt via ``notify(kind="delegate_receipt")``;
                 sender waits for the ACK but **not** for the receipt.

All three modes wait for the transport-layer ACK (``send() -> dict``, <=2s).
An ACK of ``routing_failed`` fast-fails with ``AgentCommunicationError``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from broca.components.base import BaseComponent

if TYPE_CHECKING:
    from broca.agent_configs import AgentConfig
    from broca.agent_messenger.call_chain import CallChain
    from broca.components.agent_factory import AgentFactory
    from broca.components.communicator import Communicator
    from broca.components.task_manager import TaskManager
    from broca.session.models import Message


class AgentMessenger(BaseComponent, ABC):
    """Abstract base class for agent-to-agent messaging."""

    agent_id: str
    session_id: str
    name: str  # agent name (used for message identification)

    @abstractmethod
    async def initialize(
        self,
        agent_id: str,
        name: str,
        session_id: str,
        communicator: "Communicator",
        agent_factory: "AgentFactory",
        task_manager: "TaskManager | None" = None,
        config: "AgentConfig | None" = None,
    ) -> None:
        """Initialize the messenger.

        ``agent_factory`` resolves ``target_name -> agent_id`` (sync ``get_agent``).
        ``task_manager`` is used for delegate's task-existence pre-check.

        ``config`` is an ``AgentConfig`` (**not** a ``CommunicationPolicy``):
        implementations must do ``self._config = config.communication_policy``
        and initialize audit with ``config.workspace``.
        """
        ...

    @abstractmethod
    async def request(
        self, target_name: str, message: str
    ) -> tuple[str, str]:
        """Synchronous request (ask_user-style): block until the reply arrives.

        Pairs via ``request_id`` with a pending ``asyncio.Event``; returns
        ``(reply_text, reply_status)`` where ``status`` ∈ {success, error, aborted}
        so ``Communicate`` can map ``ToolResult`` and the LLM continues in the
        same turn.  Raises ``AgentCommunicationError(reason='request_timeout')``
        on timeout.
        """
        ...

    @abstractmethod
    async def notify(
        self,
        target_name: str,
        message: str,
        task_id: str | None = None,
        kind: str = "notify",
    ) -> None:
        """Send a notification: wait for ACK, do **not** wait for a receipt.

        Raises ``AgentCommunicationError`` when the ACK is ``routing_failed``.
        All notifications/receipts reuse this method:
          - delegate receipt: ``kind="delegate_receipt"`` (with ``task_id``)
        Plain notifications use the default ``kind="notify"``.
        """
        ...

    @abstractmethod
    async def delegate(
        self, target_name: str, task_id: str, message: str
    ) -> None:
        """Delegate the task ``task_id`` to the target agent (task assignment only).

        ``task_id`` must exist (pre-check); waits for ACK (``routing_failed``
        raises, so the delegator knows the task was not handed off); returns
        immediately after ``routed`` — fire-and-forget only w.r.t. the target's
        execution receipt.  The receiver must still send a receipt via ``notify()``.
        """
        ...

    @abstractmethod
    async def reply(
        self, request_id: str, target_name: str, content: str, status: str = "success"
    ) -> None:
        """Reply to a request (called by the receiver); sends ``AGENT_REQUEST_RESPONSE``.

        ``request_id`` must match the received ``AGENT_REQUEST`` so the requester
        can pair and wake its ``Event``.  ``status``: success / error / aborted.
        """
        ...

    @abstractmethod
    async def handle_request_response(self, message: "Message") -> None:
        """Invoked directly by the ``agent_request_response`` event handler.

        Bypasses ``message_queue`` (like ask_user's ``handle_user_answer``).
        Finds the pending request by ``message.data['request_id']``, stores the
        reply and calls ``event.set()``.
        """
        ...

    @abstractmethod
    def set_call_chain(self, chain: "CallChain") -> None:
        """Set the current call chain (from ``Agent.run()`` entry)."""
        ...

    @abstractmethod
    def reset_budget(self) -> None:
        """Reset the per-turn communication budget (from ``Agent.run()`` entry)."""
        ...
