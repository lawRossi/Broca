"""
持久化记忆 Manager 单元测试
"""

from broca.persistent_memory.state import PersistentMemoryState
from broca.agent_configs import PersistentMemoryConfig


class TestPersistentMemoryState:
    def test_default_state(self):
        state = PersistentMemoryState()
        assert state.initialized is False
        assert state.last_message_index == 0
        assert state.last_step_count == 0
        assert state.step_count == 0
        assert state.extraction_in_progress is False

    def test_reset(self):
        state = PersistentMemoryState()
        state.initialized = True
        state.step_count = 50
        state.extraction_in_progress = True
        state.reset()
        assert state.initialized is False
        assert state.step_count == 0
        assert state.extraction_in_progress is False


class TestPersistentMemoryConfig:
    def test_default_config(self):
        cfg = PersistentMemoryConfig()
        assert cfg.minimum_messages_to_init == 50
        assert cfg.minimum_messages_between_update == 30
        assert cfg.steps_between_updates == 20
        assert cfg.freshness_warning_days == 7

    def test_custom_config(self):
        cfg = PersistentMemoryConfig(
            minimum_messages_to_init=10,
            minimum_messages_between_update=5,
            steps_between_updates=3,
            freshness_warning_days=14,
        )
        assert cfg.minimum_messages_to_init == 10
        assert cfg.minimum_messages_between_update == 5
        assert cfg.steps_between_updates == 3
        assert cfg.freshness_warning_days == 14
