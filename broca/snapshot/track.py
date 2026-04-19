import asyncio
from .git_manager import SnapshotGitManager


async def track_snapshot(workspace: str) -> str | None:
    manager = SnapshotGitManager(workspace)
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, manager.get_tree_hash)


async def compute_patch(workspace: str, from_hash: str) -> list[str]:
    # TODO: implement later
    return []


async def restore_snapshot(workspace: str, tree_hash: str) -> bool:
    # TODO: implement later
    return True