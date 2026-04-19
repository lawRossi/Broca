"""
Patch 反向应用模块

反向应用 patch，用于撤销操作。
"""

from typing import Dict, List

from .restore import SnapshotRestorer


class PatchReverter:
    """Patch 反向应用器"""

    def __init__(self, workspace_path: str):
        """
        初始化 Patch 反向应用器

        Args:
            workspace_path: 工作空间路径
        """
        self.workspace_path = workspace_path
        self.restorer = SnapshotRestorer(workspace_path)

    def revert_patch(self, patch: Dict[str, any]) -> None:
        """
        反向应用 patch

        Args:
            patch: patch 信息字典，包含 snapshot_hash 和 files 列表
        """
        snapshot_hash = patch.get("snapshot_hash")
        files = patch.get("files", [])

        if not snapshot_hash:
            raise ValueError("patch 必须包含 snapshot_hash")

        if not files:
            # 如果没有变更文件，直接恢复到快照
            self.restorer.restore(snapshot_hash)
            return

        # 对每个变更文件，从快照中恢复
        for file_path in files:
            self.restorer.restore_file(snapshot_hash, file_path)

    def revert_patches(self, patches: List[Dict[str, any]]) -> None:
        """
        反向应用多个 patch

        Args:
            patches: patch 信息字典列表
        """
        # 按顺序反向应用 patch
        for patch in reversed(patches):
            self.revert_patch(patch)

    def apply_patch(self, patch: Dict[str, any]) -> None:
        """
        正向应用 patch（用于重做操作）

        Args:
            patch: patch 信息字典
        """
        # 正向应用 patch 实际上就是反向应用反向 patch
        # 这里我们假设 patch 是从旧状态到新状态的变更
        # 在实际使用中，重做操作会使用保存的撤销记录中的 snapshot 来恢复
        snapshot_hash = patch.get("snapshot_hash")
        if snapshot_hash:
            # 如果提供了快照哈希，直接恢复到该快照
            self.restorer.restore(snapshot_hash)
        else:
            # 否则，反向应用 patch（撤销撤销操作）
            self.revert_patch(patch)