"""
Snapshot 模块

提供文件系统快照管理功能，用于支持 undo/redo 操作。
基于独立的 Git 仓库实现快照捕获、patch 计算和恢复。
"""

from .git_manager import GitManager
from .track import SnapshotTracker
from .patch import PatchCalculator
from .restore import SnapshotRestorer
from .revert import PatchReverter

__all__ = [
    "GitManager",
    "SnapshotTracker",
    "PatchCalculator",
    "SnapshotRestorer",
    "PatchReverter",
]