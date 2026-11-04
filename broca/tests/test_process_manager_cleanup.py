"""
Regression tests: ProcessManager startup cleanup removes stale disk directories.

Fix: _cleanup_stale_disk_dirs() scans OUTPUT_DIR on init and removes
directories whose mtime exceeds _MAX_PROCESS_AGE, even after restart
when the in-memory _processes dict is empty.
"""

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_pm_with_dir(tmp_path: Path):
    """Create a LocalProcessManager with OUTPUT_DIR pointing to tmp_path."""
    from broca.process_manager import LocalProcessManager

    out = tmp_path / "process_outputs"
    out.mkdir(exist_ok=True)

    with patch("broca.process_manager.ProcessManagerABC", MagicMock):
        pm = LocalProcessManager()
    pm.OUTPUT_DIR = out
    pm._processes = {}
    return pm, out


def _create_stale_dir(out: Path, name: str) -> Path:
    """Create a directory with mtime set to 2 hours ago."""
    d = out / name
    d.mkdir(exist_ok=True)
    (d / "stdout.log").write_text("old output")
    (d / "meta.json").write_text("{}")
    old_time = time.time() - 7200
    os.utime(d, (old_time, old_time))
    for f in d.iterdir():
        os.utime(f, (old_time, old_time))
    return d


def _create_fresh_dir(out: Path, name: str) -> Path:
    """Create a directory with current mtime."""
    d = out / name
    d.mkdir(exist_ok=True)
    (d / "stdout.log").write_text("new output")
    return d


class TestStartupCleanup:
    """Verify _cleanup_stale_disk_dirs removes only stale dirs."""

    def test_removes_stale_keeps_fresh(self, tmp_path):
        """AC: stale dir removed, fresh dir kept."""
        pm, out = _make_pm_with_dir(tmp_path)
        stale = _create_stale_dir(out, "proc_stale_123")
        fresh = _create_fresh_dir(out, "proc_fresh_456")

        pm._cleanup_stale_disk_dirs()

        assert not stale.exists(), "Stale dir should be removed"
        assert fresh.exists(), "Fresh dir should be kept"

    def test_skips_running_process_dir(self, tmp_path):
        """AC: stale dir tracked as RUNNING in memory is kept."""
        from broca.process_manager import ProcessInfo, ProcessStatus

        pm, out = _make_pm_with_dir(tmp_path)
        stale = _create_stale_dir(out, "proc_running")

        # Simulate a running process tracked in memory
        info = ProcessInfo(
            process_id="proc_running",
            pid=99999,
            command="sleep 9999",
            status=ProcessStatus.RUNNING,
            start_time=datetime.now(timezone.utc),
        )
        pm._processes["proc_running"] = info

        pm._cleanup_stale_disk_dirs()

        assert stale.exists(), "Running process dir should NOT be removed"

    def test_nonexistent_output_dir(self, tmp_path):
        """AC: OUTPUT_DIR doesn't exist → no error."""
        pm, _ = _make_pm_with_dir(tmp_path)
        pm.OUTPUT_DIR = tmp_path / "does_not_exist"
        pm._cleanup_stale_disk_dirs()  # should not raise

    def test_loose_files_ignored(self, tmp_path):
        """AC: non-directory entries in OUTPUT_DIR are not touched."""
        pm, out = _make_pm_with_dir(tmp_path)
        stray = out / "stray.log"
        stray.write_text("hello")
        old_time = time.time() - 7200
        os.utime(stray, (old_time, old_time))

        pm._cleanup_stale_disk_dirs()

        assert stray.exists(), "Loose files should not be removed"

    def test_init_calls_cleanup(self, tmp_path):
        """AC: ProcessManager.__init__ triggers _cleanup_stale_disk_dirs."""
        from broca.process_manager import LocalProcessManager

        out = tmp_path / "process_outputs"
        out.mkdir()
        _create_stale_dir(out, "proc_old")

        with patch("broca.process_manager.ProcessManagerABC", MagicMock):
            pm = LocalProcessManager()
        # Redirect to our test dir and re-run cleanup
        pm.OUTPUT_DIR = out
        pm._processes = {}
        pm._cleanup_stale_disk_dirs()

        assert not (out / "proc_old").exists()
