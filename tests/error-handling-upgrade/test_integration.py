"""
集成测试 — 验证各模块修改后的错误处理路径完好

覆盖:
- broca/errors/ 包完整可导入
- session_runner 异常类继承 BrocaError
- orchestration 模块 raise OrchestrationError/ValidationError
- Tool.execute() 基类 catch BrocaError
- send_error / create_error_message dict 格式
- llm.py ValidationError
- commands/dispatcher BrocaError catch
"""

import asyncio
import json
import importlib

import pytest

from broca.errors import (
    BrocaError, LLMError, ToolError, SessionError,
    CommunicationError, OrchestrationError, ValidationError,
    BrocaPermissionError,
    ErrorCode, ErrorInfo,
)
from broca.tools.tool import Tool, ToolResult, ToolCallContext


# ── 辅助：创建测试用 Tool ──

def make_tool(name, execute_fn):
    """Factory to create a simple test tool with given execute implementation."""
    cls = type(
        name,
        (Tool,),
        {
            "name": property(lambda self: name),
            "description": property(lambda self: f"Test tool {name}"),
            "parameters": property(lambda self: {}),
            "_execute": execute_fn,
        },
    )
    return cls()


class TestBrocaErrorsPackage:
    """broca/errors/ 包集成"""

    def test_package_imports(self):
        """所有公开 API 可导入"""
        from broca.errors import (
            BrocaError, LLMError, ToolError, SessionError,
            CommunicationError, OrchestrationError, ValidationError,
            BrocaPermissionError, ErrorCode, ErrorInfo, safe_call,
        )
        assert BrocaError

    def test_init_exports_match_all(self):
        import broca.errors
        for name in ['BrocaError', 'LLMError', 'ToolError', 'SessionError',
                      'CommunicationError', 'OrchestrationError', 'ValidationError',
                      'BrocaPermissionError', 'ErrorCode', 'ErrorInfo', 'safe_call']:
            assert hasattr(broca.errors, name), f"__init__ 未导出 {name}"


class TestSessionRunnerIntegration:
    """session_runner 异常类集成"""

    def test_ipc_exceptions_inherit_communication_error(self):
        from broca.session_runner.ipc import IPCConnectionError, IPCTimeoutError
        assert issubclass(IPCConnectionError, CommunicationError)
        assert issubclass(IPCTimeoutError, CommunicationError)
        assert IPCConnectionError().error_code == ErrorCode.COMMUNICATION_ERROR

    def test_runner_manager_error_inherits_session_error(self):
        from broca.session_runner.manager import RunnerManagerError
        assert issubclass(RunnerManagerError, SessionError)

    def test_runner_imports_broca_error(self):
        source = importlib.util.find_spec('broca.session_runner.runner').loader.get_source('broca.session_runner.runner')
        assert 'from broca.errors import BrocaError' in source


class TestOrchestrationIntegration:
    """orchestration 模块 — ValueError/RuntimeError → BrocaError 子类"""

    @pytest.mark.parametrize("module_path", [
        "broca.orchestration.graph_orchestrator",
        "broca.orchestration.supervisor_worker",
        "broca.orchestration.round_table",
        "broca.orchestration.composite",
        "broca.orchestration.orchestrator",
    ])
    def test_orchestration_modules_import(self, module_path):
        importlib.import_module(module_path)

    @pytest.mark.parametrize("mod_name", [
        "graph_orchestrator", "supervisor_worker",
        "round_table", "composite", "orchestrator",
    ])
    def test_no_value_error_in_orchestration(self, mod_name):
        source = importlib.util.find_spec(f'broca.orchestration.{mod_name}').loader.get_source(f'broca.orchestration.{mod_name}')
        assert 'raise RuntimeError' not in source, f"{mod_name} 仍有 raise RuntimeError"
        assert 'raise ValueError' not in source, f"{mod_name} 仍有 raise ValueError"

    def test_orchestrator_factory_raises_validation_error(self):
        from broca.orchestration.crew import CrewConfig, OrchestratorConfig
        from broca.orchestration.orchestrator import OrchestratorFactory

        config = CrewConfig(
            name="test", description="test",
            orchestrator=OrchestratorConfig(type="unsupported_type"),
            agents=[],
        )
        with pytest.raises(ValidationError) as exc_info:
            OrchestratorFactory.create(config, None)
        assert exc_info.value.error_code == ErrorCode.VALIDATION_CONFIG_ERROR


class TestToolIntegration:
    """Tool.execute() 基类错误处理"""

    def test_tool_execute_catches_broca_error(self):
        tool = make_tool("broken", lambda self, args, ctx: (_ for _ in ()).throw(ToolError("工具内部错误")))
        result = asyncio.run(tool.execute('{}', ToolCallContext()))
        assert result.status == 'error'
        assert '工具内部错误' in result.content

    def test_tool_execute_cancelled_error_passthrough(self):
        tool = make_tool("cancel", lambda self, args, ctx: (_ for _ in ()).throw(asyncio.CancelledError()))
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(tool.execute('{}', ToolCallContext()))

    def test_tool_execute_general_exception_fallback(self):
        tool = make_tool("crash", lambda self, args, ctx: (_ for _ in ()).throw(ValueError("意外崩溃")))
        result = asyncio.run(tool.execute('{}', ToolCallContext()))
        assert result.status == 'error'
        assert 'Error executing tool' in result.content


