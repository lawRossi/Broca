import asyncio
import os
import shutil
import signal
import sys
import tempfile
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
            }
        }

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        code = arguments.get("code") or arguments.get("command")
        background = arguments.get("background", False)
        notify = False

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

    # shell 中「词首」分隔符：位于这些字符之后的 # 才是注释
    _SHELL_WORD_BREAK = " \t\r\n;&|()<>"

    @classmethod
    def _find_comment_start(cls, line: str) -> int:
        """返回一行中第一个「真正的」注释 '#' 的下标，没有则返回 -1。

        简化规则（不依赖 tree-sitter）：
        - 引号（'...' / "..."）内的 # 不是注释；
        - 反斜杠转义的下一个字符跳过；
        - 只有当 # 处于「词首」（行首，或前一个字符是空白 / ; & | ( ) < >）
          时才算注释。

        这样就能避免把文件名、URL、a#b 里的 # 误判为注释。
        """
        in_single = in_double = False
        i, n = 0, len(line)
        while i < n:
            ch = line[i]
            if in_single:
                if ch == "'":
                    in_single = False
                i += 1
                continue
            if in_double:
                if ch == "\\":
                    i += 2
                    continue
                if ch == '"':
                    in_double = False
                i += 1
                continue
            if ch == "\\":
                i += 2
                continue
            if ch == "'":
                in_single = True
            elif ch == '"':
                in_double = True
            elif ch == "#":
                prev = line[i - 1] if i > 0 else ""
                if prev == "" or prev in cls._SHELL_WORD_BREAK:
                    return i
            i += 1
        return -1

    @classmethod
    def _strip_comments(cls, code: str) -> str:
        """按行去掉真正的注释（保留行结构与换行）。"""
        out = []
        for line in code.split("\n"):
            ci = cls._find_comment_start(line)
            out.append(line[:ci].rstrip() if ci != -1 else line)
        return "\n".join(out)

    def _detect_background_ampersand(self, code: str) -> bool:
        """检测命令是否以 shell background operator & 结尾

        检测规则：
        - 去掉真正的注释后，去除首尾空白，以 & 结尾（允许结尾有分号）
        - # 只有在「词首」且不在引号内时才算注释
        """
        stripped = self._strip_comments(code).strip()
        return stripped.rstrip().rstrip(";").rstrip().endswith("&")

    def _strip_background_ampersand(self, code: str) -> str:
        """去除命令末尾的 background operator & 及尾随空白/分号，保留注释。"""
        # 定位最后一行末尾的注释（若有），把代码与注释分开
        body = code.rstrip()
        nl = body.rfind("\n")
        last_line = body[nl + 1:]
        ci = self._find_comment_start(last_line)
        if ci != -1:
            split = nl + 1 + ci
            head, tail = code[:split], code[split:]
        else:
            head, tail = body, ""

        # 处理 &、;、空格的各种组合（如 "cmd &"、"cmd &;"、"cmd ;&"）
        while head and head[-1] in ";& \t\r\n":
            head = head.rstrip(";& \t\r\n").rstrip()

        if tail:
            sep = "" if (not head or head[-1] in " \t\n") else " "
            return head + sep + tail
        return head

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
        """异步执行代码。

        不使用 PIPE + communicate()：后台子进程会一直占着管道写端，
        导致管道 EOF 永不到达，必须等到超时才返回（例如
        `cmd & echo done` / `cmd > /dev/null &`）。
        改为把 stdout/stderr 重定向到临时文件，只 wait() shell 进程本身；
        并用独立进程组，超时可把整棵进程树一起杀掉，避免孤儿进程。
        """
        status: ToolStatus = ToolStatus.SUCCESS
        result_dict: dict = {}
        tmpdir = tempfile.mkdtemp(prefix="broca_bash_")
        out_path = os.path.join(tmpdir, "stdout.log")
        err_path = os.path.join(tmpdir, "stderr.log")

        def _read(path: str) -> str:
            try:
                with open(path, "rb") as f:
                    return f.read().decode("utf-8", errors="replace")
            except FileNotFoundError:
                return ""

        try:
            with open(out_path, "wb") as out_f, open(err_path, "wb") as err_f:
                kwargs: dict = {}
                if sys.platform == "win32":
                    kwargs["creationflags"] = 0x00000200  # CREATE_NEW_PROCESS_GROUP
                else:
                    kwargs["preexec_fn"] = os.setsid

                process = await asyncio.create_subprocess_shell(
                    code,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=out_f,
                    stderr=err_f,
                    **kwargs,
                )

                try:
                    # 只等 shell 本身，不再等管道 EOF
                    await asyncio.wait_for(process.wait(), timeout=timeout)
                    result_dict = {"returncode": process.returncode}
                except asyncio.TimeoutError:
                    # 超时：杀掉整个进程组，避免后台子进程残留
                    self._kill_process_tree(process)
                    try:
                        await process.wait()
                    except Exception:
                        pass
                    result_dict = {
                        "returncode": -1,
                        "stderr": f"Execution timed out after {timeout} seconds.",
                    }
                    status = ToolStatus.ERROR

            result_dict.setdefault("stdout", _read(out_path))
            if "stderr" not in result_dict:
                result_dict["stderr"] = _read(err_path)

        except Exception as e:
            result_dict = {
                "returncode": -1,
                "stderr": f"Execution failed: {e}",
            }
            status = ToolStatus.ERROR
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        output = Template(self.code_output_template).render(output=result_dict)
        return ToolResult(status=status, content=output)

    @staticmethod
    def _kill_process_tree(process) -> None:
        """杀掉整个进程组，避免后台子进程变成孤儿。"""
        try:
            if sys.platform == "win32":
                process.kill()
            else:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
