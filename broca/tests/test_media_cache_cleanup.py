"""Task 2.6: 缓存生命周期清理（clear_context / clear_all_context / clear_history / 删除 session / TTL GC）。"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broca.commands.base import CommandContext
from broca.media.cache import MediaCache, default_cache_root


def _seed(session, agent):
    c = MediaCache(session, agent)
    return c


async def _seed_put(session, agent, key="k", val="v"):
    await MediaCache(session, agent).put(key, val)


def _ctx(agent, context):
    return CommandContext(
        workspace="/tmp/ws", session_id="sess", agent_id="agentA",
        agent=agent, context=context,
    )


def _make_agent(session_id="sess", agent_id="agentA"):
    agent = MagicMock()
    agent.status = "idle"
    agent.STATUS_RUNNING = "running"
    agent.agent_id = agent_id
    agent.session_id = session_id
    agent.config.name = "Tester"
    agent.config.enable_context_compression = False
    agent.context_compressor = None
    agent.communicator = MagicMock(send_agent_system_message=AsyncMock())
    agent.session_manager = MagicMock()
    agent.session_manager.session_id = session_id
    agent.session_manager.get_messages = AsyncMock(return_value=[])
    agent.session_manager.batch_update_messages = AsyncMock()
    agent.session_manager.message_service = MagicMock()
    agent.session_manager.message_service.get_messages_by_session = AsyncMock(return_value=[])
    agent.session_manager.turn_service = MagicMock()
    agent.session_manager.turn_service.get_batch = AsyncMock(return_value=[])
    agent.session_manager.batch_update_turns = AsyncMock()
    agent.session_manager.agent_service = MagicMock()
    agent.session_manager.agent_service.get_agents_by_session = AsyncMock(return_value=[])
    return agent


class TestClearContext:
    @pytest.mark.asyncio
    async def test_clears_only_current_agent_cache(self):
        from broca.commands.builtin.clear_context import ClearContextCommand

        await _seed_put("sess", "agentA")
        await _seed_put("sess", "agentB")
        agent = _make_agent(agent_id="agentA")
        context = MagicMock()
        context.build_history_from_session = AsyncMock()

        result = await ClearContextCommand().execute("", _ctx(agent, context))
        assert result.type == "text"
        root = default_cache_root()
        assert not (root / "sess" / "agentA").exists()  # 当前 agent 已清
        assert (root / "sess" / "agentB").exists()       # 其他 agent 保留


class TestClearAllContext:
    @pytest.mark.asyncio
    async def test_clears_whole_session_cache(self):
        from broca.commands.builtin.clear_all_context import ClearAllContextCommand
        from broca.components import ComponentRegistry
        from broca.components.agent_factory import AgentFactory as AgentFactoryABC

        await _seed_put("sess", "agentA")
        await _seed_put("sess", "agentB")

        factory = MagicMock()
        factory._session_agents = {"sess": {}}  # 无 agent → 跳过 rebuild 循环
        registry = MagicMock()
        registry.get.return_value = factory

        agent = _make_agent()
        context = MagicMock()
        with patch.object(ComponentRegistry, "get_instance", return_value=registry):
            result = await ClearAllContextCommand().execute("", _ctx(agent, context))
        assert result.type == "text"
        assert not (default_cache_root() / "sess").exists()


class TestClearHistory:
    @pytest.mark.asyncio
    async def test_clears_whole_session_cache(self):
        from broca.commands.builtin.clear_history import ClearHistoryCommand
        from broca.components import ComponentRegistry

        await _seed_put("sess", "agentA")
        await _seed_put("sess", "agentB")

        factory = MagicMock()
        factory._session_agents = {"sess": {}}
        registry = MagicMock()
        registry.get.return_value = factory

        agent = _make_agent()
        context = MagicMock()
        context.build_history_from_session = AsyncMock()
        with patch.object(ComponentRegistry, "get_instance", return_value=registry):
            result = await ClearHistoryCommand().execute("", _ctx(agent, context))
        assert result.type == "text"
        assert not (default_cache_root() / "sess").exists()


class TestSessionDeleteCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_session_removes_media_cache(self):
        from broca.session.cleanup_service import SessionCleanupService

        SessionCleanupService._instance = None
        svc = SessionCleanupService()
        await _seed_put("del-sess", "agentA")
        assert (default_cache_root() / "del-sess").exists()

        with patch.object(svc, "cleanup_workspace_files", new=AsyncMock()), \
             patch.object(svc, "cleanup_runner_logs", new=AsyncMock()), \
             patch.object(svc, "cleanup_orphaned_jobs", new=AsyncMock(return_value=0)), \
             patch.object(svc, "cleanup_snapshots_if_last_session", new=AsyncMock()):
            await svc.cleanup_session("/tmp/ws", "del-sess")

        assert not (default_cache_root() / "del-sess").exists()

    @pytest.mark.asyncio
    async def test_media_cache_failure_does_not_raise(self):
        from broca.session.cleanup_service import SessionCleanupService
        import broca.media.cache as cache_mod

        SessionCleanupService._instance = None
        svc = SessionCleanupService()

        def boom(session_id, **kw):
            raise OSError("fail")

        with patch.object(svc, "cleanup_workspace_files", new=AsyncMock()), \
             patch.object(svc, "cleanup_runner_logs", new=AsyncMock()), \
             patch.object(svc, "cleanup_orphaned_jobs", new=AsyncMock(return_value=0)), \
             patch.object(svc, "cleanup_snapshots_if_last_session", new=AsyncMock()), \
             patch.object(cache_mod, "clear_session_cache", side_effect=boom):
            # 不应抛异常
            await svc.cleanup_session("/tmp/ws", "some-sess")
