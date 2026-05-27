"""Crew Service

管理编排执行的生命周期，通过 IPC 与 Runner 进程通信。
执行记录持久化到数据库（CrewExecution 模型）。
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from broca.orchestration.crew import CrewConfig, CrewConfigValidator
from broca.session.database import db_manager
from broca.session.models import CrewExecution, CrewExecutionStatus, Message, MessageRole, MessageType
from broca.session_runner import RunnerManager
from broca.session_runner.models import IPCMessageType
from loguru import logger
from sqlalchemy import desc, select


class CrewService:
    """编排服务

    管理编排执行的生命周期：提交、查询状态、中止。
    所有执行记录持久化到数据库。
    通过 RunnerManager 的 IPC 通道与 Runner 进程通信。
    """

    def __init__(self):
        self._runner_manager = RunnerManager()

    # ==========================================================================
    # 数据库操作辅助
    # ==========================================================================

    @staticmethod
    def _execution_to_dict(execution: CrewExecution) -> dict[str, Any]:
        """将 CrewExecution 模型转为前端所需的字典格式"""
        # 解析 yaml_content 获取摘要信息
        crew_name = execution.crew_name
        description = ""
        agent_count = 0
        try:
            cfg = CrewConfig.from_yaml(execution.yaml_content)
            crew_name = cfg.name or execution.crew_name
            description = cfg.description or ""
            agent_count = len(cfg.agents) if cfg.agents else 0
        except Exception:
            pass

        # 解析 phases_json
        phases = []
        if execution.phases_json:
            try:
                phases = (
                    json.loads(execution.phases_json)
                    if isinstance(execution.phases_json, str)
                    else execution.phases_json
                )
            except (json.JSONDecodeError, TypeError):
                phases = []

        # 解析 result_json
        result = None
        if execution.result_json:
            try:
                result = (
                    json.loads(execution.result_json)
                    if isinstance(execution.result_json, str)
                    else execution.result_json
                )
            except (json.JSONDecodeError, TypeError):
                result = {"raw": execution.result_json}

        return {
            "execution_id": execution.execution_id,
            "session_id": execution.session_id,
            "crew_name": crew_name,
            "description": description,
            "orchestrator_type": execution.orchestrator_type,
            "agent_count": agent_count,
            "status": execution.status.value if hasattr(execution.status, "value") else execution.status,
            "error": execution.error_message,
            "result": result,
            "phases": phases,
            "created_at": execution.started_at.isoformat() if execution.started_at else None,
            "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
        }

    # ==========================================================================
    # 编排提交与执行
    # ==========================================================================

    async def submit_crew(
        self,
        crew_config: CrewConfig,
        session_id: str,
    ) -> dict[str, Any]:
        """提交编排执行

        Args:
            crew_config: Crew 配置
            session_id: 目标 Session ID

        Returns:
            编排执行记录字典

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

        # 3. 创建数据库记录
        execution_id = f"crew-{uuid.uuid4().hex[:12]}"
        yaml_content = crew_config.to_json()

        db_record = CrewExecution(
            execution_id=execution_id,
            session_id=session_id,
            crew_name=crew_config.name,
            orchestrator_type=crew_config.orchestrator.type.value if crew_config.orchestrator else "pipeline",
            yaml_content=yaml_content,
            status=CrewExecutionStatus.RUNNING,
            started_at=datetime.now(UTC),
        )

        async with db_manager.get_session() as session:
            session.add(db_record)
            await session.commit()
            await session.refresh(db_record)

        # 4. 通过 IPC 发送编排命令到 Runner
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
            # 更新数据库记录为失败
            async with db_manager.get_session() as session:
                result = await session.get(CrewExecution, execution_id)
                if result:
                    result.status = CrewExecutionStatus.FAILED
                    result.error_message = response["error"]
                    result.completed_at = datetime.now(UTC)
                    session.add(result)
                    await session.commit()

            logger.error(f"Crew submission failed: {response['error']}")
        else:
            logger.info(f"Crew '{crew_config.name}' submitted, execution_id={execution_id}")

        # 重新读取返回
        async with db_manager.get_session() as session:
            saved = await session.get(CrewExecution, execution_id)
            return self._execution_to_dict(saved) if saved else self._execution_to_dict(db_record)

    async def submit_crew_from_yaml(
        self,
        yaml_content: str,
        session_id: str,
    ) -> dict[str, Any]:
        """从 YAML 字符串提交编排"""
        crew_config = CrewConfig.from_yaml(yaml_content)
        return await self.submit_crew(crew_config, session_id)

    async def submit_crew_from_file(
        self,
        yaml_path: str,
        session_id: str,
    ) -> dict[str, Any]:
        """从 YAML 文件提交编排"""
        crew_config = CrewConfig.from_yaml_file(yaml_path)
        return await self.submit_crew(crew_config, session_id)

    # ==========================================================================
    # 查询
    # ==========================================================================

    async def get_execution(self, execution_id: str) -> dict[str, Any] | None:
        """获取执行记录"""
        async with db_manager.get_session() as session:
            record = await session.get(CrewExecution, execution_id)
            return self._execution_to_dict(record) if record else None

    async def list_executions(
        self,
        session_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """列出执行记录"""
        async with db_manager.get_session() as session:
            query = select(CrewExecution)

            if session_id:
                query = query.where(CrewExecution.session_id == session_id)
            if status:
                query = query.where(CrewExecution.status == status)

            query = query.order_by(desc(CrewExecution.started_at))

            result = await session.execute(query)
            records = result.scalars().all()
            return [self._execution_to_dict(r) for r in records]

    # ==========================================================================
    # 中止
    # ==========================================================================

    async def abort_execution(self, execution_id: str) -> bool:
        """中止编排执行"""
        async with db_manager.get_session() as session:
            record = await session.get(CrewExecution, execution_id)
            if not record:
                return False

            await self._runner_manager.send_command(
                session_id=record.session_id,
                msg_type=IPCMessageType.CMD_ABORT_CREW,
                payload={"crew_id": record.crew_name, "execution_id": execution_id},
            )

            record.status = CrewExecutionStatus.ABORTED
            record.completed_at = datetime.now(UTC)
            session.add(record)
            await session.commit()

            # 实时推送编排事件到前端
            await _emit_crew_event("aborted", service._execution_to_dict(record), record.session_id)
            return True

    # ==========================================================================
    # IPC 事件处理（由 RunnerManager 回调）
    # ==========================================================================

    @staticmethod
    async def handle_crew_event(session_id: str, msg: Any) -> None:
        """处理来自 Runner 的编排事件（由 RunnerManager 回调）
        将进度/结果更新持久化到数据库。
        """
        service = get_crew_service()
        payload = msg.payload
        execution_id = payload.get("execution_id")
        if not execution_id:
            return

        msg_type = msg.type
        async with db_manager.get_session() as session:
            record = await session.get(CrewExecution, execution_id)
            if not record:
                logger.warning(f"Crew event for unknown execution: {execution_id}")
                return

            if msg_type == IPCMessageType.EVT_CREW_START:
                record.status = CrewExecutionStatus.RUNNING
                logger.info(f"[CrewService] '{record.crew_name}' started (exec={execution_id})")

            elif msg_type == IPCMessageType.EVT_CREW_PROGRESS:
                phases = payload.get("phases")
                if phases:
                    record.phases_json = json.dumps(phases, ensure_ascii=False)
                progress = payload.get("progress", 0)
                logger.info(f"[CrewService] '{record.crew_name}' progress: {progress:.0%}")

            elif msg_type == IPCMessageType.EVT_CREW_COMPLETE:
                record.status = CrewExecutionStatus.COMPLETED
                final_output = payload.get("final_output")
                if final_output:
                    record.result_json = json.dumps(final_output, ensure_ascii=False)
                phases = payload.get("phases", [])
                if phases:
                    record.phases_json = json.dumps(phases, ensure_ascii=False)
                record.completed_at = datetime.now(UTC)
                logger.info(f"[CrewService] '{record.crew_name}' completed (exec={execution_id})")

            elif msg_type == IPCMessageType.EVT_CREW_ERROR:
                record.status = CrewExecutionStatus.FAILED
                record.error_message = payload.get("error", "Unknown error")
                phases = payload.get("phases", [])
                if phases:
                    record.phases_json = json.dumps(phases, ensure_ascii=False)
                record.completed_at = datetime.now(UTC)
                logger.error(f"[CrewService] '{record.crew_name}' failed: {record.error_message}")

            session.add(record)
            await session.commit()

            # 实时推送编排事件到前端
            event_name = msg_type.value.replace("evt_crew_", "") if hasattr(msg_type, "value") else str(msg_type)
            await _emit_crew_event(event_name, service._execution_to_dict(record), session_id)

    # ==========================================================================
    # 校验
    # ==========================================================================

    @staticmethod
    def validate_crew_yaml(yaml_content: str) -> list[str]:
        """校验 YAML 配置"""
        return CrewConfigValidator.validate_yaml(yaml_content)

    @staticmethod
    def validate_crew_yaml_file(yaml_path: str) -> list[str]:
        """校验 YAML 文件配置"""
        return CrewConfigValidator.validate_yaml_file(yaml_path)

    # ==========================================================================
    # Workspace crew_configs 目录管理
    # ==========================================================================

    @staticmethod
    def list_crew_configs(workspace: str) -> list[dict[str, Any]]:
        """扫描 workspace 下的 crew_configs 目录，列出所有有效的编排配置文件。"""
        crew_configs_dir = os.path.join(workspace, "crew_configs")
        if not os.path.isdir(crew_configs_dir):
            return []

        configs = []
        for fname in sorted(os.listdir(crew_configs_dir)):
            if not (fname.endswith(".yaml") or fname.endswith(".yml")):
                continue

            fpath = os.path.join(crew_configs_dir, fname)
            if not os.path.isfile(fpath):
                continue

            try:
                cfg = CrewConfig.from_yaml_file(fpath)
                configs.append(
                    {
                        "filename": fname,
                        "path": fpath,
                        "name": cfg.name,
                        "description": cfg.description,
                        "orchestrator_type": cfg.orchestrator.type.value if cfg.orchestrator else None,
                        "agent_count": len(cfg.agents) if cfg.agents else 0,
                        "agent_names": [a.name for a in cfg.agents] if cfg.agents else [],
                        "modified_time": os.path.getmtime(fpath),
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to parse crew config {fname}: {e}")
                configs.append(
                    {
                        "filename": fname,
                        "path": fpath,
                        "name": fname,
                        "description": f"(解析失败: {e!s})",
                        "orchestrator_type": None,
                        "agent_count": 0,
                        "agent_names": [],
                        "modified_time": os.path.getmtime(fpath),
                        "parse_error": str(e),
                    }
                )

        return configs

    @staticmethod
    def get_crew_config_content(workspace: str, filename: str) -> dict[str, Any]:
        """获取 workspace crew_configs 目录下指定配置文件的内容。"""
        if "/" in filename or "\\" in filename or ".." in filename:
            raise ValueError(f"Invalid filename: {filename}")

        crew_configs_dir = os.path.join(workspace, "crew_configs")
        fpath = os.path.join(crew_configs_dir, filename)

        if not os.path.isfile(fpath):
            raise FileNotFoundError(f"Crew config file not found: {filename}")

        with open(fpath, encoding="utf-8") as f:
            content = f.read()

        summary = {}
        try:
            cfg = CrewConfig.from_yaml(content)
            summary = {
                "name": cfg.name,
                "description": cfg.description,
                "orchestrator_type": cfg.orchestrator.type.value if cfg.orchestrator else None,
                "agent_count": len(cfg.agents) if cfg.agents else 0,
                "agent_names": [a.name for a in cfg.agents] if cfg.agents else [],
            }
        except Exception as e:
            summary = {"parse_error": str(e)}

        return {
            "filename": filename,
            "path": fpath,
            "content": content,
            "summary": summary,
            "modified_time": os.path.getmtime(fpath),
        }

    @staticmethod
    def save_crew_config(workspace: str, filename: str, content: str) -> dict[str, Any]:
        """保存/更新 workspace crew_configs 目录下的配置文件。"""
        if "/" in filename or "\\" in filename or ".." in filename:
            raise ValueError(f"Invalid filename: {filename}")

        if not (filename.endswith(".yaml") or filename.endswith(".yml")):
            raise ValueError(f"Filename must end with .yaml or .yml: {filename}")

        crew_configs_dir = os.path.join(workspace, "crew_configs")
        os.makedirs(crew_configs_dir, exist_ok=True)

        fpath = os.path.join(crew_configs_dir, filename)

        try:
            cfg = CrewConfig.from_yaml(content)
        except Exception as e:
            raise ValueError(f"Invalid YAML content: {e!s}")

        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"Saved crew config: {fpath}")

        return {
            "filename": filename,
            "path": fpath,
            "name": cfg.name,
            "description": cfg.description,
            "orchestrator_type": cfg.orchestrator.type.value if cfg.orchestrator else None,
            "agent_count": len(cfg.agents) if cfg.agents else 0,
            "agent_names": [a.name for a in cfg.agents] if cfg.agents else [],
            "modified_time": os.path.getmtime(fpath),
        }


# 全局服务实例
_crew_service: CrewService | None = None
# Socket.IO 服务器引用（由 app startup 时注入）
_socketio_server: Any = None


def get_crew_service() -> CrewService:
    """获取 Crew 服务实例（单例）"""
    global _crew_service
    if _crew_service is None:
        _crew_service = CrewService()
    return _crew_service


def set_socketio_server(server: Any) -> None:
    """注入 Socket.IO 服务器实例（用于实时推送编排进度）"""
    global _socketio_server
    _socketio_server = server
    logger.info("SocketIO server injected into CrewService")


async def _emit_crew_event(event: str, data: dict[str, Any], session_id: str) -> None:
    """通过 Socket.IO 广播编排事件（按 session 隔离频道）"""
    global _socketio_server
    if not _socketio_server:
        return
    try:
        sub = f"crew:{session_id}"
        message = Message(
            message_type=MessageType.SYSTEM_MESSAGE,
            role=MessageRole.SYSTEM,
            sender_id="system",
            data={"crew_event": event, "payload": data},
            subscription=sub,
        )
        await _socketio_server.send_message(message, subscription=sub)
    except Exception as e:
        logger.warning(f"Failed to emit crew event via SocketIO: {e}")
