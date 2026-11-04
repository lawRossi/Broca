"""Task 5.3: Agent.__init__ has no side effects.

Regression test verifying that ``Agent.__init__()`` does NOT:
  - create a ``GitSnapshotManager``
  - call ``GitSnapshotManager.initialize()``
  - create a ``SessionRevertService``

These operations are deferred to ``Agent.create()`` to avoid expensive
Git operations during object construction.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broca.agent import Agent
from broca.agent_configs import AgentConfig


def _make_config() -> AgentConfig:
    cfg = AgentConfig()
    cfg.name = "test-agent"
    cfg.role = "test"
    cfg.role_description = "test"
    cfg.system_prompt_template = "test"
    cfg.tools = []
    cfg.workspace = "/tmp/test-workspace"
    cfg.save_history = False
    cfg.server_url = "http://localhost:9999"
    cfg.enable_context_compression = False
    cfg.enable_snapshot_tracking = False
    return cfg


def _make_session_manager() -> AsyncMock:
    sm = AsyncMock()
    sm.session_id = "test-session"
    sm.agent_service = AsyncMock()
    sm.agent_service.get = AsyncMock(return_value=None)
    return sm


def _make_llm_client() -> AsyncMock:
    llm = AsyncMock()
    llm.config = {"openai": {"models": {"gpt-4": {"meta": {}}}}}
    return llm


class TestAgentInitNoSideEffects:
    """Agent.__init__ must not perform any I/O or heavy construction."""

    def test_init_does_not_create_git_snapshot_manager(self) -> None:
        """GitSnapshotManager is NOT instantiated in __init__."""
        with patch("broca.agent.GitSnapshotManager") as mock_gsm:
            mock_gsm.return_value = MagicMock()

            agent = Agent(
                config=_make_config(),
                llm_client=_make_llm_client(),
                session_manager=_make_session_manager(),
            )

            mock_gsm.assert_not_called()
            assert agent.revert_service is None

    def test_init_does_not_call_snapshot_initialize(self) -> None:
        """GitSnapshotManager.initialize() is NOT called in __init__."""
        with patch("broca.agent.GitSnapshotManager") as mock_gsm:
            mock_instance = MagicMock()
            mock_instance.initialize = MagicMock()
            mock_gsm.return_value = mock_instance

            Agent(
                config=_make_config(),
                llm_client=_make_llm_client(),
                session_manager=_make_session_manager(),
            )

            mock_gsm.assert_not_called()
            mock_instance.initialize.assert_not_called()

    def test_init_does_not_create_revert_service(self) -> None:
        """SessionRevertService is NOT created in __init__."""
        with patch("broca.agent.SessionRevertService") as mock_revert:
            agent = Agent(
                config=_make_config(),
                llm_client=_make_llm_client(),
                session_manager=_make_session_manager(),
            )

            mock_revert.assert_not_called()
            assert agent.revert_service is None

    def test_revert_service_is_none_after_init(self) -> None:
        """revert_service attribute exists and is None after __init__."""
        agent = Agent(
            config=_make_config(),
            llm_client=_make_llm_client(),
            session_manager=_make_session_manager(),
        )
        assert hasattr(agent, "revert_service")
        assert agent.revert_service is None

    def test_init_does_not_create_context_compressor(self) -> None:
        """context_compressor is None (set later in create())."""
        agent = Agent(
            config=_make_config(),
            llm_client=_make_llm_client(),
            session_manager=_make_session_manager(),
        )
        assert agent.context_compressor is None

    def test_init_does_not_create_memory_manager(self) -> None:
        """persistent_memory_manager is None (set later in create())."""
        agent = Agent(
            config=_make_config(),
            llm_client=_make_llm_client(),
            session_manager=_make_session_manager(),
        )
        assert agent.persistent_memory_manager is None
