"""
Patch 反向应用模块

反向应用 patch，用于撤销操作。
"""

from typing import Dict, List, Any

from .restore import SnapshotRestorer


class PatchReverter:
    """Patch 反向应用器"""

    def __init__(self, workspace_path: str):
        """
        初始化 Patch 反向应用器
s
        Args:
            workspace_path: 工作空间路径
        """
        self.workspace_path = workspace_path
        self.restorer = SnapshotRestorer(workspace_path)

    def revert_patches(self, patches: List[Dict[str, Any]]) -> None:
        """
        反向应用多个 patch

        Args:
            patches: patch 信息字典列表
        """
        file_snapshot_mapping = {}
        for patch in patches:
            snapshot_hash = patch.get("snapshot_hash")
            files = patch.get("files", [])
            if snapshot_hash and files:
                for file_path in files:
                    if file_path not in file_snapshot_mapping:
                        file_snapshot_mapping[file_path] = snapshot_hash

        print(file_snapshot_mapping)
        for file, snapshot_hash in file_snapshot_mapping.items():
            self.restorer.restore_file(snapshot_hash, file)

    def apply_patch(self, patch: Dict[str, any]) -> None:
        """
        正向应用 patch（用于重做操作）

        Args:
            patch: patch 信息字典
        """
        snapshot_hash = patch.get("snapshot_hash")
        if snapshot_hash:
            # 如果提供了快照哈希，直接恢复到该快照
            self.restorer.restore(snapshot_hash)
