"""Regression tests: bash security check is configurable per agent.

Behavior:
- ``AgentConfig.bash_security_check`` defaults to ``True`` (check enabled).
- When an agent sets it to ``False``, ``Bash.pre_execute_check`` returns
  ``None`` (no permission prompt) even for dangerous commands.
- When the agent/config is unavailable, the check stays enabled (safe default).
"""

from types import SimpleNamespace

from broca.agent_configs import AgentConfig
from broca.tools.bash import Bash
from broca.tools.tool import ToolCallContext


def _make_context(bash_security_check=None):
    """Build a ToolCallContext whose agent config carries the given flag.

    ``bash_security_check=None`` means "no explicit config" — used to verify
    the safe default path.
    """
    context = ToolCallContext()
    if bash_security_check is not None:
        config = AgentConfig()
        config.bash_security_check = bash_security_check
        context.agent = SimpleNamespace(config=config)
    return context


class TestAgentConfigDefault:
    def test_agent_config_defaults_to_enabled(self):
        """AgentConfig must default to enabled so behavior is unchanged."""
        assert AgentConfig().bash_security_check is True

    def test_from_config_reads_flag(self):
        """Flag can be set via agent config dict (frontmatter)."""
        cfg = AgentConfig.from_config({"bash_security_check": False})
        assert cfg.bash_security_check is False

    def test_to_dict_includes_flag(self):
        """Flag is serialized so it survives DB/file round-trips."""
        assert AgentConfig().to_dict()["bash_security_check"] is True


class TestBashPreExecuteCheckConfig:
    def setup_method(self):
        self.tool = Bash()

    def test_dangerous_command_flagged_when_enabled(self):
        ctx = _make_context(bash_security_check=True)
        result = self.tool.pre_execute_check('{"code": "rm -rf /"}', ctx)
        assert result is not None

    def test_dangerous_command_skipped_when_disabled(self):
        ctx = _make_context(bash_security_check=False)
        result = self.tool.pre_execute_check('{"code": "rm -rf /"}', ctx)
        assert result is None

    def test_default_context_without_agent_is_enabled(self):
        """No agent on context → check still runs (safe default)."""
        ctx = _make_context(bash_security_check=None)
        result = self.tool.pre_execute_check('{"code": "rm -rf /"}', ctx)
        assert result is not None

    def test_disabled_still_skips_safe_commands(self):
        ctx = _make_context(bash_security_check=False)
        result = self.tool.pre_execute_check('{"code": "echo hello"}', ctx)
        assert result is None
