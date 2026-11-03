"""Tests for GitManager thread safety (Task 2.3)."""

import asyncio
import threading

import pytest

from broca.snapshot.git_manager import GitManager


@pytest.fixture(autouse=True)
def _cleanup_instances():
    """Clean up GitManager._instances before and after each test."""
    GitManager._instances.clear()
    yield
    GitManager._instances.clear()


class TestGitManagerThreadSafety:
    """Verify GitManager singleton is thread/coroutine safe."""

    def test_concurrent_same_path_returns_same_instance(self):
        """10 coroutines + 2 threads all calling GitManager("/same/path") get the same object."""
        target_path = "/tmp/broca_test_workspace_xyz"
        results = []
        lock = threading.Lock()

        # Run coroutines in a thread with its own event loop
        def run_coroutines():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                async def create():
                    inst = GitManager(target_path)
                    with lock:
                        results.append(inst)
                    return inst

                async def run_all():
                    await asyncio.gather(*[create() for _ in range(10)])

                loop.run_until_complete(run_all())
            finally:
                loop.close()

        def run_thread():
            for _ in range(5):
                inst = GitManager(target_path)
                with lock:
                    results.append(inst)

        t1 = threading.Thread(target=run_coroutines)
        t2 = threading.Thread(target=run_thread)
        t3 = threading.Thread(target=run_thread)
        t1.start(); t2.start(); t3.start()
        t1.join(); t2.join(); t3.join()

        assert len(results) == 20
        first = results[0]
        assert all(x is first for x in results), "Not all instances are the same object"

    def test_different_paths_get_different_instances(self):
        """Different workspace paths should return different GitManager instances."""
        a = GitManager("/tmp/broca_test_ws_a")
        b = GitManager("/tmp/broca_test_ws_b")
        assert a is not b

    def test_init_idempotent(self):
        """Multiple __init__ calls on the same instance don't re-initialize."""
        gm = GitManager("/tmp/broca_test_ws_init")
        workspace_path = gm.workspace_path
        repo_path = gm.repo_path
        # Call __init__ again (simulating re-creation via __new__ + __init__)
        gm.__init__("/tmp/broca_test_ws_init")
        assert gm.workspace_path == workspace_path
        assert gm.repo_path == repo_path


class TestGitManagerClassLock:
    """Verify the class-level lock exists and protects _instances."""

    def test_class_lock_exists(self):
        assert hasattr(GitManager, "_class_lock")
        assert isinstance(GitManager._class_lock, type(threading.Lock()))

    def test_instance_lock_created_on_new(self):
        """Each new instance gets its own _instance_lock."""
        gm = GitManager("/tmp/broca_test_ws_lockcheck")
        assert hasattr(gm, "_instance_lock")
        assert isinstance(gm._instance_lock, type(threading.Lock()))
