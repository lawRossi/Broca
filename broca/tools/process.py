"""
进程管理工具

独立的后台进程生命周期管理工具。
从 cron 工具拆分而来，专注管理长时间运行的子进程。
"""

from datetime import datetime

from broca.logging_config import get_logger
from broca.process_manager import ProcessManager, ProcessStatus
from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus

logger = get_logger(__name__)


class ProcessTool(Tool):
    """进程管理工具，支持查询、列举和停止后台进程"""

    def __init__(self):
        super().__init__()
        logger.info("ProcessTool initialized")

    @property
    def name(self):
        return "process_management"

    @property
    def description(self):
        return """Use this tool to manage background processes.

supported actions:
- track_process: query the status of a specific process by process_id
- list_processes: list all managed processes with basic info
- stop_process: stop a running process (graceful SIGTERM or force SIGKILL)
"""

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "track_process, list_processes, stop_process",
                    "enum": [
                        "track_process",
                        "list_processes",
                        "stop_process",
                    ],
                },
                "process_id": {
                    "type": "string",
                    "description": "process id (required for track_process and stop_process)",
                },
                "force": {
                    "type": "boolean",
                    "description": "force stop the process with SIGKILL instead of SIGTERM (optional, default: false)",
                },
            },
            "required": ["action"],
        }

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        action = arguments["action"]

        try:
            if action == "track_process":
                return await self._track_process(arguments, context)
            elif action == "list_processes":
                return await self._list_processes(arguments, context)
            elif action == "stop_process":
                return await self._stop_process(arguments, context)
            else:
                return ToolResult(
                    status=ToolStatus.ERROR, content=f"未知的操作: {action}"
                )
        except Exception as e:
            logger.error(f"Error in process tool: {e}")
            return ToolResult(status=ToolStatus.ERROR, content=f"执行失败: {str(e)}")

    async def _track_process(
        self, arguments: dict, context: ToolCallContext
    ) -> ToolResult:
        """追踪一个已知 process_id 的进程"""
        if "process_id" not in arguments:
            return ToolResult(status=ToolStatus.ERROR, content="缺少 process_id 参数")

        process_id = arguments["process_id"]

        try:
            pm = ProcessManager()
            info = pm.get_status(process_id)
            if not info:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content=f"进程不存在: {process_id}",
                )

            elapsed = ""
            if info.start_time:
                seconds = (
                    datetime.now().astimezone() - info.start_time
                ).total_seconds()
                elapsed = f"{int(seconds)}s"

            result = (
                f"进程状态: {info.status.value}\n"
                f"PID: {info.pid}\n"
                f"命令: {info.command}\n"
                f"运行时间: {elapsed}\n"
                f"stdout: {info.stdout_path}\n"
                f"stderr: {info.stderr_path}\n"
            )
            if info.exit_code is not None:
                result += f"退出码: {info.exit_code}\n"
            if info.end_time:
                result += f"结束时间: {info.end_time}\n"

            if info.status == ProcessStatus.RUNNING:
                result += "\n提示: 使用 `read_file` 工具读取输出文件"

            return ToolResult(status=ToolStatus.SUCCESS, content=result)

        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"查询进程失败: {str(e)}",
            )

    async def _list_processes(
        self, arguments: dict, context: ToolCallContext
    ) -> ToolResult:
        """列出所有被管理的进程"""
        try:
            pm = ProcessManager()
            processes = pm.list_processes()

            if not processes:
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    content="当前没有正在管理中的进程",
                )

            result = f"共 {len(processes)} 个进程:\n\n"
            for info in processes:
                elapsed = ""
                if info.start_time:
                    seconds = (
                        datetime.now().astimezone() - info.start_time
                    ).total_seconds()
                    elapsed = f"{int(seconds)}s"
                result += (
                    f"ID: {info.process_id}\n"
                    f"  状态: {info.status.value}\n"
                    f"  命令: {info.command[:60]}...\n"
                    f"  PID: {info.pid}\n"
                    f"  运行时间: {elapsed}\n"
                )
                if info.status == ProcessStatus.RUNNING:
                    result += "  (运行中)\n"
                result += "\n"

            return ToolResult(status=ToolStatus.SUCCESS, content=result)

        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"列出进程失败: {str(e)}",
            )

    async def _stop_process(
        self, arguments: dict, context: ToolCallContext
    ) -> ToolResult:
        """停止一个进程"""
        if "process_id" not in arguments:
            return ToolResult(status=ToolStatus.ERROR, content="缺少 process_id 参数")

        process_id = arguments["process_id"]
        force = arguments.get("force", False)

        try:
            pm = ProcessManager()
            success = await pm.stop_process(process_id, force=force)

            if success:
                method = "强制" if force else "优雅"
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    content=f"进程已{method}停止: {process_id}",
                )
            else:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content=f"停止进程失败: {process_id}（进程可能不存在或已结束）",
                )

        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"停止进程失败: {str(e)}",
            )
