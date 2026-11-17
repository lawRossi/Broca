"""Regression tests: process meta.json writes must survive a missing output dir.

One-shot background jobs are executed through ProcessManager. The final status
write happens in ``_wait_process`` after the child exits. If the job output
directory disappeared in the meantime (another instance's startup cleanup,
workspace cleanup, ...), the old code logged::

    Failed to write meta .broca/process_outputs/<job>/meta.json:
    [Errno 2] No such file or directory

These tests verify the directory is recreated and paths are absolute.
"""

import asyncio
import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def pm_env(monkeypatch, tmp_path):
    """Isolated ProcessManager with OUTPUT_DIR under tmp_path (no real ~/.broca)."""
    from broca.process_manager import LocalProcessManager

    out = tmp_path / "process_outputs"
    out.mkdir()
    monkeypatch.setattr(LocalProcessManager, "OUTPUT_DIR", out)

    # 项目使用 loguru bound logger，caplog 捕获不到；用 mock 断言告警。
    mock_logger = MagicMock()
    monkeypatch.setattr("broca.process_manager.logger", mock_logger)

    pm = LocalProcessManager()
    saved_processes = pm._processes
    pm._processes = {}
    yield pm, out, mock_logger

    for info in list(pm._processes.values()):
        task = getattr(info, "_wait_task", None)
        if task is not None and not task.done():
            task.cancel()
    pm._processes = saved_processes


def test_write_meta_recreates_missing_parent(pm_env):
    """AC: writing meta into a deleted directory succeeds without a warning."""
    pm, out, mock_logger = pm_env
    meta = out / "job_missing_dir" / "meta.json"

    pm._write_meta(meta, {"status": "completed", "exit_code": 0})

    assert meta.exists()
    assert json.loads(meta.read_text()) == {"status": "completed", "exit_code": 0}
    mock_logger.warning.assert_not_called()


def test_write_meta_preserves_existing_fields(pm_env):
    """AC: partial update keeps fields written earlier."""
    pm, out, _ = pm_env
    meta = out / "job_partial" / "meta.json"

    pm._write_meta(meta, {"status": "running", "pid": 123})
    pm._write_meta(meta, {"status": "completed", "exit_code": 0})

    assert json.loads(meta.read_text()) == {
        "status": "completed",
        "pid": 123,
        "exit_code": 0,
    }


@pytest.mark.asyncio
async def test_final_meta_write_survives_deleted_output_dir(pm_env):
    """AC: process finish writes status meta even if dir was removed mid-run."""
    pm, _, mock_logger = pm_env
    info = await pm.start_process("sleep 0.4")

    # Wait until the shell has opened the redirected output files, then remove
    # the directory to emulate an external cleanup while the job still runs.
    for _ in range(100):
        if Path(info.stdout_path).exists():
            break
        await asyncio.sleep(0.01)

    shutil.rmtree(Path(info.meta_path).parent)
    await info._wait_task

    assert Path(info.meta_path).exists()
    data = json.loads(Path(info.meta_path).read_text())
    assert data["status"] == "completed"
    assert data["exit_code"] == 0
    mock_logger.warning.assert_not_called()


@pytest.mark.asyncio
async def test_start_process_stores_absolute_paths(pm_env, monkeypatch, tmp_path):
    """AC: relative OUTPUT_DIR is resolved to absolute paths at start time."""
    from broca.process_manager import LocalProcessManager

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        LocalProcessManager, "OUTPUT_DIR", Path(".broca/process_outputs")
    )
    pm = LocalProcessManager()

    info = await pm.start_process("echo ok")
    try:
        assert Path(info.meta_path).is_absolute()
        assert Path(info.stdout_path).is_absolute()
        assert Path(info.stderr_path).is_absolute()

        # A cwd change after start must not redirect the final meta write.
        meta_path = Path(info.meta_path)
        monkeypatch.chdir(tmp_path.parent)
        await info._wait_task
        assert meta_path.exists()
        assert json.loads(meta_path.read_text())["status"] == "completed"
    finally:
        if info._wait_task and not info._wait_task.done():
            info._wait_task.cancel()
