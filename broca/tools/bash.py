import asyncio
import re

from jinja2 import Template
from tree_sitter import Language, Parser

from broca.logging_config import get_logger
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
                }
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
        if not self._validate_code(code):
            agent = context.agent
            if not await agent.ask_for_permission("Run potentially dangerous code"):
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content="User refused to run potentially dangerous code",
                )

        # 检查是否需要流式输出
        if self._needs_streaming(code):
            return await self._run_code_streaming(code, context)
        else:
            return await self._run_code_async(code)

    def _needs_streaming(self, code: str) -> bool:
        """判断命令是否需要流式输出"""
        lines = code.strip().split("\n")
        first_line = lines[0].strip() if lines else ""

        # 提取第一个命令
        first_word = first_line.split()[0] if first_line else ""

        # 需要流式输出的命令
        streaming_commands = {}

        # 检查命令特征
        if first_word in streaming_commands:
            return True

        # 检查是否是长时间运行的命令
        if any(
            indicator in code.lower()
            for indicator in ["build", "install", "download", "compile"]
        ):
            return True

        return False

    def _validate_code(self, code: str) -> bool:
        """Validate code using tree-sitter for better parsing, with regex fallback"""
        if self.tree_sitter_available and self._is_shell_command(code):
            return self._validate_with_tree_sitter(code)
        else:
            return self._validate_with_regex(code)

    def _is_shell_command(self, code: str) -> bool:
        """Check if the code appears to be a shell command"""
        # Simple heuristic to detect shell commands
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

    def _validate_with_tree_sitter(self, code: str) -> bool:
        """Validate shell commands using tree-sitter for better accuracy"""
        try:
            tree = self.parser.parse(bytes(code, "utf8"))
            root_node = tree.root_node

            # Define dangerous command types to check for
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

            # Walk the tree to find command nodes
            def check_node(node):
                if node.type == "command":
                    # Get the command name
                    command_node = node.child_by_field_name("name")
                    if command_node and command_node.type == "word":
                        command_name = code[
                            command_node.start_byte : command_node.end_byte
                        ]
                        if command_name in dangerous_commands:
                            logger.warning(
                                f"Dangerous command detected: {command_name}"
                            )
                            return False

                    # Check for dangerous flags with rm
                    if command_node and command_node.type == "word":
                        command_name = code[
                            command_node.start_byte : command_node.end_byte
                        ]
                        if command_name == "rm":
                            # Check for dangerous flags
                            for child in node.children:
                                if (
                                    child.type == "word"
                                    and child.start_byte < child.end_byte
                                ):
                                    flag = code[child.start_byte : child.end_byte]
                                    if flag in ["-rf", "-r", "-f", "-fr"]:
                                        logger.warning(
                                            f"Dangerous rm flag detected: {flag}"
                                        )
                                        return False

                # Check for shell injection patterns
                if node.type == "string" and (
                    "`" in code[node.start_byte : node.end_byte]
                    or "$(" in code[node.start_byte : node.end_byte]
                ):
                    logger.warning("Shell injection pattern detected")
                    return False

                # Recursively check children
                for child in node.children:
                    if not check_node(child):
                        return False

                return True

            return check_node(root_node)

        except Exception as e:
            logger.warning(
                f"Tree-sitter validation failed: {e}. Falling back to regex validation."
            )
            return self._validate_with_regex(code)

    def _validate_with_regex(self, code: str) -> bool:
        """Fallback validation using regex patterns"""
        dangerous_patterns = [
            # File system destruction commands
            r"^\s*rm\s+(-rf|-r|-f)?\s+",  # rm with force/recursive flags
            r"^\s*del\s+",  # Windows delete
            r"^\s*rd\s+",  # Windows remove directory
            r"^\s*format\s+",  # Disk formatting
            # System shutdown/reboot commands
            r"^\s*shutdown$|^\s*shutdown\s+|^\s*shutdown\s+now|"
            r"^\s*reboot$|^\s*reboot\s+",
            r"^\s*halt\s+",
            r"^\s*poweroff\s+|^\s*poweroff$",
            r"^\s*init\s+[06]",  # init 0 or init 6 (shutdown/reboot)
            # Network disruption commands
            r"^\s*iptables\s+",  # Firewall manipulation
            r"^\s*chmod\s+[0-7]{3,4}\s+",  # Dangerous permission changes
            r"^\s*chown\s+",  # Ownership changes
            # Data destruction commands
            r"^\s*dd\s+",  # Disk duplication/copy
            r"^\s*mkfs\s+",  # Filesystem creation
            r"^\s*fdisk\s+",  # Partition manipulation
            # Privilege escalation
            r"^\s*sudo\s+",  # Sudo usage
            r"^\s*su\s+",  # Switch user
            # Shell injection patterns
            r"\$\s*\(",  # $(command) substitution
            # os.system() usage
            r"^\s*os\.system\s*\(",
            # subprocess.call() usage
            r"^\s*subprocess\.call\s*\(",
            # git dangerous command
            r"^\s*git\s+rm\s+",
            r"^\s*git\s+reset\s+",
            r"^\s*git\s+restore\s+",
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, code, re.MULTILINE | re.IGNORECASE):
                logger.warning(f"Dangerous command pattern detected: {pattern}")
                return False

        return True

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

    async def _run_code_streaming(
        self, code: str, context: ToolCallContext, timeout: int = 600
    ) -> ToolResult:
        """流式执行代码，实时输出结果"""
        status: ToolStatus = ToolStatus.SUCCESS

        try:
            # 使用 asyncio.create_subprocess_shell 异步执行
            process = await asyncio.create_subprocess_shell(
                code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                shell=True,
            )

            # 创建任务来同时读取 stdout 和 stderr
            async def read_stream(stream, is_stderr=False):
                chunks = []
                try:
                    while True:
                        chunk = await stream.read(4096)
                        if not chunk:
                            break
                        decoded = chunk.decode("utf-8", errors="replace")
                        chunks.append(decoded)

                        # 实时发送输出（如果有通信器）
                        if (
                            hasattr(context, "agent")
                            and context.agent
                            and hasattr(context.agent, "communicator")
                        ):
                            try:
                                await context.agent.communicator.send_progress_update(
                                    message=f"{'STDERR' if is_stderr else 'STDOUT'}: {decoded[:100]}...",
                                    subscription=context.session_id,
                                )
                            except:
                                pass

                except Exception as e:
                    logger.error(f"Error reading stream: {e}")
                return "".join(chunks)

            # 并行读取 stdout 和 stderr
            stdout_task = asyncio.create_task(read_stream(process.stdout, False))
            stderr_task = asyncio.create_task(read_stream(process.stderr, True))

            try:
                # 等待进程完成，带超时
                await asyncio.wait_for(process.wait(), timeout=timeout)

                # 获取输出
                stdout_result = await stdout_task
                stderr_result = await stderr_task

                result_dict = {
                    "returncode": process.returncode,
                    "stdout": stdout_result,
                    "stderr": stderr_result,
                }
                status = ToolStatus.SUCCESS

            except asyncio.TimeoutError:
                # 超时处理
                try:
                    process.kill()
                    await process.wait()
                except Exception:
                    pass

                # 取消读取任务
                stdout_task.cancel()
                stderr_task.cancel()

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
