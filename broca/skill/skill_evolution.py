"""
Skill Evolution — 子 Agent 工具函数

参考 SessionMemoryManager._run_extraction_subagent() 的模式，
提供创建子 Agent 执行 Skill 创建和改进建议的公共工具函数。
"""

import asyncio
import copy

from broca.agent_manager import AgentFactory
from broca.logging_config import get_logger
from broca.loop_engine import ExecutionStatus
from broca.session import MessageProtocol

logger = get_logger(__name__)


async def run_skill_sub_agent(
    agent,
    prompt: str,
    allowed_tools: list[str],
    task_timeout: int = 120,
) -> tuple[bool, str]:
    """创建子 Agent，fork 当前上下文，执行指定 prompt。

    参考 SessionMemoryManager._run_extraction_subagent() 模式。

    Args:
        agent: 主 Agent 实例
        prompt: 发给子 Agent 的指令
        allowed_tools: 子 Agent 允许使用的工具列表
        task_timeout: 超时秒数

    Returns:
        (success: bool, message: str)
    """
    agent_factory = AgentFactory()
    session_manager = agent.session_manager
    agent_id = session_manager.session_id + "#skill-evolution-agent"

    try:
        # 创建或恢复子 Agent
        agent_config = await session_manager.get_agent_config(agent_id)
        if agent_config is None:
            agent_config = agent.config.to_dict()
            agent_config["name"] = "skill-evolution-agent"
            agent_config["role"] = "skill_evolution"
            agent_config["track_session_momory"] = False
            agent_config["enable_context_compression"] = False
            agent_config["save_history"] = False
            agent_config["interactive"] = False

            sub_agent = await agent_factory.create_agent(
                agent_config=agent_config,
                session_manager=session_manager,
                agent_id=agent_id,
            )
        else:
            sub_agent = agent_factory.get_agent(
                session_manager.session_id, agent_config["name"]
            )
            if sub_agent is None:
                sub_agent = await agent_factory.restore_agent(agent_id, session_manager)

        # 确保子 Agent 在运行
        if not sub_agent.running:
            task = asyncio.create_task(sub_agent.start())
            task.add_done_callback(lambda t, a=sub_agent: a.stop())

        # Fork 当前上下文
        sub_agent.context.history = copy.copy(agent.context.history)

        # 发送消息并执行
        trigger_message = MessageProtocol.create_user_message(content=prompt)
        result = await sub_agent.run(
            trigger_message,
            from_agent=True,
            allowed_tools=allowed_tools,
        )

        if result.status != ExecutionStatus.COMPLETED:
            logger.warning(
                f"Skill sub-agent execution failed: {result.status}: {result.message}"
            )
            return False, f"Execution failed: {result.status.value}"

        return True, "Completed successfully"

    except asyncio.TimeoutError:
        logger.error("Skill sub-agent execution timed out")
        return False, f"Execution timed out after {task_timeout}s"
    except Exception as e:
        logger.error(f"Skill sub-agent execution error: {e}")
        return False, f"Execution error: {e}"
