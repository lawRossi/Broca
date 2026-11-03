"""
Regression tests for Phase 1 bug fixes in refactor branch.

Covers:
- Task 1.1: AssignTask UnboundLocalError fix
- Task 1.2: SkillManage path traversal fix
- Task 1.3: BlackboardChanges timestamp type handling
- Task 1.4: _check_type boolean bypass fix
- Task 1.5: todo.py error message fix
"""

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ============================================================================
# Task 1.1: AssignTask UnboundLocalError
# ============================================================================


class TestAssignTaskUnboundLocalError:
    """Verify AssignTask blocking mode doesn't crash when message is None/empty."""

    def _make_context(self):
        """Create a mock ToolCallContext with the necessary agent attributes."""
        context = MagicMock()
        # Mock the calling agent
        context.agent = MagicMock()
        context.agent.agent_id = "agent-1"
        context.agent.name = "main"
        context.agent.session_id = "session-1"
        context.session_id = "session-1"
        context.workspace = "/tmp"
        context.execution_id = None
        context.namespace = None
        return context

    def _make_target_agent(self, message_return):
        """Create a mock target agent with specified get_latest_assistant_message return."""
        target = MagicMock()
        target.agent_id = "agent-2"
        target.context.get_latest_assistant_message.return_value = message_return

        # Mock run to return a COMPLETED result
        from broca.loop_engine import ExecutionStatus

        result = MagicMock()
        result.status = ExecutionStatus.COMPLETED
        target.run = AsyncMock(return_value=result)
        return target

    def _patch_component_registry(self, target_agent):
        """Patch ComponentRegistry to return our mock factory."""
        mock_registry = MagicMock()
        mock_factory = MagicMock()
        mock_factory.get_agent.return_value = target_agent
        mock_registry.get.return_value = mock_factory
        return patch("broca.components.ComponentRegistry.get_instance", return_value=mock_registry)

    @pytest.mark.asyncio
    async def test_message_none(self):
        """AC: message=None → content='Task completed.' (no crash)."""
        from broca.tools.agent_interaction import AssignTask
        from broca.tools.tool import ToolStatus

        context = self._make_context()
        target_agent = self._make_target_agent(None)

        with self._patch_component_registry(target_agent):
            tool = AssignTask()
            result = await tool.execute(
                '{"agent": "sub", "task": "do something"}', context
            )

        assert result.status == ToolStatus.SUCCESS
        assert result.content == "Task completed."

    @pytest.mark.asyncio
    async def test_message_nonempty(self):
        """AC: message='hello' → content='Message from agent: hello'."""
        from broca.tools.agent_interaction import AssignTask
        from broca.tools.tool import ToolStatus

        context = self._make_context()
        target_agent = self._make_target_agent("hello")

        with self._patch_component_registry(target_agent):
            tool = AssignTask()
            result = await tool.execute(
                '{"agent": "sub", "task": "do something"}', context
            )

        assert result.status == ToolStatus.SUCCESS
        assert result.content == "Message from agent: hello"

    @pytest.mark.asyncio
    async def test_message_empty_string(self):
        """AC: message='' → content='Task completed.' (no crash)."""
        from broca.tools.agent_interaction import AssignTask
        from broca.tools.tool import ToolStatus

        context = self._make_context()
        target_agent = self._make_target_agent("")

        with self._patch_component_registry(target_agent):
            tool = AssignTask()
            result = await tool.execute(
                '{"agent": "sub", "task": "do something"}', context
            )

        assert result.status == ToolStatus.SUCCESS
        assert result.content == "Task completed."


# ============================================================================
# Task 1.2: SkillManage Path Traversal
# ============================================================================


