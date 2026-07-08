"""
PersistentMemory 状态管理
"""

from dataclasses import dataclass, field


@dataclass
class PersistentMemoryState:
    """持久化记忆提取状态"""

    initialized: bool = False
    last_message_index: int = 0
    last_step_count: int = 0
    step_count: int = 0
    extraction_in_progress: bool = False

    def reset(self):
        """重置所有状态"""
        self.initialized = False
        self.last_message_index = 0
        self.last_step_count = 0
        self.step_count = 0
        self.extraction_in_progress = False
