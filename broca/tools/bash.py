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
        is_safe, reason, snippet = self._validate_code(code)
        if not is_safe:
            agent = context.agent
            permission_message = f"Run potentially dangerous code: {reason}\n\n```bash\n{snippet}\n```"
            if not await agent.ask_for_permission(permission_message):
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

    def _validate_with_tree_sitter(self, code: str) -> tuple[bool, str, str]:
        """Validate shell commands using tree-sitter for better accuracy
        
        Returns:
            tuple[bool, str, str]: (is_safe, reason, snippet) where reason describes why the code is 
            flagged as dangerous, and snippet is the relevant code fragment.
        """
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
                            snippet = code[node.start_byte:node.end_byte].strip()
                            return (False, f"Command '{command_name}' is flagged as dangerous", snippet)

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
                                        snippet = code[node.start_byte:node.end_byte].strip()
                                        return (False, f"'rm' with dangerous flag '{flag}' may cause destructive file deletion", snippet)

                # Check for shell injection patterns
                if node.type == "string" and (
                    "`" in code[node.start_byte : node.end_byte]
                    or "$(" in code[node.start_byte : node.end_byte]
                ):
                    logger.warning("Shell injection pattern detected")
                    snippet = code[node.start_byte:node.end_byte].strip()
                    return (False, "Shell injection pattern detected (backtick or $() substitution)", snippet)

                # Recursively check children
                for child in node.children:
                    result = check_node(child)
                    if isinstance(result, tuple) and not result[0]:
                        return result

                return (True, "", "")

            return check_node(root_node)

        except Exception as e:
            logger.warning(
                f"Tree-sitter validation failed: {e}. Falling back to regex validation."
            )
            return self._validate_with_regex(code)

    def _validate_with_regex(self, code: str) -> tuple[bool, str, str]:
        """Fallback validation using regex patterns
        
        Returns:
            tuple[bool, str, str]: (is_safe, reason, snippet) where reason describes why the code is 
            flagged as dangerous, and snippet is the relevant code fragment.
        """
        dangerous_patterns = [
            # File system destruction commands
            (r"^\s*rm\s+(-rf|-r|-f)?\s+", "File deletion with 'rm' command"),
            (r"^\s*del\s+", "File deletion with 'del' command"),
            (r"^\s*rd\s+", "Directory removal with 'rd' command"),
            (r"^\s*format\s+", "Disk formatting with 'format' command"),
            # System shutdown/reboot commands
            (r"^\s*shutdown(?:\s+|$)", "System shutdown"),
            (r"^\s*reboot(?:\s+|$)", "System reboot"),
            (r"^\s*halt(?:\s+|$)", "System halt"),
            (r"^\s*poweroff(?:\s+|$)", "System poweroff"),
            (r"^\s*init\s+[06]", "System shutdown/reboot via init"),
            # Network disruption commands
            (r"^\s*iptables\s+", "Firewall manipulation with 'iptables'"),
            (r"^\s*chmod\s+[0-7]{3,4}\s+", "Dangerous permission changes with 'chmod'"),
            (r"^\s*chown\s+", "Ownership changes with 'chown'"),
            # Data destruction commands
            (r"^\s*dd\s+", "Disk data operation with 'dd'"),
            (r"^\s*mkfs\s+", "Filesystem creation with 'mkfs'"),
            (r"^\s*fdisk\s+", "Partition manipulation with 'fdisk'"),
            # Privilege escalation
            (r"^\s*sudo\s+", "Privilege escalation with 'sudo'"),
            (r"^\s*su\s+", "User switching with 'su'"),
            # Shell injection patterns
            (r"\$\s*\(", "Shell command substitution '$('"),
            # os.system() usage
            (r"^\s*os\.system\s*\(", "Python os.system() call"),
            # subprocess.call() usage
            (r"^\s*subprocess\.call\s*\(", "Python subprocess.call()"),
            # git dangerous command
            (r"^\s*git\s+rm\s+", "Git file removal"),
            (r"^\s*git\s+reset\s+", "Git reset operation"),
            (r"^\s*git\s+restore\s+", "Git restore operation"),
        ]

        for pattern, description in dangerous_patterns:
            match = re.search(pattern, code, re.MULTILINE | re.IGNORECASE)
            if match:
                logger.warning(f"Dangerous command pattern detected: {pattern}")
                # Extract the matching line as snippet
                line_start = code.rfind("\n", 0, match.start()) + 1
                line_end = code.find("\n", match.end())
                if line_end == -1:
                    line_end = len(code)
                snippet = code[line_start:line_end].strip()
                return (False, f"{description} detected", snippet)

        return (True, "", "")

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