class TestLLMIntegration:
    """llm.py ValidationError"""

    def test_llm_client_raises_validation_error(self):
        from broca.llm import LLMClient
        client = LLMClient()
        client.config = {}
        with pytest.raises(ValidationError) as exc_info:
            client.parse_message(provider="nonexistent", model="nonexistent", message=None)
        assert exc_info.value.error_code == ErrorCode.VALIDATION_CONFIG_ERROR

    def test_llm_module_no_value_error(self):
        source = importlib.util.find_spec('broca.llm').loader.get_source('broca.llm')
        assert 'raise ValueError' not in source


class TestCommandDispatcherIntegration:
    """commands/dispatcher BrocaError catch"""

    def test_dispatcher_catches_broca_error(self):
        from broca.commands.dispatcher import dispatch_command
        from broca.commands.registry import CommandRegistry
        from broca.commands.base import CommandContext, LocalCommand, CommandResult

        class BrokenCommand(LocalCommand):
            async def execute(self, args, ctx):
                raise ToolError("命令工具错误")

        registry = CommandRegistry()
        registry.register(BrokenCommand(name="broken", description="test"))

        ctx = CommandContext(workspace="/tmp", session_id="test", agent_id="test", agent=None, context=None)
        result = asyncio.run(dispatch_command("broken", "", registry, ctx))
        assert result is not None
        assert result.type == "error"
        assert "命令工具错误" in result.value


class TestCommunicationErrorSerialization:
    """send_error / create_error_message dict 格式"""

    def test_create_error_message_accepts_dict(self):
        from broca.session.models import MessageProtocol
        error_info = {
            "code": "TOOL_TIMEOUT", "severity": "error",
            "message": "工具执行超时", "recovery_hint": "可尝试增大工具超时配置",
            "details": {"tool_name": "test"}, "cause": None, "traceback": None,
        }
        msg = MessageProtocol.create_error_message(error_info=error_info)
        assert msg.data["content"] == "工具执行超时"
        assert msg.data["error_code"] == "TOOL_TIMEOUT"
        assert msg.data["severity"] == "error"
        assert msg.data["recovery_hint"] == "可尝试增大工具超时配置"
        assert msg.data["details"] == {"tool_name": "test"}

    def test_broca_error_to_dict_directly_usable(self):
        from broca.session.models import MessageProtocol
        e = ToolError("出错了", error_code=ErrorCode.TOOL_TIMEOUT, details={"tool": "test"}, cause=ValueError("原始"))
        msg = MessageProtocol.create_error_message(error_info=e.to_dict())
        assert msg.data["error_code"] == "TOOL_TIMEOUT"
        assert msg.data["severity"] == "error"
        assert msg.data["recovery_hint"] == "可尝试增大工具超时配置"

    def test_error_info_roundtrip(self):
        info = ErrorInfo(code=ErrorCode.COMMUNICATION_DISCONNECTED, message="连接已断开",
                         details={"sid": "abc"}, cause_msg="connection reset", traceback_str="Traceback...")
        d = info.to_dict()
        assert d["code"] == "COMMUNICATION_DISCONNECTED"
        assert d["severity"] == "error"
        assert d["recovery_hint"] == "正在尝试重连..."
        assert d["details"] == {"sid": "abc"}
        assert d["cause"] == "connection reset"


class TestCrossCutting:
    """横切关注点"""

    def test_no_value_error_in_modified_files(self):
        modified_files = [
            'broca/llm.py', 'broca/communication/socketio_client.py',
            'broca/session/revert_service.py', 'broca/session/session_manager.py',
            'broca/commands/loader.py', 'broca/skill/skill_manager.py',
            'broca/skill/skill_store.py', 'broca/tools/tool_manager.py',
            'broca/tools/tool_permission_manager.py', 'broca/tools/cron.py',
            'broca/persistent_memory/types.py', 'broca/scheduler.py',
        ]
        for fpath in modified_files:
            with open(fpath) as f:
                source = f.read()
            lines = source.split('\n')
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith('raise ValueError') and '#' not in stripped and '"""' not in stripped:
                    pytest.fail(f"{fpath}:{i}: 仍有 raise ValueError: {stripped}")

    def test_all_subclasses_uniform_interface(self):
        for exc_cls in [LLMError, ToolError, SessionError, CommunicationError,
                        OrchestrationError, ValidationError, BrocaPermissionError]:
            e = exc_cls("test")
            assert hasattr(e, 'to_dict')
            assert hasattr(e, 'to_user_message')
            assert hasattr(e, 'error_code')
            assert hasattr(e, 'info')
            assert hasattr(e, 'message')
            d = e.to_dict()
            for key in ['code', 'severity', 'message', 'recovery_hint',
                        'details', 'cause', 'traceback']:
                assert key in d, f"{exc_cls.__name__} 缺少 to_dict 字段: {key}"
