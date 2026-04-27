"""
Session Memory 工具函数和状态管理
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class SessionMemoryConfig:
    """Session Memory 配置"""

    minimum_messages_to_init: int = 30
    minimum_messages_between_update: int = 20
    steps_between_updates: int = 10


DEFAULT_CONFIG = SessionMemoryConfig()


@dataclass
class SessionMemoryState:
    """Session Memory 状态"""

    initialized: bool = False
    last_message_id: str = ""
    last_message_index: int = 0
    last_step_count: int = 0
    step_count: int = 0
    extraction_in_progress: bool = False

    def reset(self):
        """重置状态"""
        self.initialized = False
        self.last_message_id = ""
        self.last_message_index = 0
        self.last_step_count = 0
        self.step_count = 0
        self.extraction_in_progress = False