class TestSkillManagePathTraversal:
    """Verify _handle_subfile rejects path traversal attempts."""

    def _setup_skill_dir(self, tmp_path: Path, skill_name: str) -> Path:
        """Create a skill directory and return its path."""
        skill_dir = tmp_path / skill_name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Test Skill", encoding="utf-8")
        return skill_dir

    def _make_store_with_dir(self, skills_dir: Path, skill_name: str):
        """Create a mock SkillStore pointing to the given directory."""
        from broca.tools.skill import SkillManage

        tool = SkillManage()
        # Override the store's skills_dir
        tool.store.skills_dir = skills_dir
        # Mock is_registered to return True
        tool.store.is_registered = MagicMock(return_value=True)
        return tool

    @pytest.mark.asyncio
    async def test_reject_other_skill(self, tmp_path):
        """AC: ../other-skill/file.txt is rejected."""
        from broca.tools.skill import SkillManage
        from broca.tools.tool import ToolStatus

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        # Create the target skill
        skill_dir = self._setup_skill_dir(skills_dir, "my-skill")
        # Create a sibling directory to simulate escape target
        other_dir = skills_dir / "other-skill"
        other_dir.mkdir()

        tool = self._make_store_with_dir(skills_dir, "my-skill")
        tool.store.skills_dir = skills_dir

        context = MagicMock()
        result = await tool._execute(
            {
                "action": "write_file",
                "name": "my-skill",
                "file_path": "../other-skill/evil.txt",
                "file_content": "hacked",
            },
            context,
        )
        assert result.status == ToolStatus.ERROR
        assert "escapes skill directory" in result.content

    @pytest.mark.asyncio
    async def test_reject_prefix_similar(self, tmp_path):
        """AC: ../my-skill-evil/file.txt is rejected (prefix-similar dir)."""
        from broca.tools.skill import SkillManage
        from broca.tools.tool import ToolStatus

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_dir = self._setup_skill_dir(skills_dir, "my-skill")
        # Create a similar-named sibling
        evil_dir = skills_dir / "my-skill-evil"
        evil_dir.mkdir()

        tool = self._make_store_with_dir(skills_dir, "my-skill")
        tool.store.skills_dir = skills_dir

        context = MagicMock()
        result = await tool._execute(
            {
                "action": "write_file",
                "name": "my-skill",
                "file_path": "../my-skill-evil/evil.txt",
                "file_content": "hacked",
            },
            context,
        )
        assert result.status == ToolStatus.ERROR
        assert "escapes skill directory" in result.content

    @pytest.mark.asyncio
    async def test_allow_valid_subpath(self, tmp_path):
        """AC: references/guide.md is allowed (valid subpath)."""
        from broca.tools.skill import SkillManage
        from broca.tools.tool import ToolStatus

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_dir = self._setup_skill_dir(skills_dir, "my-skill")
        # Create the subdirectory
        (skill_dir / "references").mkdir()

        tool = self._make_store_with_dir(skills_dir, "my-skill")
        tool.store.skills_dir = skills_dir

        context = MagicMock()
        result = await tool._execute(
            {
                "action": "write_file",
                "name": "my-skill",
                "file_path": "references/guide.md",
                "file_content": "# Guide",
            },
            context,
        )
        assert result.status == ToolStatus.SUCCESS
        # Verify file was actually written
        written_file = skill_dir / "references" / "guide.md"
        assert written_file.exists()
        assert written_file.read_text(encoding="utf-8") == "# Guide"

    @pytest.mark.asyncio
    async def test_reject_etc_passwd(self, tmp_path):
        """AC: ../../etc/passwd is rejected."""
        from broca.tools.skill import SkillManage
        from broca.tools.tool import ToolStatus

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        self._setup_skill_dir(skills_dir, "my-skill")

        tool = self._make_store_with_dir(skills_dir, "my-skill")
        tool.store.skills_dir = skills_dir

        context = MagicMock()
        result = await tool._execute(
            {
                "action": "write_file",
                "name": "my-skill",
                "file_path": "../../../../etc/passwd",
                "file_content": "hacked",
            },
            context,
        )
        assert result.status == ToolStatus.ERROR


# ============================================================================
# Task 1.3: BlackboardChanges timestamp type handling
# ============================================================================


