"""
新的定时任务工具

使用封装的调度器，实现任务持久化。
"""

import json
from datetime import datetime
from typing import Any, Dict, Optional

from loguru import logger

from broca.scheduler import Scheduler
from broca.session.models import JobType
from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus


class CronTool(Tool):
    """定时任务工具，支持定时提醒和定时执行命令（使用持久化调度器）"""

    def __init__(self):
        super().__init__()
        self.scheduler: Optional[Scheduler] = None
        logger.info("CronTool initialized")

    @property
    def name(self):
        return "cron"

    @property
    def description(self):
        return """定时任务工具，支持定时提醒和定时执行命令。
        
        功能：
        1. 定时提醒：在指定时间给agent发送消息提醒
        2. 定时执行命令：在指定时间执行shell命令
        
        支持的触发器类型：
        - cron: cron表达式，如 "*/5 * * * *" 表示每5分钟
        - interval: 间隔时间，如 {"seconds": 30} 表示每30秒
        - date: 具体时间，如 "2024-01-01 12:00:00"
        
        示例：
        1. 添加定时提醒：{"action": "add_reminder", "name": "每日会议", "message": "每日站会时间", "trigger_type": "cron", "trigger": "0 10 * * *"}
        2. 添加定时命令：{"action": "add_command", "name": "备份数据库", "command": "echo 'backup'", "trigger_type": "interval", "trigger": {"seconds": 3600}}
        3. 列出任务：{"action": "list_jobs"}
        4. 删除任务：{"action": "remove_job", "job_id": "job_id"}
        5. 暂停任务：{"action": "pause_job", "job_id": "job_id"}
        6. 恢复任务：{"action": "resume_job", "job_id": "job_id"}
        """

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "要执行的操作：add_reminder, add_command, list_jobs, remove_job, pause_job, resume_job, get_job",
                    "enum": [
                        "add_reminder",
                        "add_command",
                        "list_jobs",
                        "remove_job",
                        "pause_job",
                        "resume_job",
                        "get_job",
                    ],
                },
                "name": {
                    "type": "string",
                    "description": "任务名称（add_reminder和add_command时必需）",
                },
                "message": {
                    "type": "string",
                    "description": "提醒消息内容（add_reminder时必需）",
                },
                "command": {
                    "type": "string",
                    "description": "要执行的shell命令（add_command时必需）",
                },
                "trigger_type": {
                    "type": "string",
                    "description": "触发器类型：cron, interval, date",
                    "enum": ["cron", "interval", "date"],
                },
                "trigger": {
                    "type": ["string", "object"],
                    "description": "触发器配置：cron表达式字符串，或interval/date的配置对象",
                },
                "job_id": {
                    "type": "string",
                    "description": "任务ID（remove_job, pause_job, resume_job, get_job时必需）",
                },
            },
            "required": ["action"],
        }

    def _parse_trigger_config(self, trigger_type: str, trigger) -> Dict[str, Any]:
        """解析触发器配置为字典格式"""
        if trigger_type == "cron":
            if isinstance(trigger, str):
                # 解析cron表达式为字典
                parts = trigger.split()
                if len(parts) != 5:
                    raise ValueError(
                        f"Invalid cron expression: {trigger}. Expected 5 parts."
                    )

                # 将cron表达式转换为字典格式
                return {
                    "minute": parts[0],
                    "hour": parts[1],
                    "day": parts[2],
                    "month": parts[3],
                    "day_of_week": parts[4],
                }
            elif isinstance(trigger, dict):
                return trigger
            else:
                raise ValueError(f"Invalid trigger config for cron: {trigger}")

        elif trigger_type == "interval":
            if isinstance(trigger, dict):
                return trigger
            else:
                raise ValueError(f"Invalid trigger config for interval: {trigger}")

        elif trigger_type == "date":
            if isinstance(trigger, str):
                # 解析日期字符串
                try:
                    run_date = datetime.fromisoformat(trigger.replace("Z", "+00:00"))
                except ValueError:
                    # 尝试其他格式
                    from dateutil import parser

                    run_date = parser.parse(trigger)
                return {"run_date": run_date.isoformat()}
            elif isinstance(trigger, dict):
                return trigger
            else:
                raise ValueError(f"Invalid trigger config for date: {trigger}")
        else:
            raise ValueError(f"Unknown trigger type: {trigger_type}")

    async def initialize(self, session_id: str):
        """初始化调度器"""
        if self.scheduler is None:
            self.scheduler = Scheduler(session_id=session_id)
            await self.scheduler.start()
            logger.info("CronTool scheduler initialized")

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        action = arguments["action"]
        agent_id = context.agent.agent_id
        arguments["agent_id"] = agent_id

        try:
            # 确保调度器已初始化
            await self.initialize(context.session_id)

            if action == "add_reminder":
                return await self._add_reminder(arguments, context)
            elif action == "add_command":
                return await self._add_command(arguments, context)
            elif action == "list_jobs":
                return await self._list_jobs(arguments, context)
            elif action == "remove_job":
                return await self._remove_job(arguments, context)
            elif action == "pause_job":
                return await self._pause_job(arguments, context)
            elif action == "resume_job":
                return await self._resume_job(arguments, context)
            elif action == "get_job":
                return await self._get_job(arguments, context)
            else:
                return ToolResult(
                    status=ToolStatus.ERROR, content=f"未知的操作: {action}"
                )
        except Exception as e:
            logger.error(f"Error in cron tool: {e}")
            return ToolResult(status=ToolStatus.ERROR, content=f"执行失败: {str(e)}")

    async def _add_reminder(
        self, arguments: dict, context: ToolCallContext
    ) -> ToolResult:
        """添加定时提醒"""
        required_fields = ["name", "message", "trigger_type", "trigger"]
        for field in required_fields:
            if field not in arguments:
                return ToolResult(
                    status=ToolStatus.ERROR, content=f"缺少必需字段: {field}"
                )

        name = arguments["name"]
        message = arguments["message"]
        trigger_type = arguments["trigger_type"]
        trigger = arguments["trigger"]
        agent_id = arguments.get("agent_id")

        try:
            # 解析触发器配置
            trigger_config = self._parse_trigger_config(trigger_type, trigger)

            # 添加任务到调度器
            job_id = await self.scheduler.add_job(
                name=name,
                job_type=JobType.REMINDER,
                trigger_type=trigger_type,
                trigger_config=trigger_config,
                content=message,
                agent_id=agent_id,
            )

            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"定时提醒已添加\nID: {job_id}\n名称: {name}\n消息: {message}",
            )

        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"添加定时提醒失败: {str(e)}"
            )

    async def _add_command(
        self, arguments: dict, context: ToolCallContext
    ) -> ToolResult:
        """添加定时命令"""
        required_fields = ["name", "command", "trigger_type", "trigger"]
        for field in required_fields:
            if field not in arguments:
                return ToolResult(
                    status=ToolStatus.ERROR, content=f"缺少必需字段: {field}"
                )

        name = arguments["name"]
        command = arguments["command"]
        trigger_type = arguments["trigger_type"]
        trigger = arguments["trigger"]
        agent_id = arguments.get("agent_id")

        try:
            # 解析触发器配置
            trigger_config = self._parse_trigger_config(trigger_type, trigger)

            # 添加任务到调度器
            job_id = await self.scheduler.add_job(
                name=name,
                job_type=JobType.COMMAND,
                trigger_type=trigger_type,
                trigger_config=trigger_config,
                content=command,
                agent_id=agent_id,
            )

            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"定时命令已添加\nID: {job_id}\n名称: {name}\n命令: {command}",
            )

        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"添加定时命令失败: {str(e)}"
            )

    async def _list_jobs(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        """列出所有任务"""
        try:
            jobs = await self.scheduler.list_jobs()

            if not jobs:
                return ToolResult(status=ToolStatus.SUCCESS, content="当前没有定时任务")

            result = "当前定时任务:\n\n"
            for job in jobs:
                result += f"ID: {job['job_id']}\n"
                result += f"名称: {job['name']}\n"
                result += f"类型: {job['type']}\n"
                result += f"状态: {job['status']}\n"
                result += f"触发器类型: {job['trigger_type']}\n"
                result += f"内容: {job['content']}\n"
                if job["next_run_time"]:
                    result += f"下次执行时间: {job['next_run_time']}\n"
                result += "-" * 40 + "\n"

            return ToolResult(status=ToolStatus.SUCCESS, content=result)

        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"列出任务失败: {str(e)}"
            )

    async def _get_job(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        """获取任务详情"""
        if "job_id" not in arguments:
            return ToolResult(status=ToolStatus.ERROR, content="缺少job_id参数")

        job_id = arguments["job_id"]

        try:
            job = await self.scheduler.get_job(job_id)

            if not job:
                return ToolResult(
                    status=ToolStatus.ERROR, content=f"任务不存在: {job_id}"
                )

            result = "任务详情:\n\n"
            result += f"ID: {job['job_id']}\n"
            result += f"名称: {job['name']}\n"
            result += f"类型: {job['type']}\n"
            result += f"状态: {job['status']}\n"
            result += f"触发器类型: {job['trigger_type']}\n"
            result += f"触发器配置: {json.dumps(job['trigger_config'], indent=2, ensure_ascii=False)}\n"
            result += f"内容: {job['content']}\n"
            result += f"创建时间: {job['created_at']}\n"
            result += f"更新时间: {job['updated_at']}\n"
            if job["next_run_time"]:
                result += f"下次执行时间: {job['next_run_time']}\n"

            if job["execution_history"]:
                result += "\n执行历史:\n"
                for exec in job["execution_history"]:
                    status = "✅ 成功" if exec["success"] else "❌ 失败"
                    result += f"- {exec['executed_at']}: {status}\n"
                    if exec["result"]:
                        result += f"  结果: {exec['result'][:100]}...\n"

            return ToolResult(status=ToolStatus.SUCCESS, content=result)

        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"获取任务详情失败: {str(e)}"
            )

    async def _remove_job(
        self, arguments: dict, context: ToolCallContext
    ) -> ToolResult:
        """删除任务"""
        if "job_id" not in arguments:
            return ToolResult(status=ToolStatus.ERROR, content="缺少job_id参数")

        job_id = arguments["job_id"]

        try:
            success = await self.scheduler.remove_job(job_id)

            if success:
                return ToolResult(
                    status=ToolStatus.SUCCESS, content=f"任务已删除: {job_id}"
                )
            else:
                return ToolResult(
                    status=ToolStatus.ERROR, content=f"任务不存在: {job_id}"
                )

        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"删除任务失败: {str(e)}"
            )

    async def _pause_job(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        """暂停任务"""
        if "job_id" not in arguments:
            return ToolResult(status=ToolStatus.ERROR, content="缺少job_id参数")

        job_id = arguments["job_id"]

        try:
            success = await self.scheduler.pause_job(job_id)

            if success:
                return ToolResult(
                    status=ToolStatus.SUCCESS, content=f"任务已暂停: {job_id}"
                )
            else:
                return ToolResult(
                    status=ToolStatus.ERROR, content=f"任务不存在: {job_id}"
                )

        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"暂停任务失败: {str(e)}"
            )

    async def _resume_job(
        self, arguments: dict, context: ToolCallContext
    ) -> ToolResult:
        """恢复任务"""
        if "job_id" not in arguments:
            return ToolResult(status=ToolStatus.ERROR, content="缺少job_id参数")

        job_id = arguments["job_id"]

        try:
            success = await self.scheduler.resume_job(job_id)

            if success:
                return ToolResult(
                    status=ToolStatus.SUCCESS, content=f"任务已恢复: {job_id}"
                )
            else:
                return ToolResult(
                    status=ToolStatus.ERROR, content=f"任务不存在: {job_id}"
                )

        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"恢复任务失败: {str(e)}"
            )

    async def cleanup(self):
        """清理资源"""
        if self.scheduler:
            await self.scheduler.cleanup()
        logger.info("CronTool cleaned up")
