import asyncio
from datetime import datetime

from jinja2 import Template

from broca.logging_config import get_logger
from broca.process_manager import ProcessManager
from broca.scheduler import Scheduler
from broca.session.models import JobType
from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus
from broca.utils.shell_security import init_tree_sitter, validate_shell_command

logger = get_logger(__name__)


class Bash(Tool):
    def __init__(self):
        super().__init__()
        self.code_output_template = "return code: {{output.returncode}}\n{% if output.stdout -%}\noutput:{{ output.stdout if output.stdout.strip() else 'execution succeeded'}}\n{% endif %}\n{%- if output.stderr -%}error: {{output.stderr}}{% endif %}"
        init_tree_sitter()

    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return (
            "Use this tool to execute code using shell. "
            "**Note**: 1. Your default python path points to a special standalone python environment. "
            "When running python-related code, use the correct python environment.\n"
            "2. Only run shell code supported by the current platform.\n"
            "3. For long-running commands (dev servers, watchers, etc.), "
            "set `background: true` to run in background without timeout. "
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "the code to run",
                },
                "background": {
                    "type": "boolean",
                    "description": "Run in background without timeout. Use for long-running commands like dev servers, file watchers, or any command that doesn't terminate. The output is redirected to files and can be tracked via process tool. When False (default), commands have a 120s timeout.",
                    "default": False,
                },
                "notify": {
                    "type": "boolean",
                    "description": "When background=True, whether to send a notification when the process completes. Default: False (no notification). Use process tool to check status instead.",
                    "default": False,
                },
            },
            "required": ["code"],
        }

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        code = arguments["code"]
        background = arguments.get("background", False)
        notify = arguments.get("notify", False)

        # 检测命令是否包含 &（shell background operator）
        has_shell_bg = self._detect_background_ampersand(code)

        if background or has_shell_bg:
            if has_shell_bg:
                code = self._strip_background_ampersand(code)
            return await self._run_background(code, context, notify=notify)

        is_safe, reason, snippet = self._validate_code(code)
        if not is_safe:
            agent = context.agent
            permission_message = (
                f"Run potentially dangerous code: {reason}\n\n```bash\n{snippet}\n```"
            )
            if not await agent.ask_for_permission(permission_message):
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content="User refused to run potentially dangerous code",
                )

        return await self._run_code_async(code)

    def _validate_code(self, code: str) -> tuple[bool, str, str]:
        """Validate code using shared security module.

        Returns:
            tuple[bool, str, str]: (is_safe, reason, snippet) where reason describes why the code is
            flagged as dangerous, and snippet is the relevant code fragment that triggered the flag.
        """
        from broca.utils.shell_security import _tree_sitter_available

        # Use tree-sitter for more accurate parsing if available and code looks like shell
        use_tree_sitter = _tree_sitter_available and self._is_shell_command(code)
        return validate_shell_command(code, use_tree_sitter=use_tree_sitter)

    def _is_shell_command(self, code: str) -> bool:
        """Check if the code appears to be a shell command"""
        lines = code.strip().split("\n")
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Check for common shell command patterns
            if (
                not line.startswith("import")
                and not line.startswith("from")
                and not line.startswith("def ")
                and not line.startswith("class ")
                and not line.startswith("print(")
                and not line.startswith("print ")
                and "=" not in line[:20]
                and (" " in line or line.endswith(";"))
            ):
                return True
        return False

    def _detect_background_ampersand(self, code: str) -> bool:
        """检测命令是否以 shell background operator & 结尾

        检测规则：
        - 代码去除首尾空白后以 & 结尾
        - 允许结尾有分号、空格、注释（# 后内容被忽略）
        """
        stripped = code.strip()
        # 去掉注释
        if "#" in stripped:
            stripped = stripped.rsplit("#", 1)[0]
        return stripped.rstrip().rstrip(";").rstrip().endswith("&")

    def _strip_background_ampersand(self, code: str) -> str:
        """去除命令末尾的 & 和尾随空白"""
        # 先去除注释
        lines = code.rsplit("#", 1)
        main_code = lines[0]
        # 处理 &、;、空格的各种组合（如 "cmd &"、"cmd &;"、"cmd ;&"）
        while main_code and main_code[-1] in ";& ":
            main_code = main_code.rstrip(";& ").rstrip()
        # 如果本来有注释，保留它
        if len(lines) > 1:
            return main_code + "  # " + lines[1]
        return main_code

    async def _run_background(
        self, code: str, context: ToolCallContext, notify: bool = False
    ) -> ToolResult:
        """Schedule code execution via the scheduler for background running."""
        try:
            scheduler = Scheduler()
            if not scheduler.running:
                await scheduler.start()
            job_id = await scheduler.add_job(
                session_id=context.session_id,
                name=f"bg_code_{datetime.now().strftime('%H%M%S_%f')}",
                job_type=JobType.COMMAND,
                trigger_type="date",
                trigger_config={},
                content=code,
                agent_id=context.agent.agent_id,
                notify=notify,
            )
            # 基于 job_id 预测输出路径
            stdout_path = ProcessManager.OUTPUT_DIR / job_id / "stdout.log"
            stderr_path = ProcessManager.OUTPUT_DIR / job_id / "stderr.log"
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=(
                    f"Code scheduled for background execution\n"
                    f"Job ID: {job_id}\n"
                    f"stdout: {stdout_path}\n"
                    f"stderr: {stderr_path}\n"
                ),
            )
        except Exception as e:
            logger.error(f"Failed to schedule background execution: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Failed to schedule background execution: {e}",
            )

    async def _run_code_async(self, code: str, timeout: int = 120) -> ToolResult:
        """异步执行代码"""
        status: ToolStatus = ToolStatus.SUCCESS
        try:
            # 使用 asyncio.create_subprocess_shell 异步执行
            process = await asyncio.create_subprocess_shell(
                code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                shell=True,
            )

            try:
                # 等待进程完成，带超时
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )

                result_dict = {
                    "returncode": process.returncode,
                    "stdout": stdout.decode("utf-8", errors="replace")
                    if stdout
                    else "",
                    "stderr": stderr.decode("utf-8", errors="replace")
                    if stderr
                    else "",
                }
                status = ToolStatus.SUCCESS

            except asyncio.TimeoutError:
                # 超时处理
                try:
                    process.kill()
                    await process.wait()
                except Exception:
                    pass
                result_dict = {
                    "returncode": -1,
                    "stderr": f"Execution timed out after {timeout} seconds.",
                }
                status = ToolStatus.ERROR

        except Exception as e:
            result_dict = {
                "returncode": -1,
                "stderr": f"Execution failed: {e}",
            }
            status = ToolStatus.ERROR

        output = Template(self.code_output_template).render(output=result_dict)
        return ToolResult(status=status, content=output)