class TestBlackboardChangesTimestamp:
    """Verify BlackboardChanges handles both datetime and ISO string timestamps."""

    def _make_context(self, blackboard):
        context = MagicMock()
        context.session_id = "session-1"
        context.execution_id = "exec-1"
        context.namespace = "test_ns"
        context.agent = MagicMock()
        context.agent.name = "test_agent"
        return context

    def _make_blackboard(self, changes):
        """Create a mock blackboard that returns the given changes."""
        bb = MagicMock()
        bb.get_version = AsyncMock(return_value=5)
        bb.get_changes = AsyncMock(return_value=changes)
        return bb

    @pytest.mark.asyncio
    async def test_datetime_timestamp(self):
        """AC: datetime object → correct HH:MM:SS output."""
        from broca.tools.blackboard import BlackboardChanges, set_blackboard

        ts = datetime(2024, 1, 15, 14, 30, 0)
        changes = [
            {
                "key": "test_ns.mykey",
                "event_type": "SET",
                "value": "hello",
                "producer": "agent_a",
                "timestamp": ts,
            }
        ]
        bb = self._make_blackboard(changes)
        set_blackboard("session-1", "exec-1", bb)

        try:
            tool = BlackboardChanges()
            context = self._make_context(bb)
            result = await tool._execute({"since_version": 0}, context)

            assert result.status.value == "success"
            assert "14:30:00" in result.content
        finally:
            from broca.tools.blackboard import remove_blackboard

            remove_blackboard("session-1", "exec-1")

    @pytest.mark.asyncio
    async def test_iso_string_timestamp(self):
        """AC: ISO string → correct HH:MM:SS output."""
        from broca.tools.blackboard import BlackboardChanges, set_blackboard

        changes = [
            {
                "key": "test_ns.mykey",
                "event_type": "SET",
                "value": "hello",
                "producer": "agent_a",
                "timestamp": "2024-01-15T14:30:00",
            }
        ]
        bb = self._make_blackboard(changes)
        set_blackboard("session-1", "exec-1", bb)

        try:
            tool = BlackboardChanges()
            context = self._make_context(bb)
            result = await tool._execute({"since_version": 0}, context)

            assert result.status.value == "success"
            assert "14:30:00" in result.content
        finally:
            from broca.tools.blackboard import remove_blackboard

            remove_blackboard("session-1", "exec-1")


# ============================================================================
# Task 1.4: _check_type boolean bypass
# ============================================================================


class TestCheckTypeBooleanBypass:
    """Verify boolean values don't pass integer/number type checks."""

    def test_true_integer(self):
        """AC: _check_type(True, 'integer') → False."""
        from broca.tools.tool import Tool

        assert Tool._check_type(True, "integer") is False

    def test_false_number(self):
        """AC: _check_type(False, 'number') → False."""
        from broca.tools.tool import Tool

        assert Tool._check_type(False, "number") is False

    def test_true_boolean(self):
        """AC: _check_type(True, 'boolean') → True."""
        from broca.tools.tool import Tool

        assert Tool._check_type(True, "boolean") is True

    def test_int_boolean(self):
        """AC: _check_type(1, 'boolean') → False."""
        from broca.tools.tool import Tool

        assert Tool._check_type(1, "boolean") is False

    def test_int_integer(self):
        """AC: _check_type(42, 'integer') → True."""
        from broca.tools.tool import Tool

        assert Tool._check_type(42, "integer") is True

    def test_true_list_boolean(self):
        """AC: _check_type(True, ['string', 'boolean']) → True."""
        from broca.tools.tool import Tool

        assert Tool._check_type(True, ["string", "boolean"]) is True


# ============================================================================
# Task 1.5: todo.py error message
# ============================================================================


class TestTodoErrorMessage:
    """Verify error message includes all valid status values."""

    def test_invalid_status_message_includes_in_progress(self):
        """AC: status='unknown' → error contains 'pending, in_progress, completed'."""
        from broca.tools.todo import TodoManagement

        tool = TodoManagement()
        result = tool._validate_todos([{"name": "x", "status": "unknown"}])
        assert result is not None
        assert "pending" in result
        assert "in_progress" in result
        assert "completed" in result

    def test_in_progress_is_valid(self):
        """AC: status='in_progress' → validation passes (returns None)."""
        from broca.tools.todo import TodoManagement

        tool = TodoManagement()
        result = tool._validate_todos([{"name": "x", "status": "in_progress"}])
        assert result is None
