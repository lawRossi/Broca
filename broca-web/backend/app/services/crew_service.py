"""
Crew Service

管理编排执行的生命周期，通过 IPC 与 Runner 进程通信。
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from broca.orchestration.crew import CrewConfig, CrewConfigValidator, OrchestratorType
from broca.session_runner import RunnerManager
from broca.session_runner.models import IPCMessageType


class CrewExecutionRecord:
    """编排执行记录（内存中维护，后续可持久化到数据库）"""

    def __init__(
        self,
        execution_id: str,
        session_id: str,
        crew_config: CrewConfig,
        status: str = "pending",
    ):
        self.execution_id = execution_id
        self.session_id = session_id
        self.crew_config = crew_config
        self.status = status  # pending, running, completed, failed, aborted
        self.error: Optional[str] = None
        self.result: Optional[Dict[str, Any]] = None
        self.created_at = datetime.now(timezone.utc)
        self.completed_at: Optional[datetime] = None
        self.phases: List[Dict[str, Any]] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "session_id": self.session_id,
            "crew_name": self.crew_config.name,
            "description": self.crew_config.description,
            "orchestrator_type": self.crew_config.orchestrator.type.value,
            "agent_count": len(self.crew_config.agents),
            "status": self.status,
            "error": self.error,
            "result": self.result,
            "phases": self.phases,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class CrewService:
    """
    编排服务

    管理编排执行的生命周期：提交、查询状态、中止。
    通过 RunnerManager 的 IPC 通道与 Runner 进程通信。
    """

    def __init__(self):
        self._executions: Dict[str, CrewExecutionRecord] = {}
        self._runner_manager = RunnerManager()

    async def submit_crew(
        self,
        crew_config: CrewConfig,
        session_id: str,
    ) -> CrewExecutionRecord:
        """
        提交编排执行

        Args:
            crew_config: Crew 配置
            session_id: 目标 Session ID

        Returns:
            编排执行记录

        Raises:
            ValueError: 配置校验失败
            RuntimeError: Runner 未运行或通信失败
        """
        # 1. 校验配置
        errors = CrewConfigValidator.validate(crew_config)
        if errors:
            raise ValueError(f"Crew config validation failed: {'; '.join(errors)}")

        # 2. 检查 Runner 状态
        runner_status = self._runner_manager.get_session_status(session_id)
        if not runner_status:
            raise RuntimeError(f"Session {session_id} has no active runner")

        # 3. 创建执行记录
        execution_id = f"crew-{uuid.uuid4().hex[:12]}"
        record = CrewExecutionRecord(
            execution_id=execution_id,
            session_id=session_id,
            crew_config=crew_config,
            status="running",
        )
        self._executions[execution_id] = record

        # 4. 通过 IPC 发送编排命令到 Runner
        yaml_content = crew_config.to_json()
        response = await self._runner_manager.send_command(
            session_id=session_id,
            msg_type=IPCMessageType.CMD_RUN_CREW,
            payload={
                "yaml_content": yaml_content,
                "crew_name": crew_config.name,
                "execution_id": execution_id,
            },
        )

        if response and "error" in response:
            record.status = "failed"
            record.error = response["error"]
            logger.error(f"Crew submission failed: {response['error']}")
        else:
            logger.info(f"Crew '{crew_config.name}' submitted, execution_id={execution_id}")

        return record

    async def submit_crew_from_yaml(
        self,
        yaml_content: str,
        session_id: str,
    ) -> CrewExecutionRecord:
        """从 YAML 字符串提交编排"""
        crew_config = CrewConfig.from_yaml(yaml_content)
        return await self.submit_crew(crew_config, session_id)

    async def submit_crew_from_file(
        self,
        yaml_path: str,
        session_id: str,
    ) -> CrewExecutionRecord:
        """从 YAML 文件提交编排"""
        crew_config = CrewConfig.from_yaml_file(yaml_path)
        return await self.submit_crew(crew_config, session_id)

    def get_execution(self, execution_id: str) -> Optional[CrewExecutionRecord]:
        """获取执行记录"""
        return self._executions.get(execution_id)

    def list_executions(
        self,
        session_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """列出执行记录"""
        records = list(self._executions.values())

        if session_id:
            records = [r for r in records if r.session_id == session_id]
        if status:
            records = [r for r in records if r.status == status]

        # 按创建时间倒序
        records.sort(key=lambda r: r.created_at, reverse=True)
        return [r.to_dict() for r in records]

    async def abort_execution(self, execution_id: str) -> bool:
        """中止编排执行"""
        record = self._executions.get(execution_id)
        if not record:
            return False

        response = await self._runner_manager.send_command(
            session_id=record.session_id,
            msg_type=IPCMessageType.CMD_ABORT_CREW,
            payload={"crew_id": record.crew_config.name, "execution_id": execution_id},
        )

        record.status = "aborted"
        record.completed_at = datetime.now(timezone.utc)
        return True

    def update_execution_result(
        self,
        execution_id: str,
        status: str,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        """更新执行结果（由 IPC 事件处理器回调）"""
        record = self._executions.get(execution_id)
        if not record:
            return

        record.status = status
        record.result = result
        record.error = error
        record.completed_at = datetime.now(timezone.utc)

    @staticmethod
    def validate_crew_yaml(yaml_content: str) -> List[str]:
        """校验 YAML 配置"""
        return CrewConfigValidator.validate_yaml(yaml_content)

    @staticmethod
    def validate_crew_yaml_file(yaml_path: str) -> List[str]:
        """校验 YAML 文件配置"""
        return CrewConfigValidator.validate_yaml_file(yaml_path)


# 全局服务实例
_crew_service: Optional[CrewService] = None


def get_crew_service() -> CrewService:
    """获取 Crew 服务实例（单例）"""
    global _crew_service
    if _crew_service is None:
        _crew_service = CrewService()
    return _crew_service
