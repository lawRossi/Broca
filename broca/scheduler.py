"""
调度器模块

封装APScheduler，实现任务管理和持久化。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

import os
from broca.session.models import JobStatus, JobType, MessageProtocol, MessageRole, MessageType
from broca.session.service import get_job_execution_service, get_job_service


class Scheduler:
    """调度器主类（封装APScheduler）"""

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id
        self.apscheduler = AsyncIOScheduler()
        self.job_service = get_job_service()
        self.execution_service = get_job_execution_service()
        logger.info(f"Scheduler initialized for session: {session_id}")

    def _serialize_trigger_config(self, trigger_config: Dict[str, Any]) -> Dict[str, Any]:
        """序列化触发器配置，将datetime对象转换为ISO字符串"""
        serialized = {}
        for key, value in trigger_config.items():
            if isinstance(value, datetime):
                serialized[key] = value.isoformat()
            else:
                serialized[key] = value
        return serialized

    def _deserialize_trigger_config(self, trigger_config: Dict[str, Any]) -> Dict[str, Any]:
        """反序列化触发器配置，将ISO字符串转换回datetime（如果需要）"""
        # 注意：APScheduler可以处理ISO字符串，所以不一定需要转换回datetime
        # 这里我们保持原样，让APScheduler处理
        return trigger_config

    def _parse_trigger(
        self, trigger_type: str, trigger_config: Dict[str, Any]
    ) -> CronTrigger | IntervalTrigger | DateTrigger:
        """解析触发器配置"""
        # 使用反序列化后的配置
        config = self._deserialize_trigger_config(trigger_config)

        if trigger_type == "cron":
            if isinstance(config, dict):
                return CronTrigger(**config)
            else:
                raise ValueError(f"Invalid trigger config for cron: {config}")

        elif trigger_type == "interval":
            if isinstance(config, dict):
                return IntervalTrigger(**config)
            else:
                raise ValueError(
                    f"Invalid trigger config for interval: {config}"
                )

        elif trigger_type == "date":
            if isinstance(config, dict):
                return DateTrigger(**config)
            else:
                raise ValueError(f"Invalid trigger config for date: {config}")

        else:
            raise ValueError(f"Unknown trigger type: {trigger_type}")

    async def start(self):
        """启动调度器，从数据库恢复任务"""
        try:
            # 从数据库加载ACTIVE状态的任务
            jobs = await self.job_service.get_active_jobs(self.session_id)
            logger.info(f"Loading {len(jobs)} active jobs from database")

            # 初始化APScheduler
            self.apscheduler.start()

            # 恢复任务调度
            for job in jobs:
                await self._restore_job(job)

            logger.info("Scheduler started successfully")

        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}")
            raise

    async def shutdown(self):
        """关闭调度器"""
        try:
            if self.apscheduler.running:
                self.apscheduler.shutdown()
            logger.info("Scheduler shutdown successfully")
        except Exception as e:
            logger.error(f"Failed to shutdown scheduler: {e}")

    async def _restore_job(self, job: Any):
        """恢复单个任务"""
        try:
            # 解析触发器
            trigger = self._parse_trigger(job.trigger_type, job.trigger_config)

            # 根据任务类型选择执行函数
            if job.job_type == JobType.REMINDER:
                func = self._execute_reminder
            elif job.job_type == JobType.COMMAND:
                func = self._execute_command
            else:
                logger.warning(
                    f"Unknown job type: {job.job_type}, skipping job {job.job_id}"
                )
                return

            # 添加到APScheduler（传递agent_id）
            aps_job = self.apscheduler.add_job(
                func,
                trigger=trigger,
                args=[job.job_id, job.content, job.agent_id],
                id=job.job_id,
                name=job.name,
                replace_existing=True,
            )

            # 更新下次执行时间
            await self.job_service.update_next_run_time(
                job.job_id, aps_job.next_run_time
            )

            logger.info(f"Restored job: {job.name} (ID: {job.job_id})")

        except Exception as e:
            logger.error(f"Failed to restore job {job.job_id}: {e}")

    async def add_job(
        self,
        name: str,
        job_type: JobType,
        trigger_type: str,
        trigger_config: Dict[str, Any],
        content: str,
        agent_id: Optional[str] = None,
    ) -> str:
        """
        添加任务

        Args:
            name: 任务名称
            job_type: 任务类型
            trigger_type: 触发器类型 (cron, interval, date)
            trigger_config: 触发器配置
            content: 执行内容（消息或命令）
            agent_id: 关联的Agent ID（可选）

        Returns:
            任务ID
        """
        try:
            # 生成任务ID
            job_id = f"{job_type.value}_{name}_{datetime.now().timestamp()}"

            # 序列化trigger_config，将datetime转换为ISO字符串
            serialized_config = self._serialize_trigger_config(trigger_config)

            # 创建数据库记录
            await self.job_service.create_job(
                job_id=job_id,
                name=name,
                job_type=job_type,
                trigger_type=trigger_type,
                trigger_config=serialized_config,
                content=content,
                session_id=self.session_id,
                agent_id=agent_id,
            )

            # 解析触发器
            trigger = self._parse_trigger(trigger_type, trigger_config)

            # 根据任务类型选择执行函数
            if job_type == JobType.REMINDER:
                func = self._execute_reminder
            elif job_type == JobType.COMMAND:
                func = self._execute_command
            else:
                raise ValueError(f"Unsupported job type: {job_type}")

            # 添加到APScheduler
            aps_job = self.apscheduler.add_job(
                func,
                trigger=trigger,
                args=[job_id, content, agent_id],
                id=job_id,
                name=name,
                replace_existing=True,
            )

            # 更新下次执行时间
            await self.job_service.update_next_run_time(job_id, aps_job.next_run_time)

            logger.info(
                f"Added job: {name} (ID: {job_id}), next run: {aps_job.next_run_time}"
            )

            return job_id

        except Exception as e:
            logger.error(f"Failed to add job {name}: {e}")
            raise

    async def remove_job(self, job_id: str) -> bool:
        """删除任务"""
        try:
            # 从APScheduler移除
            self.apscheduler.remove_job(job_id)

            # 从数据库删除
            success = await self.job_service.delete(job_id)

            if success:
                logger.info(f"Removed job: {job_id}")
            else:
                logger.warning(f"Job not found in database: {job_id}")

            return success

        except Exception as e:
            logger.error(f"Failed to remove job {job_id}: {e}")
            return False

    async def pause_job(self, job_id: str) -> bool:
        """暂停任务"""
        try:
            # 暂停APScheduler中的任务
            self.apscheduler.pause_job(job_id)

            # 更新数据库状态
            success = await self.job_service.pause_job(job_id)

            if success:
                logger.info(f"Paused job: {job_id}")
            else:
                logger.warning(f"Job not found: {job_id}")

            return success

        except Exception as e:
            logger.error(f"Failed to pause job {job_id}: {e}")
            return False

    async def resume_job(self, job_id: str) -> bool:
        """恢复任务"""
        try:
            # 恢复APScheduler中的任务
            self.apscheduler.resume_job(job_id)

            # 更新数据库状态
            success = await self.job_service.resume_job(job_id)

            if success:
                # 更新下次执行时间
                job = await self.job_service.get(job_id)
                if job:
                    aps_job = self.apscheduler.get_job(job_id)
                    if aps_job:
                        await self.job_service.update_next_run_time(
                            job_id, aps_job.next_run_time
                        )

                logger.info(f"Resumed job: {job_id}")
            else:
                logger.warning(f"Job not found: {job_id}")

            return success

        except Exception as e:
            logger.error(f"Failed to resume job {job_id}: {e}")
            return False

    async def list_jobs(self) -> List[Dict[str, Any]]:
        """列出所有任务"""
        try:
            jobs = await self.job_service.get_active_jobs(self.session_id)

            result = []
            for job in jobs:
                aps_job = self.apscheduler.get_job(job.job_id)

                job_info = {
                    "job_id": job.job_id,
                    "name": job.name,
                    "type": job.job_type.value,
                    "status": job.status.value,
                    "trigger_type": job.trigger_type,
                    "content": job.content,
                    "agent_id": job.agent_id,
                    "created_at": job.created_at.isoformat()
                    if job.created_at
                    else None,
                    "next_run_time": aps_job.next_run_time.isoformat()
                    if aps_job and aps_job.next_run_time
                    else None,
                }
                result.append(job_info)

            return result

        except Exception as e:
            logger.error(f"Failed to list jobs: {e}")
            return []

    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """获取任务信息"""
        try:
            job = await self.job_service.get(job_id)
            if not job:
                return None

            aps_job = self.apscheduler.get_job(job_id)

            # 获取执行历史
            executions = await self.execution_service.get_executions_by_job(
                job_id, limit=5
            )

            return {
                "job_id": job.job_id,
                "name": job.name,
                "type": job.job_type.value,
                "status": job.status.value,
                "trigger_type": job.trigger_type,
                "trigger_config": job.trigger_config,
                "content": job.content,
                "session_id": job.session_id,
                "agent_id": job.agent_id,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "updated_at": job.updated_at.isoformat() if job.updated_at else None,
                "next_run_time": aps_job.next_run_time.isoformat()
                if aps_job and aps_job.next_run_time
                else None,
                "execution_history": [
                    {
                        "executed_at": exec.executed_at.isoformat()
                        if exec.executed_at
                        else None,
                        "success": exec.success,
                        "result": exec.result,
                    }
                    for exec in executions
                ],
            }

        except Exception as e:
            logger.error(f"Failed to get job {job_id}: {e}")
            return None

    async def _execute_reminder(self, job_id: str, message: str, agent_id):
        """执行提醒任务"""
        try:
            logger.info(f"Executing reminder job: {job_id}, message: {message}, agent_id: {agent_id}")

            # 如果指定了agent_id，向该agent发送消息
            message = "Reminder:" + message
            await self._send_message_to_agent(agent_id, message)

            # 记录执行结果
            result = f"Reminder sent: {message}"
            if agent_id:
                result += f" (to agent: {agent_id})"

            await self.execution_service.create_execution(
                job_id=job_id, success=True, result=result
            )

        except Exception as e:
            logger.error(f"Failed to execute reminder job {job_id}: {e}")

            # 记录执行失败
            await self.execution_service.create_execution(
                job_id=job_id, success=False, result=f"Error: {str(e)}"
            )

    async def _execute_command(self, job_id: str, command: str, agent_id: Optional[str] = None):
        """执行命令任务"""
        try:
            logger.info(f"Executing command job: {job_id}, command: {command}, agent_id: {agent_id}")

            import shlex
            import subprocess

            # 执行命令
            result = subprocess.run(
                shlex.split(command),
                capture_output=True,
                text=True,
                timeout=300,  # 5分钟超时
            )

            output = f"job id:{job_id}\n"
            output += f"命令: {command}\n"
            output += f"返回码: {result.returncode}\n"
            output += f"输出: {result.stdout}\n"
            if result.stderr:
                output += f"错误: {result.stderr}\n"

            logger.info(
                f"Executed command: {command}, return code: {result.returncode}"
            )

            # 如果指定了agent_id，将执行结果发送给agent
            if agent_id:
                try:
                    await self._send_message_to_agent(agent_id, f"命令执行完成:\n{output}")
                except Exception as e:
                    logger.warning(f"Failed to send command result to agent {agent_id}: {e}")

            # 记录执行结果
            await self.execution_service.create_execution(
                job_id=job_id, success=result.returncode == 0, result=output
            )

        except subprocess.TimeoutExpired:
            error_msg = f"命令执行超时: {command}"
            logger.error(error_msg)

            # 如果指定了agent_id，通知超时
            if agent_id:
                try:
                    await self._send_message_to_agent(agent_id, f"命令执行超时: {command}")
                except Exception as e:
                    logger.warning(f"Failed to send timeout notification to agent {agent_id}: {e}")

            # 记录执行失败
            await self.execution_service.create_execution(
                job_id=job_id, success=False, result=error_msg
            )

        except Exception as e:
            error_msg = f"命令执行失败: {command}, 错误: {str(e)}"
            logger.error(error_msg)

            # 如果指定了agent_id，通知错误
            if agent_id:
                try:
                    await self._send_message_to_agent(agent_id, f"命令执行失败:\n{error_msg}")
                except Exception as e:
                    logger.warning(f"Failed to send error notification to agent {agent_id}: {e}")

            # 记录执行失败
            await self.execution_service.create_execution(
                job_id=job_id, success=False, result=error_msg
            )

    async def _send_message_to_agent(self, agent_id: str, content: str):
        """向指定agent发送消息"""
        try:
            # 获取服务器URL，从环境变量或默认值
            server_url = os.getenv("BROCA_SERVER_URL", "http://localhost:6868")

            # 创建临时socketio客户端
            from broca.comm.socketio_client import SocketIOClient

            client = SocketIOClient(
                server_url=server_url,
                client_type="scheduler",
                client_id=f"scheduler_{id(self)}",
                auto_reconnect=False
            )

            # 连接到服务器
            await client.connect()

            # 创建用户消息发送给agent
            message = MessageProtocol.create_user_message(
                content=content,
                sender_id="scheduler",
                receiver_id=agent_id
            )

            # 发送消息
            await client.send_message(message)
            logger.info(f"Sent message to agent {agent_id}: {content[:50]}...")

            # 断开连接
            await client.disconnect()

        except Exception as e:
            logger.error(f"Failed to send message to agent {agent_id}: {e}")
            raise

    async def execute_job_now(self, job_id: str) -> bool:
        """
        立即执行指定的job

        Args:
            job_id: 任务ID

        Returns:
            是否执行成功
        """
        try:
            # 从数据库获取job信息
            job = await self.job_service.get(job_id)
            if not job:
                logger.error(f"Job not found: {job_id}")
                return False

            # 检查job状态
            if job.status != JobStatus.ACTIVE:
                logger.warning(f"Job {job_id} is not active (status: {job.status})")
                return False

            logger.info(f"Executing job immediately: {job.name} (ID: {job_id}, type: {job.job_type}, agent_id: {job.agent_id})")

            # 根据job类型执行相应的任务
            if job.job_type == JobType.REMINDER:
                await self._execute_reminder(job_id, job.content, job.agent_id)
            elif job.job_type == JobType.COMMAND:
                await self._execute_command(job_id, job.content, job.agent_id)
            else:
                logger.error(f"Unsupported job type: {job.job_type}")
                return False

            # 对于date触发器的一次性任务，执行后标记为完成
            if job.trigger_type == "date":
                await self.job_service.complete_job(job_id)
                # 从APScheduler中移除
                try:
                    self.apscheduler.remove_job(job_id)
                except Exception as e:
                    logger.warning(f"Failed to remove job from scheduler: {e}")

            logger.info(f"Job executed successfully: {job.name}")
            return True

        except Exception as e:
            logger.exception(f"Failed to execute job {job_id}: {e}")
            return False

    async def cleanup(self):
        """清理资源"""
        await self.shutdown()
        logger.info("Scheduler cleaned up")
