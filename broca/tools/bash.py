import re
import subprocess

from jinja2 import Template
from loguru import logger
from tree_sitter import Language, Parser

from broca.tools.tool import Tool, ToolCallContext


class ExecuteCode(Tool):
    def __init__(self):
        self.code_output_template = "return code: {{output.returncode}}\n{% if output.returncode == 0 -%}\noutput:{{ output.stdout if output.stdout.strip() else 'execution succeeded'}}\n{% endif %}\n{%- if output.stderr -%}error: {{output.stderr}}{% endif %}"
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

    async def _execute(self, arguments: dict, context: ToolCallContext):
        code = arguments["code"]
        if not self._validate_code(code):
            agent = context.agent
            if not await agent.ask_for_permission("Run potentially dangerous code"):
                return "User refused to run potentially dangerous code"

        return self._run_code(code)

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
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, code, re.MULTILINE | re.IGNORECASE):
                logger.warning(f"Dangerous command pattern detected: {pattern}")
                return False

        return True

    def _run_code(self, code: str, timeout: int = 10) -> str:
        try:
            result = subprocess.run(
                code, capture_output=True, text=True, timeout=timeout, shell=True
            )
            result_dict = {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except subprocess.TimeoutExpired:
            result_dict = {
                "returncode": -1,
                "stdout": "Execution timed out.",
            }
        except Exception as e:
            result_dict = {
                "returncode": -1,
                "stdout": f"Execution failed: {e}",
            }
        output = Template(self.code_output_template).render(output=result_dict)
        return output
