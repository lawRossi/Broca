#!/usr/bin/env python3
"""Loop engine micro-benchmarks (Phase 5 / Task 5.3).

Compares the legacy monolithic engine (``broca.loop_engine.legacy``) with the
refactored orchestrator (``broca.loop_engine.engine`` + strategies + hooks).

Benchmarks
----------
``execute_round``   one full round: 1 step, 3 streamed chunks, no tool calls
``llm_call``        one LLM call with 3 streamed chunks (retry path, no retry)
``parallel_tools``  10 mock tool calls executed in parallel
``hook_dispatch``   one ``_dispatch`` call with the 4 default hooks

Method mapping between the two implementations (they no longer share private
method names — the LLM/tool policies moved into the strategy layer):

========================================  ==========================================
legacy                                    refactored
========================================  ==========================================
``engine.execute_round(1)``               ``engine._execute_round(turn_ctx, 1)``
``engine._call_llm_with_retry()``         ``RetryLLMStrategy.call(...)``
``engine._process_tool_calls_parallel()`` ``ParallelToolStrategy.execute(...)``
``engine._broadcast_step_message()``      ``engine._dispatch(method, ctx)``
========================================  ==========================================

Usage::

    PYTHONPATH=. python scripts/perf/loop_engine_bench.py --impl legacy \
        --out reports/perf/loop-engine-baseline.json
    PYTHONPATH=. python scripts/perf/loop_engine_bench.py --impl new \
        --out reports/perf/loop-engine-after.json

``--impl legacy`` requires ``broca/loop_engine/legacy.py``, which Phase 5
deleted.  The baseline was captured **before** that deletion and is committed
as ``reports/perf/loop-engine-baseline.json``; re-running the legacy side now
exits with a pointer to that file instead of an ``ImportError`` (review m5).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List

# ── Tunables (plan Task 5.3: 10 measured iterations per benchmark) ──────
ITERATIONS = 10
WARMUP = 3
TOOL_COUNT = 10
DISPATCH_ITERATIONS = 2000

CHUNKS: List[Dict[str, Any]] = [
    {"type": "content", "data": "hello"},
    {"type": "content", "data": " world"},
    {"type": "reasoning_content", "data": "thinking"},
]


# ── Fakes ───────────────────────────────────────────────────────────────


class FakeLLMClient:
    """Streams :data:`CHUNKS` and aggregates them into a tool-call-free message."""

    input_tokens_used = 10
    output_tokens_used = 5

    def __init__(self) -> None:
        self.stream_calls = 0

    async def get_stream_response(self, provider, model, history, tools):
        self.stream_calls += 1
        for chunk in CHUNKS:
            yield chunk

    def aggregate_message(self, content_chunks, tool_call_chunks):
        text = "".join(c.get("data", "") for c in content_chunks)
        return SimpleNamespace(content=text, tool_calls=[], message_id="msg-bench")


class FakeAgentRef:
    agent_id = "agent-bench"
    turn_id = None
    persistent_memory_manager = None

    def __init__(self) -> None:
        self.token_reports = 0

    async def on_llm_call_completed(self, input_tokens, output_tokens):
        self.token_reports += 1


class FakeSessionManager:
    session_id = "session-bench"

    async def create_session(self, workspace=None):
        return self.session_id

    async def start_turn(self, agent_id):
        return "turn-bench"

    async def save_message(self, **kwargs):
        return True

    async def save_agent_response(self, *args, **kwargs):
        return True

    async def save_turn_end(self, *args, **kwargs):
        return True


class FakeContext:
    def __init__(self) -> None:
        self.history: List[Any] = []
        self.added = 0

    async def add_message(self, message, message_id=None):
        self.added += 1


class FakeCommunicator:
    async def send_agent_response(self, **kwargs):
        return None

    async def send_tool_call(self, **kwargs):
        return None

    async def send_error(self, *args, **kwargs):
        return None

    async def send_step_message(self, *args, **kwargs):
        return None


class FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name

    def format(self) -> Dict[str, Any]:
        return {"name": self.name, "description": "bench tool", "parameters": {}}


class FakeToolExecutor:
    """Every tool succeeds instantly; permission is always ``auto``."""

    def __init__(self) -> None:
        self.executions = 0

    def get_permission(self, tool_name: str) -> str:
        return "auto"

    def is_readonly_tool(self, tool_name: str) -> bool:
        return True

    async def execute_tool(self, *args, **kwargs):
        self.executions += 1
        return SimpleNamespace(
            result=SimpleNamespace(status="success", content="ok", error=None)
        )


def make_config() -> SimpleNamespace:
    """Minimal config: snapshot tracking + compression off (pure orchestration)."""
    return SimpleNamespace(
        provider="openai",
        model="gpt-4o",
        workspace="",
        interactive=False,
        enable_snapshot_tracking=False,
        enable_context_compression=False,
        tool_execution_mode="parallel",
        max_parallel_tools=10,
        persistent_memory_config=None,
        execution_config=SimpleNamespace(
            step_max_errors=3,
            llm_retry_delay=0,
            llm_timeout=300,
            tool_call_timeout=120,
            assign_task_timeout=1800,
            dead_loop_window=3,
            tool_execution_mode="parallel",
            max_parallel_tools=10,
        ),
    )


def make_tool_calls(count: int) -> List[Any]:
    calls = []
    for i in range(count):
        fn = SimpleNamespace(name=f"tool{i}", arguments="{}")
        calls.append(SimpleNamespace(id=f"call-{i}", function=fn))
    return calls


# ── Engine builders ─────────────────────────────────────────────────────


class LegacyEngineGone(RuntimeError):
    """Raised when the legacy engine module no longer exists."""


async def build_legacy_engine():
    try:
        from broca.loop_engine.legacy import DefaultLoopEngine
    except ModuleNotFoundError as exc:  # Phase 5 removed the monolith
        raise LegacyEngineGone(
            "broca/loop_engine/legacy.py was removed in Phase 5, so the legacy "
            "baseline can no longer be re-measured from this tree.\n"
            "Use the committed baseline instead: "
            "reports/perf/loop-engine-baseline.json\n"
            "Run only: --impl new"
        ) from exc

    engine = DefaultLoopEngine(
        agent_ref=FakeAgentRef(),
        llm_client=FakeLLMClient(),
        context=FakeContext(),
        tool_mapping={f"tool{i}": FakeTool(f"tool{i}") for i in range(TOOL_COUNT)},
        config=make_config(),
        communicator=FakeCommunicator(),
        session_manager=FakeSessionManager(),
        tool_executor=FakeToolExecutor(),
        context_compressor=None,
        memory_manager=None,
    )
    return engine


async def build_new_engine():
    from broca.loop_engine.engine import DefaultLoopEngine
    from broca.loop_engine.hooks.factory import build_default_hooks

    config = make_config()
    context = FakeContext()
    engine = DefaultLoopEngine(
        agent_ref=FakeAgentRef(),
        llm_client=FakeLLMClient(),
        context=context,
        tool_mapping={f"tool{i}": FakeTool(f"tool{i}") for i in range(TOOL_COUNT)},
        config=config,
        communicator=FakeCommunicator(),
        session_manager=FakeSessionManager(),
        tool_executor=FakeToolExecutor(),
        hooks=build_default_hooks(
            config,
            snapshot_manager=None,
            communicator=FakeCommunicator(),
            context_compressor=None,
            memory_manager=None,
            context=context,
            session_id="session-bench",
            compressor_ctx_builder=None,
        ),
    )
    # ``_ensure_strategies`` is normally awaited inside ``execute()``.
    await engine._ensure_strategies()
    return engine


def make_turn_ctx():
    from broca.components.loop_hook import TurnContext

    return TurnContext(
        turn_id="turn-bench",
        agent_id="agent-bench",
        session_id="session-bench",
        user_message={},
        message_id="msg-user",
    )


# ── Benchmark bodies ────────────────────────────────────────────────────


async def bench_execute_round(impl: str) -> None:
    if impl == "legacy":
        engine = await build_legacy_engine()
        await engine.execute_round(max_steps=1)
    else:
        engine = await build_new_engine()
        await engine._execute_round(make_turn_ctx(), max_steps=1)


async def bench_llm_call(impl: str) -> None:
    if impl == "legacy":
        engine = await build_legacy_engine()
        engine.turn_id = "turn-bench"
        await engine._call_llm_with_retry()
    else:
        engine = await build_new_engine()
        engine.turn_id = "turn-bench"
        await engine._llm_strategy.call(
            history=engine.context.history,
            tools=[],
            on_chunk=None,
            on_error=None,
            should_abort=lambda: False,
        )


async def bench_parallel_tools(impl: str) -> None:
    async def _noop_result(*args, **kwargs):
        return True

    tool_calls = make_tool_calls(TOOL_COUNT)
    if impl == "legacy":
        engine = await build_legacy_engine()
        engine.turn_id = "turn-bench"
        # Result processing (broadcast + DB + context) is engine work in both
        # implementations and is measured by ``execute_round``; stub it out so
        # this benchmark isolates *parallel execution* only.
        engine.process_tool_call_result = _noop_result
        ctx = engine._build_tool_context()
        await engine._process_tool_calls_parallel(tool_calls, ctx)
    else:
        engine = await build_new_engine()
        engine.turn_id = "turn-bench"
        ctx = engine._build_tool_context()
        await engine._tool_strategy.execute(
            tool_calls,
            ctx,
            engine.tool_mapping,
            allowed_tools=None,
            should_abort=lambda: False,
        )


async def bench_hook_dispatch(impl: str) -> None:
    from broca.components.loop_hook import StepContext

    if impl == "legacy":
        engine = await build_legacy_engine()
        engine.turn_id = "turn-bench"
        engine.step_id = "step-bench"
        # Legacy has no dispatch: broadcasting a step message is the closest
        # equivalent single "hook-ish" call per step.
        from broca.session import MessageProtocol

        msg = MessageProtocol.create_step_end(step_id="step-bench", snapshot_hash="")
        msg.session_id = engine.session_id
        msg.turn_id = engine.turn_id
        msg.agent_id = engine.agent_id
        msg.subscription = engine.session_id
        await engine._broadcast_step_message(msg)
    else:
        engine = await build_new_engine()
        ctx = StepContext(
            step_id="step-bench",
            turn_id="turn-bench",
            agent_id="agent-bench",
            session_id="session-bench",
        )
        await engine._dispatch("on_step_start", ctx)


BENCHMARKS: Dict[str, Dict[str, Any]] = {
    "execute_round": {
        "fn": bench_execute_round,
        "iterations": ITERATIONS,
        "unit": "ms/round",
        "description": "one round: 1 step, 3 streamed chunks, no tool calls",
    },
    "llm_call": {
        "fn": bench_llm_call,
        "iterations": ITERATIONS,
        "unit": "ms/call",
        "description": "one LLM call, 3 streamed chunks, no retry",
    },
    "parallel_tools": {
        "fn": bench_parallel_tools,
        "iterations": ITERATIONS,
        "unit": "ms/batch",
        "description": f"{TOOL_COUNT} tool calls executed in parallel",
    },
    "hook_dispatch": {
        "fn": bench_hook_dispatch,
        "iterations": DISPATCH_ITERATIONS,
        "unit": "ms/call",
        "description": "one _dispatch over the 4 default hooks (4 awaits) / "
        "one step-message broadcast (legacy)",
    },
}


# ── Runner ──────────────────────────────────────────────────────────────


async def measure(fn: Callable[[str], Any], impl: str, iterations: int) -> Dict[str, float]:
    for _ in range(WARMUP):
        await fn(impl)

    samples: List[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        await fn(impl)
        samples.append((time.perf_counter() - start) * 1000.0)

    return {
        "iterations": iterations,
        "mean_ms": round(statistics.fmean(samples), 6),
        "median_ms": round(statistics.median(samples), 6),
        "min_ms": round(min(samples), 6),
        "max_ms": round(max(samples), 6),
        "stdev_ms": round(statistics.stdev(samples), 6) if len(samples) > 1 else 0.0,
    }


async def main(impl: str, out: Path) -> int:
    if impl == "legacy":
        import importlib.util

        if importlib.util.find_spec("broca.loop_engine.legacy") is None:
            print(
                "error: --impl legacy is no longer runnable — "
                "broca/loop_engine/legacy.py was deleted in Phase 5.\n"
                "       The recorded baseline is "
                "reports/perf/loop-engine-baseline.json\n"
                "       Re-run with --impl new to refresh the after numbers.",
                file=sys.stderr,
            )
            return 2

    results: Dict[str, Any] = {
        "implementation": impl,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "warmup": WARMUP,
        "benchmarks": {},
    }

    for name, spec in BENCHMARKS.items():
        stats = await measure(spec["fn"], impl, spec["iterations"])
        stats["unit"] = spec["unit"]
        stats["description"] = spec["description"]
        results["benchmarks"][name] = stats
        print(
            f"[{impl}] {name:16s} mean={stats['mean_ms']:.4f} ms "
            f"median={stats['median_ms']:.4f} ms  ({spec['unit']})"
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--impl", choices=["legacy", "new"], required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.impl, args.out)))
