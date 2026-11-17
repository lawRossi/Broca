"""Unit tests for :class:`AuditLogger` and :class:`CommunicationEvent`.

Audit is best-effort recording (never a control mechanism, never raises).
Each event is written as one JSON line under ``{workspace}/.broca/``.
"""

from __future__ import annotations

import json
import os

from broca.agent_messenger.audit import (
    AuditLogger,
    CommunicationEvent,
    now_iso,
)


def _event(**overrides) -> CommunicationEvent:
    base = dict(
        timestamp=now_iso(),
        source_agent="A",
        target_agent="B",
        mode="request",
        message_summary="hello",
        request_id="r1",
        result="routed",
        call_depth=1,
        duration_ms=12.5,
    )
    base.update(overrides)
    return CommunicationEvent(**base)


class TestNowIso:
    def test_now_iso_is_string(self):
        ts = now_iso()
        assert isinstance(ts, str)
        assert "T" in ts


class TestAuditLoggerWrite:
    def test_log_creates_jsonl_file(self, tmp_path):
        logger = AuditLogger(str(tmp_path))
        logger.log(_event())

        path = os.path.join(str(tmp_path), ".broca", "agent_messenger_audit.jsonl")
        assert os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["source_agent"] == "A"
        assert record["target_agent"] == "B"
        assert record["mode"] == "request"
        assert record["result"] == "routed"

    def test_multiple_events_are_appended(self, tmp_path):
        logger = AuditLogger(str(tmp_path))
        logger.log(_event(request_id="r1"))
        logger.log(_event(request_id="r2"))
        logger.log(_event(request_id="r3"))

        path = os.path.join(str(tmp_path), ".broca", "agent_messenger_audit.jsonl")
        with open(path, encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        assert len(lines) == 3
        assert [r["request_id"] for r in lines] == ["r1", "r2", "r3"]

    def test_event_serializes_all_fields(self, tmp_path):
        logger = AuditLogger(str(tmp_path))
        logger.log(
            _event(
                mode="delegate",
                task_id="task-1",
                kind="delegate_receipt",
                rejection_reason=None,
            )
        )
        path = os.path.join(str(tmp_path), ".broca", "agent_messenger_audit.jsonl")
        with open(path, encoding="utf-8") as f:
            record = json.loads(f.readline())
        assert record["mode"] == "delegate"
        assert record["task_id"] == "task-1"
        assert record["kind"] == "delegate_receipt"
        assert record["call_depth"] == 1
        assert record["duration_ms"] == 12.5


class TestAuditLoggerResilience:
    def test_empty_workspace_does_not_write(self, tmp_path, monkeypatch):
        # Ensure we're not accidentally writing to a real workspace.
        logger = AuditLogger("")
        # Should not raise and should not create anything.
        logger.log(_event())
        assert not os.path.exists(
            os.path.join(str(tmp_path), ".broca", "agent_messenger_audit.jsonl")
        )

    def test_log_never_raises_on_bad_workspace(self):
        # An un-creatable path must be swallowed (audit is best-effort).
        logger = AuditLogger("/proc/definitely/not/writable")
        logger.log(_event())  # must not raise

    def test_uses_workspace_dot_broca_directory(self, tmp_path):
        logger = AuditLogger(str(tmp_path))
        logger.log(_event())
        assert (tmp_path / ".broca").is_dir()
