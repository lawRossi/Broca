import asyncio
import re
from datetime import datetime

from jinja2 import Template
from tree_sitter import Language, Parser

from broca.logging_config import get_logger
from broca.scheduler import Scheduler
from broca.session.models import JobType
from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus

logger = get_logger(__name__)


class ExecuteCode(Tool):
    def __init__(self):
        super().__init__()
        self.code_output_template = "return code: {{output.returncode}}\n{% if output.stdout -%}\noutput:{{ output.stdout if output.stdout.strip() else 'execution succeeded'}}\n{% endif %}\n{%- if output.stderr -%}error: {{output.stderr}}{% endif %}"
        self._init_tree_sitter()

    @property
    def name(self) -> str:
        return "execute_code"

    @property
    def description(self) -> str:
        return "Use this tool to execute code using shell."

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
                    "description": "Run in background via scheduler. Use for long-running commands or when user explicitly requests background execution. When true, returns immediately with a job ID for tracking instead of waiting for completion.",
                },
            },
            "required": ["code"],
        }

    def _init_tree_sitter(self):
        """Initialize tree-sitter parser for bash language"""
        try:
            # Try to load bash language from tree-sitter-bash
            self.bash_lang = Language.build_library(
                "build/my-languages.so", ["vendor/tree-sitter-bash"]
            )
            self.bash_lang = Language("build/my-languages.so", "bash")
            self.parser = Parser()
            self.parser.set_language(self.bash_lang)
            self.tree_sitter_available = True
        except Exception as e:
            logger.warning(
                f"Failed to initialize tree-sitter: {e}. Falling back to regex validation."
            )
            self.tree_sitter_available = False
            self.parser = None
            self.bash_lang = None

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        code = arguments["code"]
        background = arguments.get("background", False)

        if background:
            return await self._run_background(code, context)

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
        """Validate code using tree-sitter for better parsing, with regex fallback.

        Returns:
            tuple[bool, str, str]: (is_safe, reason, snippet) where reason describes why the code is
            flagged as dangerous, and snippet is the relevant code fragment that triggered the flag.
        """
        if self.tree_sitter_available and self._is_shell_command(code):
            return self._validate_with_tree_sitter(code)
        else:
            return self._validate_with_regex(code)

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

    def _validate_with_tree_sitter(self, code: str) -> tuple[bool, str, str]:
        """Validate shell commands using tree-sitter for better accuracy"""
        try:
            tree = self.parser.parse(bytes(code, "utf8"))
            root_node = tree.root_node

            dangerous_commands = {
                "rm",
                "del",
                "rd",
                "format",
                "shutdown",
                "reboot",
                "halt",
                "poweroff",
                "iptables",
                "dd",
                "mkfs",
                "fdisk",
                "sudo",
                "su",
            }

            def check_node(node):
                if node.type == "command":
                    command_node = node.child_by_field_name("name")
                    if command_node and command_node.type == "word":
                        command_name = code[
                            command_node.start_byte : command_node.end_byte
                        ]
                        if command_name in dangerous_commands:
                            snippet = code[node.start_byte : node.end_byte].strip()
                            return (
                                False,
                                f"Command '{command_name}' is flagged as dangerous",
                                snippet,
                            )

                        if command_name == "rm":
                            for child in node.children:
                                if (
                                    child.type == "word"
                                    and child.start_byte < child.end_byte
                                ):
                                    flag = code[child.start_byte : child.end_byte]
                                    if flag in ["-rf", "-r", "-f", "-fr"]:
                                        snippet = code[
                                            node.start_byte : node.end_byte
                                        ].strip()
                                        return (
                                            False,
                                            f"'rm' with dangerous flag '{flag}'",
                                            snippet,
                                        )

                if node.type == "string" and (
                    "`" in code[node.start_byte : node.end_byte]
                    or "$(" in code[node.start_byte : node.end_byte]
                ):
                    snippet = code[node.start_byte : node.end_byte].strip()
                    return (False, "Shell injection pattern detected", snippet)

                for child in node.children:
                    result = check_node(child)
                    if isinstance(result, tuple) and not result[0]:
                        return result
                return (True, "", "")

            return check_node(root_node)
        except Exception as e:
            logger.warning(
                f"Tree-sitter validation failed: {e}. Falling back to regex."
            )
            return self._validate_with_regex(code)

    def _validate_with_regex(self, code: str) -> tuple[bool, str, str]:
        """Fallback validation using regex patterns"""
        dangerous_patterns = [
            (r"^\s*rm\s+(-rf|-r|-f)?\s+", "File deletion with 'rm' command"),
            (r"^\s*del\s+", "File deletion with 'del' command"),
            (r"^\s*rd\s+", "Directory removal with 'rd' command"),
            (r"^\s*format\s+", "Disk formatting with 'format' command"),
            (r"^\s*shutdown(?:\s+|$)", "System shutdown"),
            (r"^\s*reboot(?:\s+|$)", "System reboot"),
            (r"^\s*halt(?:\s+|$)", "System halt"),
            (r"^\s*poweroff(?:\s+|$)", "System poweroff"),
            (r"^\s*init\s+[06]", "System shutdown/reboot via init"),
            (r"^\s*iptables\s+", "Firewall manipulation with 'iptables'"),
            (r"^\s*chmod\s+[0-7]{3,4}\s+", "Dangerous permission changes with 'chmod'"),
            (r"^\s*chown\s+", "Ownership changes with 'chown'"),
            (r"^\s*dd\s+", "Disk data operation with 'dd'"),
            (r"^\s*mkfs\s+", "Filesystem creation with 'mkfs'"),
            (r"^\s*fdisk\s+", "Partition manipulation with 'fdisk'"),
            (r"^\s*sudo\s+", "Privilege escalation with 'sudo'"),
            (r"^\s*su\s+", "User switching with 'su'"),
            (r"\$\s*\(", "Shell command substitution '$('"),
            (r"^\s*os\.system\s*\(", "Python os.system() call"),
            (r"^\s*subprocess\.call\s*\(", "Python subprocess.call()"),
            (r"^\s*git\s+rm\s+", "Git file removal"),
            (r"^\s*git\s+reset\s+", "Git reset operation"),
            (r"^\s*git\s+restore\s+", "Git restore operation"),
        ]

        for pattern, description in dangerous_patterns:
            match = re.search(pattern, code, re.MULTILINE | re.IGNORECASE)
            if match:
                line_start = code.rfind("\n", 0, match.start()) + 1
                line_end = code.find("\n", match.end())
                if line_end == -1:
                    line_end = len(code)
                snippet = code[line_start:line_end].strip()
                return (False, f"{description} detected", snippet)

        return (True, "", "")

    async def _run_background(self, code: str, context: ToolCallContext) -> ToolResult:
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
            )
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"Code scheduled for background execution\nJob ID: {job_id}\nYou'll be notified when it's done. You can also use `cron` tool with `get_job` action to check execution result.",
            )
        except Exception as e:
            logger.error(f"Failed to schedule background execution: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Failed to schedule background execution: {e}",
            )

    async def _run_code_async(self, code: str, timeout: int = 300) -> ToolResult:
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
