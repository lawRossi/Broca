"""Shared pytest fixtures for broca-web backend tests.

Provides mock dependencies, test database sessions, async HTTP client,
and reusable auth helpers.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# Override settings before importing app modules
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only"
os.environ["SQLITE_DATABASE_PATH"] = "sqlite:///./test.db"
os.environ["BROCA_SOCKETIO_ENABLED"] = "false"

# ---------------------------------------------------------------------------
# Patch broca package imports at module level
# ---------------------------------------------------------------------------

_broca_patches = [
    patch("broca.logging_config.init_logging", return_value=None),
    patch("broca.agent_manager.AgentFactory"),
    patch("broca.session_runner.RunnerManager"),
    patch("broca.session_runner.RunnerManager.get_instance", return_value=AsyncMock()),
    patch("broca.communication.socketio_server.SocketIOServer"),
    patch("broca.configs.get_configs"),
    patch("broca.commands.loader.load_all_commands"),
    patch("broca.commands.registry.CommandRegistry"),
    patch("broca.scheduler.Scheduler", return_value=AsyncMock()),
    patch("broca.orchestration.crew.CrewConfig"),
    patch("broca.orchestration.crew.CrewConfigValidator"),
    patch("broca.session.database.db_manager"),
    patch("broca.session.models.CrewExecution"),
    patch("broca.session.service.get_session_service"),
    patch("broca.session.service.get_message_service"),
    patch("broca.session.service.get_turn_service"),
    patch("broca.session.service.get_agent_service"),
    patch("broca.session.service.get_agent_config_service"),
    patch("broca.session.service.get_job_service"),
    patch("broca.session.service.get_job_execution_service"),
    patch("broca.session.service.get_task_service"),
    patch("broca.session.service.get_task_comment_service"),
    patch("broca.session.service.db_manager"),
    patch("broca.utils.datetime_util.serialize_dt"),
]


def _apply_broca_patches() -> list:
    """Apply all broca package patches and return the patch objects for cleanup."""
    patches = [p.start() for p in _broca_patches]
    return patches


def _stop_broca_patches(patches: list) -> None:
    """Stop all broca package patches."""
    for p in _broca_patches:
        p.stop()


# Apply patches at import time
_apply_broca_patches()

# Now safe to import app modules
from app.core.config import settings
from app.main import app as _app
from app.schemas.schemas import ApiResponse
from app.services.auth_service import AuthService


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def _reset_settings() -> None:
    """Reset settings environment overrides after each test."""
    yield


@pytest.fixture
def anyio_backend() -> str:
    """Required by pytest-asyncio."""
    return "asyncio"


@pytest.fixture
def test_app() -> FastAPI:
    """Return the FastAPI test application instance.

    The app already has all dependencies registered. Tests can override
    dependencies via ``app.dependency_overrides``.
    """
    return _app


@pytest_asyncio.fixture
async def async_client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Create an async HTTP test client."""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Generate valid JWT auth headers for testing."""
    user_id = str(uuid.uuid4())
    token = AuthService.create_access_token(user_id, "testuser")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def mock_db_session() -> AsyncMock:
    """Create a mock async database session."""
    session = AsyncMock()
    session.add = MagicMock()
    session.add_all = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    session.scalar = AsyncMock()
    session.scalars = MagicMock()
    session.get = AsyncMock()
    session.delete = AsyncMock()

    # Make execute result chainable for scalars().all()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    return session


@pytest.fixture
def mock_runner_manager() -> MagicMock:
    """Create a mock RunnerManager."""
    manager = MagicMock()
    manager.get_session_status = MagicMock(return_value={"status": "running", "pid": 12345})
    manager.get_stats = MagicMock(return_value={"total_runners": 1, "active_runners": 1})
    manager.start_session = AsyncMock()
    manager.stop_session = AsyncMock(return_value=True)
    manager.restart_session = AsyncMock()
    manager.shutdown_all = AsyncMock(return_value=3)
    manager.start_heartbeat_monitor = AsyncMock()
    manager.restore_active_sessions = AsyncMock(return_value=0)
    manager.send_command = AsyncMock(return_value={"success": True})
    manager.on = MagicMock()
    return manager


@pytest.fixture
def mock_session_service() -> MagicMock:
    """Create a mock session service."""
    service = MagicMock()
    service.get = AsyncMock()
    service.get_batch = AsyncMock(return_value=[])
    service.update = AsyncMock()
    service.delete = AsyncMock(return_value=True)
    service.delete_batch = AsyncMock(return_value=2)
    service.create = AsyncMock()
    return service


@pytest.fixture
def mock_message_service() -> MagicMock:
    """Create a mock message service."""
    service = MagicMock()
    service.get_messages_by_session = AsyncMock(return_value=[])
    service.count = AsyncMock(return_value=0)
    service.count_messages_by_execution = AsyncMock(return_value=0)
    service.search_messages = AsyncMock(return_value=([], 0))
    service.get_distinct_tool_names = AsyncMock(return_value=[])
    service.get_message_stats_by_session = AsyncMock(
        return_value={
            "total_messages": 0,
            "user_messages": 0,
            "agent_messages": 0,
            "tool_calls": 0,
        }
    )
    return service


@pytest.fixture
def mock_turn_service() -> MagicMock:
    """Create a mock turn service."""
    service = MagicMock()
    service.get_turns_by_session = AsyncMock(return_value=[])
    service.count_turns_by_session = AsyncMock(return_value=0)
    service.get_turn_time_range = AsyncMock(return_value=(None, None))
    service.get_turn_stats = AsyncMock(
        return_value={
            "is_reverted": False,
            "user_message": None,
            "total_steps": 0,
            "tool_call_stats": {},
            "current_file_path": None,
            "current_todo_list": [],
            "final_response": None,
            "last_message_id": None,
            "changed_files": {},
        }
    )
    service.get_file_diff = AsyncMock(return_value=None)
    return service


@pytest.fixture
def mock_agent_service() -> MagicMock:
    """Create a mock agent service."""
    service = MagicMock()
    service.get = AsyncMock()
    service.get_agents_by_session = AsyncMock(return_value=[])
    return service


@pytest.fixture
def mock_agent_config_service() -> MagicMock:
    """Create a mock agent config service."""
    service = MagicMock()
    service.get = AsyncMock()
    service.update = AsyncMock()
    return service


@pytest.fixture
def mock_job_service() -> MagicMock:
    """Create a mock job service."""
    service = MagicMock()
    service.get = AsyncMock()
    service.get_batch = AsyncMock(return_value=[])
    service.update = AsyncMock()
    service.pause_job = AsyncMock(return_value=True)
    service.resume_job = AsyncMock(return_value=True)
    return service


@pytest.fixture
def mock_job_execution_service() -> MagicMock:
    """Create a mock job execution service."""
    service = MagicMock()
    service.get_executions_by_job = AsyncMock(return_value=[])
    return service


@pytest.fixture
def mock_task_service() -> MagicMock:
    """Create a mock task service."""
    service = MagicMock()
    service.get = AsyncMock()
    service.get_batch = AsyncMock(return_value=[])
    service.update = AsyncMock()
    service.delete = AsyncMock(return_value=True)
    service.create_task = AsyncMock()
    service.get_child_tasks = AsyncMock(return_value=[])
    service.search_tasks = AsyncMock(return_value=[])
    service.add_comment = AsyncMock()
    service.update_task = AsyncMock()
    return service


@pytest.fixture
def mock_task_comment_service() -> MagicMock:
    """Create a mock task comment service."""
    service = MagicMock()
    service.get_comments_by_task = AsyncMock(return_value=[])
    return service


@pytest.fixture
def sample_session() -> MagicMock:
    """Create a sample session model mock."""
    session = MagicMock()
    session.session_id = "test-session-001"
    session.description = "Test session description"
    session.workspace = "/tmp/test-workspace"
    session.category = "normal"
    session.provider = "openrouter"
    session.model = "gpt-4"
    session.status = "active"
    session.created_at = datetime.now(UTC)
    session.updated_at = datetime.now(UTC)
    session.model_dump = MagicMock(
        return_value={
            "session_id": "test-session-001",
            "description": "Test session description",
            "workspace": "/tmp/test-workspace",
            "category": "normal",
            "provider": "openrouter",
            "model": "gpt-4",
            "status": "active",
        }
    )
    return session


@pytest.fixture
def sample_message() -> MagicMock:
    """Create a sample message model mock."""
    message = MagicMock()
    message.message_id = "msg-001"
    message.session_id = "test-session-001"
    message.role = "user"
    message.message_type = "user_message"
    message.content = "Hello"
    message.data = {}
    message.sequence_number = 1
    message.sender_id = "user"
    message.tool_name = None
    message.created_at = datetime.now(UTC)
    return message


@pytest.fixture
def sample_task() -> MagicMock:
    """Create a sample task model mock."""
    task = MagicMock()
    task.task_id = "task-001"
    task.name = "Test Task"
    task.description = "A test task"
    task.status = "pending"
    task.priority = "medium"
    task.assignee = "user1"
    task.parent_id = None
    task.session_id = "test-session-001"
    task.details = "Some details"
    task.acceptance_criteria = ["AC1", "AC2"]
    task.context_files = []
    task.context_links = []
    task.context_notes = ""
    task.report = ""
    task.dependencies = []
    task.created_at = datetime.now(UTC)
    task.updated_at = datetime.now(UTC)
    return task


@pytest.fixture
def sample_job() -> MagicMock:
    """Create a sample job model mock."""
    job = MagicMock()
    job.job_id = "job-001"
    job.name = "Test Job"
    job.job_type = "scheduled"
    job.status = "active"
    job.trigger_type = "cron"
    job.trigger_config = "0 */1 * * *"
    job.content = "echo hello"
    job.session_id = "test-session-001"
    job.agent_id = None
    job.created_at = datetime.now(UTC)
    job.updated_at = datetime.now(UTC)
    job.next_run_time = None
    return job


@pytest.fixture
def sample_agent() -> MagicMock:
    """Create a sample agent model mock."""
    agent = MagicMock()
    agent.agent_id = "agent-001"
    agent.session_id = "test-session-001"
    agent.name = "Test Agent"
    agent.role = "assistant"
    agent.config_id = "config-001"
    agent.agent_status = "idle"
    agent.model_dump = MagicMock(
        return_value={
            "agent_id": "agent-001",
            "session_id": "test-session-001",
            "name": "Test Agent",
            "role": "assistant",
            "config_id": "config-001",
            "agent_status": "idle",
        }
    )
    return agent


@pytest.fixture
def sample_agent_config() -> MagicMock:
    """Create a sample agent config model mock."""
    config = MagicMock()
    config.config_id = "config-001"
    config.name = "Test Config"
    config.config_content = '{"model": "gpt-4", "temperature": 0.7}'
    config.created_at = datetime.now(UTC)
    return config


@pytest.fixture
def sample_turn() -> MagicMock:
    """Create a sample turn model mock."""
    turn = MagicMock()
    turn.turn_id = "turn-001"
    turn.session_id = "test-session-001"
    turn.agent_id = "agent-001"
    turn.sequence_number = 1
    turn.status = "completed"
    turn.created_at = datetime.now(UTC)
    return turn


@pytest.fixture
def sample_crew_execution() -> MagicMock:
    """Create a sample crew execution model mock."""
    execution = MagicMock()
    execution.execution_id = "crew-exec-001"
    execution.session_id = "test-session-001"
    execution.crew_name = "Test Crew"
    execution.orchestrator_type = "pipeline"
    execution.yaml_content = "name: Test Crew\nagents: []"
    execution.status = "running"
    execution.error_message = None
    execution.result_json = None
    execution.phases_json = None
    execution.phases_total = 0
    execution.progress = 0
    execution.started_at = datetime.now(UTC)
    execution.completed_at = None
    return execution
