"""Audit logging for agent-to-agent communication.

Audit is **not** a control mechanism — it only records.  It is always on:
every request / reply / notify / delegate attempt produces a JSONL line.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone


def now_iso() -> str:
    """Current time as an ISO-8601 UTC string."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CommunicationEvent:
    """A single audited communication attempt."""

    timestamp: str
    source_agent: str
    target_agent: str
    mode: str  # "request" | "request_reply" | "notify" | "delegate"
    message_summary: str  # truncated to 200 chars
    task_id: str | None = None
    kind: str = "notify"
    request_id: str = ""
    # routed / replied / rejected / timeout / routing_failed
    result: str = ""
    call_depth: int = 0
    duration_ms: float = 0.0
    rejection_reason: str | None = None


class AuditLogger:
    """Append-only JSONL audit logger under ``{workspace}/.broca/``."""

    FILENAME = "agent_messenger_audit.jsonl"

    def __init__(self, workspace: str):
        self.workspace = workspace or ""

    def _path(self) -> str | None:
        if not self.workspace:
            return None
        directory = os.path.join(self.workspace, ".broca")
        return os.path.join(directory, self.FILENAME)

    def log(self, event: CommunicationEvent) -> None:
        """Append one event as a JSON line. Never raises (audit is best-effort)."""
        path = self._path()
        if path is None:
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
        except Exception:
            # Audit must never break the communication path.
            pass
