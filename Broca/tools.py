import json
import re
import subprocess

from jinja2 import Template
from loguru import logger
from tavily import TavilyClient
from tree_sitter import Language, Parser

from Broca.agent_crew import BlackBoard
from Broca.skill_manager import SkillManager
from Broca.task import TaskContext, TaskPriority, TaskStatus
from Broca.task_manager import TaskManager


class ToolCallContext:
    def __init__(self):
        self.agent = None


class Tool:
    def __init__(self):
        self.name = "tool"
        self.description = "This is a tool"
        self.parameters = {}

    def format(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    async def execute(self, arguments: str, context: ToolCallContext) -> str:
        try:
            args_dict = json.loads(arguments)
            return await self._execute(args_dict, context)
        except Exception as e:
            logger.error(f"Error executing tool: {e}")
            return f"Error executing tool: {e}"

    async def _execute(self, arguments: dict, context: ToolCallContext) -> str:
        return f"Tool {self.name} does not implement _execute method"


class ExecuteCode(Tool):
    def __init__(self):
        super().__init__()
        self.name = "execute_code"
        self.description = "Use this tool to execute code using shell."
        self.parameters = {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "the code to run",
                }
            },
            "required": ["code"],
        }
        self.code_output_template = "return code: {{output.returncode}}\n{% if output.returncode == 0 -%}\noutput:{{ output.stdout if output.stdout.strip() else 'execution succeeded'}}\n{% endif %}\n{%- if output.stderr -%}error: {{output.stderr}}{% endif %}"

        # Initialize tree-sitter parser for bash
        self._init_tree_sitter()

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


class LoadSkill(Tool):
    def __init__(self, skill_manager: SkillManager):
        super().__init__()
        self.name = "load_skill"
        self.description = "Use this tool to load a skill."
        self.parameters = {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "the name of the skill to load",
                }
            },
            "required": ["skill_name"],
        }
        self.skill_manager = skill_manager

    async def _execute(self, arguments: dict, context: ToolCallContext):
        skill_name = arguments["skill_name"]
        return self.skill_manager.load_skill_spec(skill_name)


class Speak(Tool):
    def __init__(self, blackboard: BlackBoard):
        self.blackboard = blackboard
        self.name = "speak"
        self.description = "Use this tool to speak in the crew."
        self.parameters = {
            "type": "object",
            "properties": {
                "role": {
                    "type": "string",
                    "description": "the complete role name of the speaker",
                },
                "text": {
                    "type": "string",
                    "description": "the text to speak",
                },
            },
            "required": ["text", "role"],
        }

    def _execute(self, arguments: dict, context: ToolCallContext):
        role = arguments["role"]
        text = arguments["text"]
        new_text = f"{role}: {text}".replace("\n\n", "\n")
        print(new_text[:100])
        content = self.blackboard.content
        new_content = content + "\n\n" + new_text
        self.blackboard.update(new_content)
        with open("blackboard.txt", "a") as fo:
            fo.write(new_text + "\n\n")
        return "Done."


class PickSpeaker(Tool):
    def __init__(self):
        super().__init__()
        self.name = "pick_speaker"
        self.description = "Use this tool to pick a speaker."
        self.parameters = {
            "type": "object",
            "properties": {
                "speaker": {
                    "type": "string",
                    "description": "the complete role name of the speaker",
                }
            },
            "required": ["speaker"],
        }
        self.agent_crew = None

    def _execute(self, arguments: dict, context: ToolCallContext):
        speaker = arguments["speaker"]
        if speaker not in self.agent_crew.members:
            logger.error(f"Speaker '{speaker}' not found.")
            return f"Speaker '{speaker}' not found."
        self.agent_crew.run_member_step(speaker)
        return f"Speaker '{speaker}' finished speaking."


