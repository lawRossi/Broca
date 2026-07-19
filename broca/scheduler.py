"""
调度器模块

封装APScheduler，实现任务管理和持久化。
"""

import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from broca.logging_config import get_logger
from broca.errors import ValidationError
from broca.process_manager import ProcessManager
from broca.session.models import JobStatus, JobType, MessageProtocol
from broca.session.service import get_job_execution_service, get_job_service
from broca.utils.datetime_util import serialize_dt



def _aps_to_utc(dt: datetime | None) -> datetime | None:
    """将 APScheduler 的 timezone-aware datetime 转为 UTC naive datetime 以便存储。

    APScheduler 返回的时间是本地时区（如 UTC+8），
    而数据库所有字段统一用 UTC 存储，需在写入前转换。
    """
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None)

logger = get_logger(__name__)


class Scheduler:
    """调度器主类（封装APScheduler）"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Scheduler, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._initialized = True
            self.apscheduler = AsyncIOScheduler()
            self.job_service = get_job_service()
            self.execution_service = get_job_execution_service()
            self._job_process_map: Dict[str, str] = {}  # job_id → process_id
            self._job_notify_map: Dict[str, bool] = {}  # job_id → notify flag
            logger.info("Scheduler initialized")

    @property
    def running(self):
        return self.apscheduler.running

    def _serialize_trigger_config(
        self, trigger_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """序列化触发器配置，将datetime对象转换为ISO字符串"""
        serialized = {}
        for key, value in trigger_config.items():
            if isinstance(value, datetime):
                serialized[key] = value.isoformat()
            else:
                serialized[key] = value
        return serialized

    def _deserialize_trigger_config(
        self, trigger_config: Dict[str, Any]
    ) -> Dict[str, Any]:
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
                raise ValidationError(f"Invalid trigger config for cron: {config}")

        elif trigger_type == "interval":
            if isinstance(config, dict):
                return IntervalTrigger(**config)
            else:
                raise ValidationError(f"Invalid trigger config for interval: {config}")

        elif trigger_type == "date":
            if isinstance(config, dict):
                return DateTrigger(**config)
            else:
                raise ValidationError(f"Invalid trigger config for date: {config}")

        else:
            raise ValidationError(f"Unknown trigger type: {trigger_type}")

    async def start(self):
        """启动调度器，从数据库恢复任务"""
        try:
            # 从数据库加载ACTIVE状态的任务
            jobs = await self.job_service.get_active_jobs()
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
            func: Callable[..., Any]
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

            # 更新下次执行时间（转为 UTC 后存储，与其他模型字段一致）
            await self.job_service.update_next_run_time(
                job.job_id, _aps_to_utc(aps_job.next_run_time)
            )

            logger.info(f"Restored job: {job.name} (ID: {job.job_id})")

        except Exception as e:
            logger.error(f"Failed to restore job {job.job_id}: {e}")

    async def add_job(
        self,
        session_id: str,
        name: str,
        job_type: JobType,
        trigger_type: str,
        trigger_config: Dict[str, Any],
        content: str,
        agent_id: Optional[str] = None,
        notify: bool = False,
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
            notify: 命令执行完成后是否通知 Agent（仅 COMMAND 类型有效）

        Returns:
            任务ID
        """
        try:
            # 生成任务ID
            job_id = f"job_{uuid.uuid4()}"

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
                session_id=session_id,
                agent_id=agent_id,
            )

            # 解析触发器
            trigger = self._parse_trigger(trigger_type, trigger_config)

            # 根据任务类型选择执行函数
            func: Callable[..., Any]
            if job_type == JobType.REMINDER:
                func = self._execute_reminder
            elif job_type == JobType.COMMAND:
                func = self._execute_command
            else:
                raise ValidationError(f"Unsupported job type: {job_type}")

            # 添加到APScheduler
            aps_job = self.apscheduler.add_job(
                func,
                trigger=trigger,
                args=[job_id, content, agent_id],
                id=job_id,
                name=name,
                replace_existing=True,
            )

            # 更新下次执行时间（转为 UTC 后存储，与其他模型字段一致）
            await self.job_service.update_next_run_time(job_id, _aps_to_utc(aps_job.next_run_time))

            # 存储 notify 标志（仅 COMMAND 类型）
            if job_type == JobType.COMMAND and notify:
                self._job_notify_map[job_id] = True

            logger.info(
                f"Added job: {name} (ID: {job_id}), next run: {aps_job.next_run_time}, notify={notify}"
            )

            return job_id

        except Exception as e:
            logger.error(f"Failed to add job {name}: {e}")
            raise

    async def remove_job(self, job_id: str) -> bool:
        """删除任务"""
        try:
            # 从APScheduler删除，APScheduler的remove_job本身会处理不存在的情况
            try:
                self.apscheduler.remove_job(job_id)
            except Exception as e:
                logger.warning(
                    f"Job not found in scheduler or remove failed: {job_id}, {e}"
                )

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
                            job_id, _aps_to_utc(aps_job.next_run_time)
                        )

                logger.info(f"Resumed job: {job_id}")
            else:
                logger.warning(f"Job not found: {job_id}")

            return success

        except Exception as e:
            logger.error(f"Failed to resume job {job_id}: {e}")
            return False

    async def list_jobs(self, session_id: str) -> List[Dict[str, Any]]:
        """列出所有任务"""
        try:
            jobs = await self.job_service.get_active_jobs(session_id)

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
                    "created_at": serialize_dt(job.created_at, is_utc=True),
                    "next_run_time": serialize_dt(aps_job.next_run_time)
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

            result = {
                "job_id": job.job_id,
                "name": job.name,
                "type": job.job_type.value,
                "status": job.status.value,
                "trigger_type": job.trigger_type,
                "trigger_config": job.trigger_config,
                "content": job.content,
                "session_id": job.session_id,
                "agent_id": job.agent_id,
                "created_at": serialize_dt(job.created_at, is_utc=True),
                "updated_at": serialize_dt(job.updated_at, is_utc=True),
                "next_run_time": serialize_dt(aps_job.next_run_time)
                if aps_job and aps_job.next_run_time
                else None,
                "execution_history": [
                    {
                        "executed_at": serialize_dt(exec.executed_at, is_utc=True),
                        "success": exec.success,
                        "result": exec.result,
                    }
                    for exec in executions
                ],
            }

            # 如果有关联的运行中进程，添加进程状态信息
            process_id = self._job_process_map.get(job_id)
            if process_id:
                pm = ProcessManager()
                pinfo = pm.get_status(process_id)
                if pinfo:
                    elapsed = (
                        datetime.now(timezone.utc) - pinfo.start_time
                    ).total_seconds() if pinfo.start_time else 0
                    result["process_status"] = {
                        "process_id": pinfo.process_id,
                        "pid": pinfo.pid,
                        "status": pinfo.status.value,
                        "running_seconds": int(elapsed),
                        "stdout_path": str(pinfo.stdout_path) if pinfo.stdout_path else None,
                        "stderr_path": str(pinfo.stderr_path) if pinfo.stderr_path else None,
                    }

            return result

        except Exception as e:
            logger.error(f"Failed to get job {job_id}: {e}")
            return None

    async def _cleanup_one_time_job(self, job_id: str):
        """
        清理一次性date触发器任务

        对于一次性任务，执行后标记为完成并从调度器移除
        """
        try:
            job = await self.job_service.get(job_id)
            if job and job.trigger_type == "date":
                await self.job_service.complete_job(job_id)
                try:
                    self.apscheduler.remove_job(job_id)
                except Exception as e:
                    logger.warning(
                        f"Failed to remove one-time job {job_id} from scheduler: {e}"
                    )
        except Exception as e:
            logger.warning(f"Failed to check/complete one-time job {job_id}: {e}")

    async def _execute_reminder(self, job_id: str, message: str, agent_id):
        """执行提醒任务"""
        try:
            logger.info(
                f"Executing reminder job: {job_id}, message: {message}, agent_id: {agent_id}"
            )

            # 如果指定了agent_id，向该agent发送消息
            message = "Reminder:" + message
            await self._send_message_to_agent(agent_id, message)

            # 记录执行结果
            result = f"Reminder sent: {message}"

            await self.execution_service.create_execution(
                job_id=job_id, success=True, result=result
            )

        except Exception as e:
            logger.error(f"Failed to execute reminder job {job_id}: {e}")

            # 记录执行失败
            await self.execution_service.create_execution(
                job_id=job_id, success=False, result=f"Error: {str(e)}"
            )

        # 清理一次性任务
        await self._cleanup_one_time_job(job_id)

    async def _execute_command(
        self, job_id: str, command: str, agent_id: Optional[str] = None
    ):
        """执行命令任务（通过 ProcessManager，无超时，异步非阻塞）"""
        try:
            logger.info(
                f"Executing command job: {job_id}, command: {command}, agent_id: {agent_id}"
            )

            # ── 使用 ProcessManager 启动进程（取消 600s 硬超时） ──
            pm = ProcessManager()
            info = await pm.start_process(command, process_id=job_id)
            self._job_process_map[job_id] = info.process_id

            # 后台等待进程结束（不阻塞 APScheduler 调度循环）
            asyncio.create_task(
                self._wait_and_record(job_id, info, agent_id)
            )

        except Exception as e:
            error_msg = f"命令执行失败: {command}, 错误: {str(e)}"
            logger.error(error_msg)

            if agent_id:
                try:
                    await self._send_message_to_agent(
                        agent_id,
                        f"命令{job_id}执行失败，可通过cron工具的get_job查看详细结果",
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to send error notification to agent {agent_id}: {e}"
                    )

            await self.execution_service.create_execution(
                job_id=job_id, success=False, result=error_msg
            )

    async def _wait_and_record(
        self,
        job_id: str,
        process_info: Any,
        agent_id: Optional[str] = None,
    ):
        """后台等待进程结束，记录执行结果"""
        try:
            # 等待进程结束（无超时）
            exit_code = await process_info._process.wait()

            # 更新进程状态（仅在未被 stop_process 中断过时修改）
            # 如果 cancel_job_execution 已设置 STOPPED/KILLED，保留原状态
            from broca.process_manager import ProcessStatus
            if process_info.status == ProcessStatus.RUNNING:
                if exit_code == 0:
                    process_info.status = ProcessStatus.COMPLETED
                else:
                    process_info.status = ProcessStatus.FAILED
            process_info.exit_code = exit_code

            # 读取输出文件摘要（尾部 500 字节）
            stdout_preview = ""
            stderr_preview = ""
            try:
                if process_info.stdout_path and process_info.stdout_path.exists():
                    stdout_preview = self._tail_file(
                        process_info.stdout_path, 500
                    )
                if process_info.stderr_path and process_info.stderr_path.exists():
                    stderr_preview = self._tail_file(
                        process_info.stderr_path, 200
                    )
            except Exception:
                pass

            output = (
                f"job id: {job_id}\n"
                f"返回码: {exit_code}\n"
                f"输出文件: {process_info.stdout_path}\n"
                f"错误文件: {process_info.stderr_path}\n"
            )
            if stdout_preview:
                output += f"输出预览: {stdout_preview}\n"
            if stderr_preview:
                output += f"错误预览: {stderr_preview}\n"

            logger.info(
                f"Command job {job_id} finished: exit_code={exit_code}"
            )

            # 如果设置了 notify，通知 Agent
            notify = self._job_notify_map.get(job_id, False)
            if notify and agent_id:
                try:
                    await self._send_message_to_agent(
                        agent_id,
                        f"命令 {job_id} 执行完成, "
                        f"返回码: {exit_code}",
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to send completion to agent {agent_id}: {e}"
                    )

            # 记录执行结果
            await self.execution_service.create_execution(
                job_id=job_id,
                success=exit_code == 0,
                result=output,
            )

        except Exception as e:
            error_msg = f"等待命令 {job_id} 完成时出错: {e}"
            logger.error(error_msg)
            await self.execution_service.create_execution(
                job_id=job_id, success=False, result=error_msg,
            )

        finally:
            # 清理映射关系
            self._job_process_map.pop(job_id, None)
            self._job_notify_map.pop(job_id, None)

            # 清理一次性任务
            await self._cleanup_one_time_job(job_id)

    def _tail_file(self, path, max_bytes: int = 500) -> str:
        """读取文件尾部内容"""
        try:
            file_size = path.stat().st_size
            if file_size == 0:
                return ""
            with open(path, "r") as f:
                if file_size <= max_bytes:
                    return f.read()
                f.seek(file_size - max_bytes)
                # 跳过不完整的行
                f.readline()
                return f.read()
        except Exception:
            return ""

    async def cancel_job_execution(self, job_id: str) -> bool:
        """取消正在运行的命令执行

        Args:
            job_id: 任务 ID

        Returns:
            是否成功取消
        """
        process_id = self._job_process_map.get(job_id)
        if not process_id:
            logger.warning(
                f"No running process found for job {job_id}"
            )
            return False

        pm = ProcessManager()
        success = await pm.stop_process(process_id, force=True)
        if success:
            logger.info(
                f"Cancelled job execution: {job_id} (process: {process_id})"
            )
            await self.execution_service.create_execution(
                job_id=job_id,
                success=False,
                result="Job execution cancelled by user",
            )
        return success

    async def _send_message_to_agent(self, agent_id: str, content: str):
        """向指定agent发送消息"""
        try:
            # 获取服务器URL，从环境变量或默认值
            server_url = os.getenv("BROCA_SERVER_URL", "http://localhost:6868")

            # 创建临时socketio客户端
            from broca.communication.socketio_client import SocketIOClient

            client = SocketIOClient(
                server_url=server_url,
                client_type="scheduler",
                client_id=f"scheduler_{id(self)}",
                auto_reconnect=False,
            )

            # 连接到服务器
            await client.connect()

            # 创建用户消息发送给agent
            message = MessageProtocol.create_user_message(
                content=content, sender_id="scheduler", receiver_id=agent_id
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

            logger.info(
                f"Executing job immediately: {job.name} (ID: {job_id}, type: {job.job_type}, agent_id: {job.agent_id})"
            )

            # 根据job类型执行相应的任务
            if job.job_type == JobType.REMINDER:
                await self._execute_reminder(job_id, job.content, job.agent_id)
            elif job.job_type == JobType.COMMAND:
                await self._execute_command(job_id, job.content, job.agent_id)
            else:
                logger.error(f"Unsupported job type: {job.job_type}")
                return False

            logger.info(f"Job executed successfully: {job.name}")
            return True

        except Exception as e:
            logger.exception(f"Failed to execute job {job_id}: {e}")
            return False

    async def cleanup(self):
        """清理资源"""
        # 清理 ProcessManager 中的所有存活进程
        pm = ProcessManager()
        await pm.cleanup()

        self._job_process_map.clear()
        self._job_notify_map.clear()

        await self.shutdown()
        logger.info("Scheduler cleaned up")
