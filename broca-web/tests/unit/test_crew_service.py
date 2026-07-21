"""Unit tests for app.services.crew_service module.

Tests CrewService: config validation, workspace config management,
execution record handling, and IPC event processing.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from app.services.crew_service import CrewService, get_crew_service


class TestCrewServiceValidation:
    """Test YAML validation methods."""

    def test_validate_valid_yaml(self):
        """Valid YAML should pass validation."""
        with patch("app.services.crew_service.CrewConfigValidator") as mock_validator:
            mock_validator.validate_yaml.return_value = []
            errors = CrewService.validate_crew_yaml("name: valid\nagents: []")
            assert errors == []
            mock_validator.validate_yaml.assert_called_once_with("name: valid\nagents: []")

    def test_validate_invalid_yaml(self):
        """Invalid YAML should return error list."""
        with patch("app.services.crew_service.CrewConfigValidator") as mock_validator:
            mock_validator.validate_yaml.return_value = ["Agent 'worker' not found", "Missing orchestrator"]
            errors = CrewService.validate_crew_yaml("name: bad")
            assert len(errors) == 2
            assert "Agent" in errors[0]

    def test_validate_empty_yaml(self):
        """Empty YAML should return errors."""
        with patch("app.services.crew_service.CrewConfigValidator") as mock_validator:
            mock_validator.validate_yaml.return_value = ["Empty configuration"]
            errors = CrewService.validate_crew_yaml("")
            assert len(errors) == 1

    def test_validate_yaml_file(self):
        """File-based validation should work."""
        with (
            patch("app.services.crew_service.CrewConfigValidator") as mock_validator,
            tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f,
        ):
            f.write("name: test\nagents: []")
            f.flush()
            mock_validator.validate_yaml_file.return_value = []
            errors = CrewService.validate_crew_yaml_file(f.name)
            assert errors == []
            mock_validator.validate_yaml_file.assert_called_once_with(f.name)
            os.unlink(f.name)


class TestCrewServiceConfigManagement:
    """Test workspace crew_configs directory management."""

    def test_list_crew_configs_empty_dir(self):
        """Empty crew_configs directory should return empty list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            configs = CrewService.list_crew_configs(tmpdir)
            assert configs == []

    def test_list_crew_configs_no_dir(self):
        """Non-existent crew_configs directory should return empty list."""
        configs = CrewService.list_crew_configs("/nonexistent/path")
        assert configs == []

    def test_list_crew_configs_filters_non_yaml(self):
        """Non-YAML files should be filtered out."""
        with tempfile.TemporaryDirectory() as tmpdir:
            configs_dir = os.path.join(tmpdir, "crew_configs")
            os.makedirs(configs_dir)

            # Create valid yaml
            with open(os.path.join(configs_dir, "test.yaml"), "w") as f:
                f.write("name: test\nagents: []")

            # Create non-yaml file — should be ignored
            with open(os.path.join(configs_dir, "readme.txt"), "w") as f:
                f.write("not a config")

            with patch("app.services.crew_service.CrewConfig.from_yaml_file") as mock_from_file:
                mock_config = MagicMock()
                mock_config.name = "test"
                mock_config.description = "A test config"
                mock_config.orchestrator = MagicMock()
                mock_config.orchestrator.type.value = "pipeline"
                mock_config.agents = []
                mock_from_file.return_value = mock_config

                configs = CrewService.list_crew_configs(tmpdir)
                assert len(configs) == 1
                assert configs[0]["filename"] == "test.yaml"
                assert configs[0]["name"] == "test"

    def test_list_crew_configs_parse_error(self):
        """Files with parse errors should be included with error info."""
        with tempfile.TemporaryDirectory() as tmpdir:
            configs_dir = os.path.join(tmpdir, "crew_configs")
            os.makedirs(configs_dir)

            broken_yaml_path = os.path.join(configs_dir, "broken.yaml")
            with open(broken_yaml_path, "w") as f:
                f.write("name: broken")

            # CrewConfig.from_yaml_file raises an exception for broken files
            with patch("app.services.crew_service.CrewConfig.from_yaml_file") as mock_from_file:
                mock_from_file.side_effect = Exception("Parse error: invalid YAML")
                configs = CrewService.list_crew_configs(tmpdir)
                assert len(configs) == 1
                assert "parse_error" in configs[0]

    def test_get_crew_config_content(self):
        """Config content should be returned with metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            configs_dir = os.path.join(tmpdir, "crew_configs")
            os.makedirs(configs_dir)

            yaml_content = "name: my_crew\ndescription: A sample crew\nagents: []"
            with open(os.path.join(configs_dir, "sample.yaml"), "w") as f:
                f.write(yaml_content)

            with patch("app.services.crew_service.CrewConfig.from_yaml") as mock_from_yaml:
                mock_config = MagicMock()
                mock_config.name = "my_crew"
                mock_config.description = "A sample crew"
                mock_config.orchestrator = MagicMock()
                mock_config.orchestrator.type.value = "pipeline"
                mock_config.agents = []
                mock_from_yaml.return_value = mock_config

                result = CrewService.get_crew_config_content(tmpdir, "sample.yaml")
                assert result["filename"] == "sample.yaml"
                assert result["content"] == yaml_content
                assert result["summary"]["name"] == "my_crew"

    def test_get_crew_config_content_invalid_filename(self):
        """Filenames with path separators should be rejected."""
        with pytest.raises(ValueError, match="Invalid filename"):
            CrewService.get_crew_config_content("/tmp", "../etc/passwd")

    def test_get_crew_config_content_not_found(self):
        """Non-existent file should raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="not found"):
            CrewService.get_crew_config_content("/tmp", "nonexistent.yaml")

    def test_save_crew_config(self):
        """Valid config should be saved to disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_content = "name: new_crew\ndescription: A new crew\nagents: []"

            with patch("app.services.crew_service.CrewConfig.from_yaml") as mock_from_yaml:
                mock_config = MagicMock()
                mock_config.name = "new_crew"
                mock_config.description = "A new crew"
                mock_config.orchestrator = MagicMock()
                mock_config.orchestrator.type.value = "pipeline"
                mock_config.agents = []
                mock_from_yaml.return_value = mock_config

                result = CrewService.save_crew_config(tmpdir, "new_crew.yaml", yaml_content)

                assert result["filename"] == "new_crew.yaml"
                assert os.path.exists(result["path"])

                with open(result["path"]) as f:
                    assert f.read() == yaml_content

    def test_save_crew_config_invalid_filename(self):
        """Filenames with path separators should be rejected."""
        with pytest.raises(ValueError, match="Invalid filename"):
            CrewService.save_crew_config("/tmp", "config.yaml/../../evil", "content")

    def test_save_crew_config_invalid_extension(self):
        """Non-yaml extension should be rejected."""
        with pytest.raises(ValueError, match="Filename must end with"):
            CrewService.save_crew_config("/tmp", "config.txt", "content")

    def test_save_crew_config_invalid_yaml(self):
        """Invalid YAML content should be rejected."""
        with patch("app.services.crew_service.CrewConfig.from_yaml") as mock_from_yaml:
            mock_from_yaml.side_effect = Exception("Invalid YAML")
            with pytest.raises(ValueError, match="Invalid YAML content"):
                CrewService.save_crew_config("/tmp", "test.yaml", "invalid: [yaml")


class TestCrewServiceExecutionDict:
    """Test _execution_to_dict conversion."""

    def test_basic_conversion(self):
        """Basic execution should convert to dict correctly."""
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

        with patch("app.services.crew_service.CrewConfig.from_yaml") as mock_from_yaml:
            mock_config = MagicMock()
            mock_config.name = "Test Crew"
            mock_config.description = "A test"
            mock_config.agents = [MagicMock()]
            mock_from_yaml.return_value = mock_config

            result = CrewService._execution_to_dict(execution)
            assert result["execution_id"] == "crew-exec-001"
            assert result["session_id"] == "test-session-001"
            assert result["crew_name"] == "Test Crew"
            assert result["status"] == "running"
            assert result["agent_count"] == 1

    def test_conversion_with_error(self):
        """Execution with error should include error message."""
        execution = MagicMock()
        execution.execution_id = "crew-exec-002"
        execution.session_id = "test-session-001"
        execution.crew_name = "Failed Crew"
        execution.orchestrator_type = "pipeline"
        execution.yaml_content = "name: Failed Crew\nagents: []"
        execution.status = "failed"
        execution.error_message = "Something went wrong"
        execution.result_json = None
        execution.phases_json = None
        execution.phases_total = 0
        execution.progress = 0
        execution.started_at = datetime.now(UTC)
        execution.completed_at = datetime.now(UTC)

        with patch("app.services.crew_service.CrewConfig.from_yaml") as mock_from_yaml:
            mock_config = MagicMock()
            mock_config.name = "Failed Crew"
            mock_config.description = ""
            mock_config.agents = []
            mock_from_yaml.return_value = mock_config

            result = CrewService._execution_to_dict(execution)
            assert result["status"] == "failed"
            assert result["error"] == "Something went wrong"

    def test_conversion_with_phases(self):
        """Execution with phases should parse them."""
        execution = MagicMock()
        execution.execution_id = "crew-exec-003"
        execution.session_id = "test-session-001"
        execution.crew_name = "Phased Crew"
        execution.orchestrator_type = "pipeline"
        execution.yaml_content = "name: Phased Crew\nagents: []"
        execution.status = "completed"
        execution.error_message = None
        execution.result_json = None
        execution.phases_json = '[{"name": "phase1"}, {"name": "phase2"}]'
        execution.phases_total = 2
        execution.progress = 1.0
        execution.started_at = datetime.now(UTC)
        execution.completed_at = datetime.now(UTC)

        with patch("app.services.crew_service.CrewConfig.from_yaml") as mock_from_yaml:
            mock_config = MagicMock()
            mock_config.name = "Phased Crew"
            mock_config.description = ""
            mock_config.agents = []
            mock_from_yaml.return_value = mock_config

            result = CrewService._execution_to_dict(execution)
            assert len(result["phases"]) == 2
            assert result["phases"][0]["name"] == "phase1"

    def test_conversion_with_result(self):
        """Execution with result should parse it."""
        execution = MagicMock()
        execution.execution_id = "crew-exec-004"
        execution.session_id = "test-session-001"
        execution.crew_name = "Result Crew"
        execution.orchestrator_type = "pipeline"
        execution.yaml_content = "name: Result Crew\nagents: []"
        execution.status = "completed"
        execution.error_message = None
        execution.result_json = '{"output": "success", "score": 95}'
        execution.phases_json = None
        execution.phases_total = 0
        execution.progress = 1.0
        execution.started_at = datetime.now(UTC)
        execution.completed_at = datetime.now(UTC)

        with patch("app.services.crew_service.CrewConfig.from_yaml") as mock_from_yaml:
            mock_config = MagicMock()
            mock_config.name = "Result Crew"
            mock_config.description = ""
            mock_config.agents = []
            mock_from_yaml.return_value = mock_config

            result = CrewService._execution_to_dict(execution)
            assert result["result"]["output"] == "success"
            assert result["result"]["score"] == 95


class TestCrewServiceSingleton:
    """Test get_crew_service singleton pattern."""

    def test_get_crew_service_returns_same_instance(self):
        """Multiple calls should return the same instance."""
        service1 = get_crew_service()
        service2 = get_crew_service()
        assert service1 is service2