class CreateTask(Tool):
    def __init__(self):
        super().__init__()
        self.name = "create_task"
        self.description = "Use this tool to create a task."
        self.parameters = {
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "description": "the agent to create the task for",
                },
                "task": {
                    "type": "string",
                    "description": "a self-explanatory description of the task",
                },
            },
            "required": ["agent", "task"],
        }


class TaskManagementTool(Tool):
    def __init__(self):
        super().__init__()
        self.name = "task_management"
        self.description = "Use this tool to manage tasks with CRUD operations. Supports creating, retrieving, updating, deleting tasks, as well as adding comments and searching."
        self.parameters = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "The action to perform: create, get, get_all, get_by_status, get_by_assignee, update, delete, add_comment, get_children, search",
                },
                "task_id": {
                    "type": "string",
                    "description": "The ID of the task (required for get, update, delete, add_comment, get_children actions)",
                },
                "name": {
                    "type": "string",
                    "description": "Task name (required for create action)",
                },
                "description": {
                    "type": "string",
                    "description": "Task description (required for create action)",
                },
                "priority": {
                    "type": "string",
                    "description": "Task priority: low, medium, high (optional for create and update actions)",
                },
                "status": {
                    "type": "string",
                    "description": "Task status: pending, in_progress, blocked, completed (optional for update action)",
                },
                "assignee": {
                    "type": "string",
                    "description": "Task assignee (optional for create and update actions)",
                },
                "parent_id": {
                    "type": "string",
                    "description": "Parent task ID (optional for create action)",
                },
                "dependencies": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of dependency task IDs (optional for create and update actions)",
                },
                "details": {
                    "type": "string",
                    "description": "Detailed task description (optional for create and update actions)",
                },
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of task related files (optional for create and update actions)",
                },
                "links": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of task related links (optional for create and update actions)",
                },
                "acceptance_criteria": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of acceptance criteria (optional for create and update actions)",
                },
                "author": {
                    "type": "string",
                    "description": "Comment author (required for add_comment action)",
                },
                "content": {
                    "type": "string",
                    "description": "Comment content (required for add_comment action)",
                },
                "query": {
                    "type": "string",
                    "description": "Search query (required for search action)",
                },
            },
            "required": ["action"],
        }
        self.task_manager = TaskManager()

    def _execute(self, arguments: dict, context: ToolCallContext):
        action = arguments.get("action")

        if action == "create":
            return self._create_task(arguments)
        elif action == "get":
            return self._get_task(arguments)
        elif action == "get_all":
            return self._get_all_tasks()
        elif action == "get_by_status":
            return self._get_tasks_by_status(arguments)
        elif action == "get_by_assignee":
            return self._get_tasks_by_assignee(arguments)
        elif action == "update":
            return self._update_task(arguments)
        elif action == "delete":
            return self._delete_task(arguments)
        elif action == "add_comment":
            return self._add_comment(arguments)
        elif action == "get_children":
            return self._get_child_tasks(arguments)
        elif action == "search":
            return self._search_tasks(arguments)
        else:
            return f"Unknown action: {action}"

    def _create_task(self, arguments):
        required_fields = ["name", "description"]
        for field in required_fields:
            if field not in arguments:
                return f"Missing required field: {field}"

        try:
            # Convert string priority to enum if provided
            priority = TaskPriority.MEDIUM
            if "priority" in arguments:
                priority = TaskPriority(arguments["priority"].lower())

            # Convert context dict to TaskContext if provided
            context = None
            if "context" in arguments:
                context = TaskContext(**arguments["context"])

            task = self.task_manager.create_task(
                name=arguments["name"],
                description=arguments["description"],
                priority=priority,
                parent_id=arguments.get("parent_id"),
                assignee=arguments.get("assignee"),
                dependencies=arguments.get("dependencies"),
                details=arguments.get("details"),
                context=context,
                acceptance_criteria=arguments.get("acceptance_criteria"),
            )

            return f"Task created successfully with ID: {task.metadata.id}"
        except Exception as e:
            return f"Error creating task: {str(e)}"

    def _get_task(self, arguments):
        task_id = arguments.get("task_id")
        if not task_id:
            return "Missing required field: task_id"

        task = self.task_manager.get_task(task_id)
        if task:
            return json.dumps(task.model_dump(), indent=2, default=str)
        else:
            return f"Task with ID {task_id} not found"

    def _get_all_tasks(self):
        tasks = self.task_manager.get_all_tasks()
        return json.dumps([task.model_dump() for task in tasks], indent=2, default=str)

    def _get_tasks_by_status(self, arguments):
        status = arguments.get("status")
        if not status:
            return "Missing required field: status"

        try:
            status_enum = TaskStatus(status.lower())
            tasks = self.task_manager.get_tasks_by_status(status_enum)
            return json.dumps(
                [task.model_dump() for task in tasks], indent=2, default=str
            )
        except ValueError:
            return f"Invalid status: {status}. Valid values: pending, in_progress, blocked, completed"

    def _get_tasks_by_assignee(self, arguments):
        assignee = arguments.get("assignee")
        if not assignee:
            return "Missing required field: assignee"

        tasks = self.task_manager.get_tasks_by_assignee(assignee)
        return json.dumps([task.model_dump() for task in tasks], indent=2, default=str)

    def _update_task(self, arguments):
        task_id = arguments.get("task_id")
        if not task_id:
            return "Missing required field: task_id"

        try:
            # Convert string status to enum if provided
            status = None
            if "status" in arguments:
                status = TaskStatus(arguments["status"].lower())

            # Convert string priority to enum if provided
            priority = None
            if "priority" in arguments:
                priority = TaskPriority(arguments["priority"].lower())

            # Convert context dict to TaskContext if provided
            context = None
            if "context" in arguments:
                context = TaskContext(**arguments["context"])

            task = self.task_manager.update_task(
                task_id=task_id,
                name=arguments.get("name"),
                description=arguments.get("description"),
                status=status,
                priority=priority,
                assignee=arguments.get("assignee"),
                dependencies=arguments.get("dependencies"),
                details=arguments.get("details"),
                context=context,
                acceptance_criteria=arguments.get("acceptance_criteria"),
            )

            if task:
                return f"Task {task_id} updated successfully"
            else:
                return f"Task with ID {task_id} not found"
        except ValueError as e:
            return f"Invalid value: {str(e)}"
        except Exception as e:
            return f"Error updating task: {str(e)}"

    def _delete_task(self, arguments):
        task_id = arguments.get("task_id")
        if not task_id:
            return "Missing required field: task_id"

        success = self.task_manager.delete_task(task_id)
        if success:
            return f"Task {task_id} deleted successfully"
        else:
            return f"Task with ID {task_id} not found"

    def _add_comment(self, arguments):
        task_id = arguments.get("task_id")
        author = arguments.get("author")
        content = arguments.get("content")

        if not task_id:
            return "Missing required field: task_id"
        if not author:
            return "Missing required field: author"
        if not content:
            return "Missing required field: content"

        task = self.task_manager.add_comment(
            task_id=task_id, author=author, content=content
        )

        if task:
            return f"Comment added to task {task_id} successfully"
        else:
            return f"Task with ID {task_id} not found"

    def _get_child_tasks(self, arguments):
        parent_id = arguments.get("task_id")
        if not parent_id:
            return "Missing required field: task_id"

        tasks = self.task_manager.get_child_tasks(parent_id)
        return json.dumps([task.model_dump() for task in tasks], indent=2, default=str)

    def _search_tasks(self, arguments):
        query = arguments.get("query")
        if not query:
            return "Missing required field: query"

        tasks = self.task_manager.search_tasks(query)
        return json.dumps([task.model_dump() for task in tasks], indent=2, default=str)


