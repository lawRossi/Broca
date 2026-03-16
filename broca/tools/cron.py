import asyncio
import json
from datetime import datetime
from typing import Dict, List, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus


class CronTool(Tool):
    """定时任务工具，支持定时提醒和定时执行命令"""
    
    def __init__(self):
        super().__init__()
        self.scheduler = AsyncIOScheduler()
        self.scheduler.start()
        self.jobs: Dict[str, Dict] = {}  # 存储任务信息
        logger.info("CronTool initialized with scheduler")
    
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
        """
    
    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "要执行的操作：add_reminder, add_command, list_jobs, remove_job, pause_job, resume_job",
                    "enum": ["add_reminder", "add_command", "list_jobs", "remove_job", "pause_job", "resume_job"]
                },
                "name": {
                    "type": "string",
                    "description": "任务名称（add_reminder和add_command时必需）"
                },
                "message": {
                    "type": "string",
                    "description": "提醒消息内容（add_reminder时必需）"
                },
                "command": {
                    "type": "string",
                    "description": "要执行的shell命令（add_command时必需）"
                },
                "trigger_type": {
                    "type": "string",
                    "description": "触发器类型：cron, interval, date",
                    "enum": ["cron", "interval", "date"]
                },
                "trigger": {
                    "type": ["string", "object"],
                    "description": "触发器配置：cron表达式字符串，或interval/date的配置对象"
                },
                "job_id": {
                    "type": "string",
                    "description": "任务ID（remove_job, pause_job, resume_job时必需）"
                }
            },
            "required": ["action"]
        }
    
    def _parse_trigger(self, trigger_type: str, trigger_config) -> CronTrigger | IntervalTrigger | DateTrigger:
        """解析触发器配置"""
        if trigger_type == "cron":
            if isinstance(trigger_config, str):
                # 解析cron表达式
                parts = trigger_config.split()
                if len(parts) != 5:
                    raise ValueError(f"Invalid cron expression: {trigger_config}. Expected 5 parts.")
                return CronTrigger.from_crontab(trigger_config)
            elif isinstance(trigger_config, dict):
                return CronTrigger(**trigger_config)
            else:
                raise ValueError(f"Invalid trigger config for cron: {trigger_config}")
        
        elif trigger_type == "interval":
            if isinstance(trigger_config, dict):
                return IntervalTrigger(**trigger_config)
            else:
                raise ValueError(f"Invalid trigger config for interval: {trigger_config}")
        
        elif trigger_type == "date":
            if isinstance(trigger_config, str):
                # 解析日期字符串
                try:
                    run_date = datetime.fromisoformat(trigger_config.replace('Z', '+00:00'))
                except ValueError:
                    # 尝试其他格式
                    from dateutil import parser
                    run_date = parser.parse(trigger_config)
                return DateTrigger(run_date=run_date)
            elif isinstance(trigger_config, dict):
                return DateTrigger(**trigger_config)
            else:
                raise ValueError(f"Invalid trigger config for date: {trigger_config}")
        
        else:
            raise ValueError(f"Unknown trigger type: {trigger_type}")
    
    async def _send_reminder(self, job_id: str, message: str, context: ToolCallContext):
        """发送提醒消息给agent"""
        try:
            agent = context.agent
            if agent and hasattr(agent, 'communicator'):
                # 通过communicator发送消息
                await agent.communicator.send_message(
                    message=f"⏰ 定时提醒: {message}",
                    receiver_id=agent.agent_id
                )
                logger.info(f"Sent reminder: {message} to agent {agent.agent_id}")
            else:
                # 如果没有communicator，记录日志
                logger.info(f"Reminder: {message}")
        except Exception as e:
            logger.error(f"Failed to send reminder: {e}")
    
    async def _execute_command(self, job_id: str, command: str, context: ToolCallContext):
        """执行shell命令"""
        try:
            import subprocess
            import shlex
            
            # 执行命令
            result = subprocess.run(
                shlex.split(command),
                capture_output=True,
                text=True,
                timeout=300  # 5分钟超时
            )
            
            output = f"命令: {command}\n"
            output += f"返回码: {result.returncode}\n"
            output += f"输出: {result.stdout}\n"
            if result.stderr:
                output += f"错误: {result.stderr}\n"
            
            logger.info(f"Executed command: {command}, return code: {result.returncode}")
            
            # 如果有agent上下文，发送执行结果
            if context.agent and hasattr(context.agent, 'communicator'):
                await context.agent.communicator.send_message(
                    message=f"🖥️ 定时命令执行完成:\n{output[:500]}...",  # 限制消息长度
                    receiver_id=context.agent.agent_id
                )
            
        except subprocess.TimeoutExpired:
            error_msg = f"命令执行超时: {command}"
            logger.error(error_msg)
            if context.agent and hasattr(context.agent, 'communicator'):
                await context.agent.communicator.send_message(
                    message=f"⏰ 定时命令执行超时: {command}",
                    receiver_id=context.agent.agent_id
                )
        except Exception as e:
            error_msg = f"命令执行失败: {command}, 错误: {str(e)}"
            logger.error(error_msg)
            if context.agent and hasattr(context.agent, 'communicator'):
                await context.agent.communicator.send_message(
                    message=f"❌ 定时命令执行失败: {command}\n错误: {str(e)}",
                    receiver_id=context.agent.agent_id
                )
    
    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        action = arguments["action"]
        
        try:
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
            else:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content=f"未知的操作: {action}"
                )
        except Exception as e:
            logger.error(f"Error in cron tool: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"执行失败: {str(e)}"
            )
    
    async def _add_reminder(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        """添加定时提醒"""
        required_fields = ["name", "message", "trigger_type", "trigger"]
        for field in required_fields:
            if field not in arguments:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content=f"缺少必需字段: {field}"
                )
        
        name = arguments["name"]
        message = arguments["message"]
        trigger_type = arguments["trigger_type"]
        trigger_config = arguments["trigger"]
        
        # 生成唯一的job_id
        job_id = f"reminder_{name}_{datetime.now().timestamp()}"
        
        try:
            trigger = self._parse_trigger(trigger_type, trigger_config)
            
            # 添加任务到调度器
            job = self.scheduler.add_job(
                self._send_reminder,
                trigger=trigger,
                args=[job_id, message, context],
                id=job_id,
                name=name,
                replace_existing=True
            )
            
            # 存储任务信息
            self.jobs[job_id] = {
                "type": "reminder",
                "name": name,
                "message": message,
                "trigger_type": trigger_type,
                "trigger": trigger_config,
                "next_run_time": str(job.next_run_time) if job.next_run_time else None
            }
            
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"定时提醒已添加\nID: {job_id}\n名称: {name}\n下次执行时间: {job.next_run_time}"
            )
            
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"添加定时提醒失败: {str(e)}"
            )
    
    async def _add_command(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        """添加定时命令"""
        required_fields = ["name", "command", "trigger_type", "trigger"]
        for field in required_fields:
            if field not in arguments:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content=f"缺少必需字段: {field}"
                )
        
        name = arguments["name"]
        command = arguments["command"]
        trigger_type = arguments["trigger_type"]
        trigger_config = arguments["trigger"]
        
        # 生成唯一的job_id
        job_id = f"command_{name}_{datetime.now().timestamp()}"
        
        try:
            trigger = self._parse_trigger(trigger_type, trigger_config)
            
            # 添加任务到调度器
            job = self.scheduler.add_job(
                self._execute_command,
                trigger=trigger,
                args=[job_id, command, context],
                id=job_id,
                name=name,
                replace_existing=True
            )
            
            # 存储任务信息
            self.jobs[job_id] = {
                "type": "command",
                "name": name,
                "command": command,
                "trigger_type": trigger_type,
                "trigger": trigger_config,
                "next_run_time": str(job.next_run_time) if job.next_run_time else None
            }
            
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"定时命令已添加\nID: {job_id}\n名称: {name}\n命令: {command}\n下次执行时间: {job.next_run_time}"
            )
            
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"添加定时命令失败: {str(e)}"
            )
    
    async def _list_jobs(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        """列出所有任务"""
        if not self.jobs:
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content="当前没有定时任务"
            )
        
        result = "当前定时任务:\n\n"
        for job_id, job_info in self.jobs.items():
            result += f"ID: {job_id}\n"
            result += f"类型: {job_info['type']}\n"
            result += f"名称: {job_info['name']}\n"
            
            if job_info['type'] == 'reminder':
                result += f"消息: {job_info['message']}\n"
            else:
                result += f"命令: {job_info['command']}\n"
            
            result += f"触发器类型: {job_info['trigger_type']}\n"
            result += f"触发器配置: {job_info['trigger']}\n"
            result += f"下次执行时间: {job_info.get('next_run_time', '未知')}\n"
            result += "-" * 40 + "\n"
        
        return ToolResult(
            status=ToolStatus.SUCCESS,
            content=result
        )
    
    async def _remove_job(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        """删除任务"""
        if "job_id" not in arguments:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="缺少job_id参数"
            )
        
        job_id = arguments["job_id"]
        
        if job_id not in self.jobs:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"任务不存在: {job_id}"
            )
        
        try:
            # 从调度器移除
            self.scheduler.remove_job(job_id)
            # 从存储中移除
            del self.jobs[job_id]
            
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"任务已删除: {job_id}"
            )
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"删除任务失败: {str(e)}"
            )
    
    async def _pause_job(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        """暂停任务"""
        if "job_id" not in arguments:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="缺少job_id参数"
            )
        
        job_id = arguments["job_id"]
        
        if job_id not in self.jobs:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"任务不存在: {job_id}"
            )
        
        try:
            self.scheduler.pause_job(job_id)
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"任务已暂停: {job_id}"
            )
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"暂停任务失败: {str(e)}"
            )
    
    async def _resume_job(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        """恢复任务"""
        if "job_id" not in arguments:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="缺少job_id参数"
            )
        
        job_id = arguments["job_id"]
        
        if job_id not in self.jobs:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"任务不存在: {job_id}"
            )
        
        try:
            self.scheduler.resume_job(job_id)
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"任务已恢复: {job_id}"
            )
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"恢复任务失败: {str(e)}"
            )
    
    async def cleanup(self):
        """清理资源"""
        if self.scheduler.running:
            self.scheduler.shutdown()
        logger.info("CronTool cleaned up")