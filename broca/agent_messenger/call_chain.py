"""CallChain — track the chain of agents a message has traversed.

Used for cycle detection:

- ``request``: **always** used to prevent blocking deadlocks (A waits on B, B
  requests A back → detect and reject before delivery).
- ``notify`` / ``delegate``: optional anti-flooding guard (disabled in this
  iteration per user request).

The chain travels with the message: each hop appends its own ``agent_id``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CallChain:
    """Track the agent chain of a forwarded message."""

    agent_ids: list[str] = field(default_factory=list)

    @property
    def depth(self) -> int:
        return len(self.agent_ids)

    def would_create_cycle(self, target_agent_id: str) -> bool:
        return target_agent_id in self.agent_ids

    def is_within_depth(self, max_depth: int) -> bool:
        return len(self.agent_ids) < max_depth

    def add(self, agent_id: str) -> "CallChain":
        return CallChain(agent_ids=self.agent_ids + [agent_id])

    def to_dict(self) -> dict:
        return {"agent_ids": list(self.agent_ids)}

    @classmethod
    def from_dict(cls, data: dict | None) -> "CallChain":
        if not data:
            return cls()
        return cls(agent_ids=data.get("agent_ids", []))

    def describe(self) -> str:
        return " → ".join(self.agent_ids) if self.agent_ids else "(empty)"
