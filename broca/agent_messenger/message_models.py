"""Data model shared by all agent-to-agent communication modes.

A single :class:`AgentCommunication` dataclass is reused for ``request`` /
``request_reply`` / ``notify`` / ``delegate`` — the payload shape is identical
and the mode discriminates the semantics.  There is intentionally **no**
``AgentRequestResponse`` dataclass: a request reply is just an
``AgentCommunication(mode="request_reply", request_id=..., content=<reply>)``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass
class AgentCommunication:
    """Payload for agent-to-agent messages (serialized into ``Message.data``)."""

    source_agent: str
    target_agent: str
    mode: str  # "request" | "request_reply" | "notify" | "delegate"
    content: str
    task_id: str | None = None  # delegate 投递 + delegate 回执携带
    kind: str = "notify"  # 仅 AGENT_NOTIFY 用："notify" | "delegate_receipt"
    request_id: str = field(
        default_factory=lambda: uuid.uuid4().hex[:16]
    )  # request / request_reply 配对
    status: str = "success"  # 仅 request_reply：success / error / aborted（审计用）
    call_chain: dict = field(default_factory=dict)  # CallChain.to_dict()

    def to_dict(self) -> dict:
        return {
            "source_agent": self.source_agent,
            "target_agent": self.target_agent,
            "mode": self.mode,
            "content": self.content,
            "task_id": self.task_id,
            "kind": self.kind,
            "request_id": self.request_id,
            "status": self.status,
            "call_chain": self.call_chain,
        }

    @classmethod
    def from_message_data(cls, data: dict) -> "AgentCommunication":
        """Deserialize from ``Message.data`` (called on the target side after routing).

        Uses ``.get`` with defaults so a malformed / truncated payload does not
        raise ``KeyError`` (which would silently drop the message in the agent
        message loop); a request with missing ``content`` simply gets an empty
        reply instead of stalling the sender to timeout.
        """
        data = data or {}
        return cls(
            source_agent=data.get("source_agent", ""),
            target_agent=data.get("target_agent", ""),
            mode=data.get("mode", ""),
            content=data.get("content", ""),
            task_id=data.get("task_id"),
            kind=data.get("kind", "notify"),
            request_id=data.get("request_id", ""),
            status=data.get("status", "success"),
            call_chain=data.get("call_chain", {}),
        )
