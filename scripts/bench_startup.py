#!/usr/bin/env python3
"""Startup time baseline measurement script.

Measures two metrics:
  1. ``import broca`` — time to import the broca package
  2. ``Agent.create()`` — median time over N runs

Output: CSV to stdout for easy comparison between runs.

Usage:
    python scripts/bench_startup.py [--runs 20] [--output results.csv]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
import tempfile
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. Measure `import broca`
# ---------------------------------------------------------------------------


def measure_import_time() -> float:
    """Measure time to import broca (in a subprocess for clean state)."""
    import subprocess

    code = (
        "import time; t0=time.perf_counter(); "
        "import broca; "
        "print(f'{(time.perf_counter()-t0)*1000:.1f}')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True,
        timeout=30,
    )
    if result.returncode != 0:
        print(f"ERROR: import failed: {result.stderr}", file=sys.stderr)
        return 0.0
    return float(result.stdout.strip())


# ---------------------------------------------------------------------------
# 2. Measure Agent.create() time
# ---------------------------------------------------------------------------


def measure_agent_create(n_runs: int = 20) -> list[float]:
    """Measure Agent.create() time over n_runs (in a subprocess)."""
    import subprocess

    # Write the benchmark code to a temp file to avoid f-string issues
    code = '''
import asyncio, sys, time, tempfile
sys.path.insert(0, ".")
from unittest.mock import AsyncMock, patch as _patch
from broca.agent import Agent
from broca.agent_configs import AgentConfig
from broca.components.tool_manager import ToolManager
from broca.components.registry import ComponentRegistry

class _MockTM(ToolManager):
    async def init(self, workspace=None): pass
    def get_tools(self, tool_names=None): return []
    def get_mcp_tools(self, mcp_servers=None): return []
    def load_custom_tools(self, workspace=None): return []

registry = ComponentRegistry()
registry.register_defaults()
registry.set_override(ToolManager, _MockTM)

sm = AsyncMock()
sm.session_id = "bench"
sm.agent_service = AsyncMock()
sm.agent_service.get = AsyncMock(return_value=None)
sm.agent_service.update = AsyncMock()
sm.agent_service.update_agent_status = AsyncMock()
sm.get_agents = AsyncMock(return_value=[])
sm.get_agent_config = AsyncMock(return_value=None)
sm.load_session = AsyncMock()
sm.create_session = AsyncMock()

llm = AsyncMock()
llm.config = {}

cfg = AgentConfig()
cfg.name = "bench"; cfg.role = "bench"; cfg.role_description = "bench"
cfg.system_prompt_template = "test"; cfg.tools = []
cfg.workspace = tempfile.mkdtemp()
cfg.save_history = False; cfg.server_url = "http://localhost:9999"
cfg.enable_context_compression = False; cfg.enable_snapshot_tracking = False

async def create_once(i):
    with _patch("broca.components.registry.ComponentRegistry.get_instance",
                return_value=registry):
        a = await Agent.create(cfg, llm, sm, agent_id="bench-" + str(i))
        await a.disconnect()

async def main():
    import os
    n_runs = int(os.environ.get("BENCH_RUNS", "20"))
    await create_once(0)
    times = []
    for i in range(1, n_runs + 1):
        t0 = time.perf_counter()
        await create_once(i)
        times.append(time.perf_counter() - t0)
    times.sort()
    med = times[len(times)//2]
    print("median=" + str(round(med*1000, 1)))
    for t in times:
        print("run=" + str(round(t*1000, 1)))

asyncio.run(main())
'''
    import os
    env = dict(os.environ)
    env["BENCH_RUNS"] = str(n_runs)

    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True,
        timeout=120,
        cwd=str(Path(__file__).resolve().parent.parent),
        env=env,
    )
    if result.returncode != 0:
        print(f"ERROR: {result.stderr[:500]}", file=sys.stderr)
        return []

    lines = result.stdout.strip().split("\n")
    times = []
    for line in lines:
        if line.startswith("run="):
            times.append(float(line.split("=")[1]))
    return times


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Broca startup time benchmark")
    parser.add_argument("--runs", type=int, default=20, help="Number of Agent.create() runs")
    parser.add_argument("--output", type=str, default=None, help="Output CSV path")
    args = parser.parse_args()

    print(f"Benchmarking with {args.runs} runs...")

    # Measure import time
    print("  [1/2] Measuring import time...")
    import_ms = measure_import_time()
    print(f"         import broca: {import_ms:.1f}ms")

    # Measure Agent.create() time
    print("  [2/2] Measuring Agent.create() time...")
    times = measure_agent_create(args.runs)
    if not times:
        print("ERROR: No timing data collected", file=sys.stderr)
        sys.exit(1)

    times.sort()
    median_ms = times[len(times) // 2]
    min_ms = times[0]
    max_ms = times[-1]
    mean_ms = sum(times) / len(times)

    print(f"\n  Results ({args.runs} runs):")
    print(f"    import broca:   {import_ms:.1f}ms")
    print(f"    Agent.create(): median={median_ms:.1f}ms  min={min_ms:.1f}ms  "
          f"max={max_ms:.1f}ms  mean={mean_ms:.1f}ms")

    # Output CSV
    if args.output:
        with open(args.output, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["metric", "value_ms"])
            writer.writerow(["import_broca", f"{import_ms:.1f}"])
            writer.writerow(["agent_create_median", f"{median_ms:.1f}"])
            writer.writerow(["agent_create_min", f"{min_ms:.1f}"])
            writer.writerow(["agent_create_max", f"{max_ms:.1f}"])
            writer.writerow(["agent_create_mean", f"{mean_ms:.1f}"])
            print(f"\n  CSV written to: {args.output}")


if __name__ == "__main__":
    main()