class WebSearch(Tool):
    def __init__(self, api_key: str | None = None):
        super().__init__()
        self.name = "web_search"
        self.description = "Use this tool to search the web using Tavily API. This tool performs web searches and returns relevant results with sources."
        self.parameters = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to look up",
                },
                "search_depth": {
                    "type": "string",
                    "description": "Search depth: 'fast', 'basic', 'advanced', or 'ultra-fast'",
                    "enum": ["fast", "basic", "advanced", "ultra-fast"],
                    "default": "fast",
                },
                "topic": {
                    "type": "string",
                    "description": "Search topic: 'general', 'news', or 'finance'",
                    "enum": ["general", "news", "finance"],
                    "default": "general",
                },
                "time_range": {
                    "type": "string",
                    "description": "Time range filter: 'day', 'week', 'month', or 'year'",
                    "enum": ["day", "week", "month", "year"],
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 10)",
                    "default": 5
                },
                "include_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of domains to include in search",
                },
                "exclude_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of domains to exclude from search",
                },
                "include_answer": {
                    "type": "boolean",
                    "description": "Whether to include an AI-generated answer",
                    "default": True,
                },
                "include_images": {
                    "type": "boolean",
                    "description": "Whether to include images in results",
                    "default": False,
                },
            },
            "required": ["query"],
        }
        # Initialize Tavily client
        self.api_key = api_key
        self.client = None
        self._init_client()

    def _init_client(self) -> bool:
        """Initialize Tavily client with API key"""
        try:
            # Try to get API key from environment variable if not provided
            if not self.api_key:
                import os

                self.api_key = os.environ.get("TAVILY_API_KEY")

            if self.api_key:
                self.client = TavilyClient(api_key=self.api_key)
                return True
            else:
                logger.warning("No Tavily API key provided. Web search will not work.")
        except ImportError:
            logger.warning(
                "tavily-python package not installed. Web search will not work."
            )
        return False

    async def _execute(self, arguments: dict, context: ToolCallContext) -> str:
        if not self.client:
            return (
                "Error: Tavily client not initialized. Please provide a valid API key."
            )

        query = arguments.get("query")
        if not query:
            return "Error: Query is required"
        try:
            # Build search parameters
            search_params = {
                "query": query,
                "search_depth": arguments.get("search_depth", "fast"),
                "topic": arguments.get("topic", "general"),
                "max_results": arguments.get("max_results", 5),
                "include_answer": arguments.get("include_answer", True),
                "include_images": arguments.get("include_images", False),
            }

            # Add optional parameters
            if arguments.get("time_range"):
                search_params["time_range"] = arguments.get("time_range")
            if arguments.get("include_domains"):
                search_params["include_domains"] = arguments.get("include_domains")
            if arguments.get("exclude_domains"):
                search_params["exclude_domains"] = arguments.get("exclude_domains")

            # Perform search
            result = self.client.search(**search_params)

            # Format results
            return self._format_results(result)

        except Exception as e:
            logger.error(f"Web search error: {e}")
            return f"Error performing web search: {str(e)}"

    def _format_results(self, result: dict) -> str:
        """Format search results for better readability"""
        output = []

        # Add answer if available
        if "answer" in result and result["answer"]:
            output.append("Answer:")
            output.append(result["answer"])
            output.append("")

        # Add sources
        if "sources" in result and result["sources"]:
            output.append("Sources:")
            for i, source in enumerate(result["sources"], 1):
                output.append(f"{i}. {source}")
            output.append("")

        # Add results
        if "results" in result and result["results"]:
            output.append("Search Results:")
            for i, result_item in enumerate(result["results"], 1):
                title = result_item.get("title", "No title")
                url = result_item.get("url", "No URL")
                content = result_item.get("content", "")
                score = result_item.get("score", 0)

                output.append(f"{i}. {title}")
                output.append(f"   URL: {url}")
                output.append(f"   Relevance: {score:.2f}")
                if content:
                    output.append(f"   Content: {content}...")
                output.append("")

        return "\n".join(output)
