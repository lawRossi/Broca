"""
Memory Tool — 持久化记忆触发工具

已从 add/replace/remove 重构为触发记忆提取的工具。
调用后异步触发 PersistentMemoryManager 创建子 Agent 分析对话并更新记忆文件。
"""

from __future__ import annotations

import json

from broca.persistent_memory import PersistentMemoryManager
from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus


class MemoryTool(Tool):
    """持久化记忆管理工具 — 触发记忆提取"""

    def __init__(self):
        super().__init__(max_content_length=30000)

    @property
    def name(self) -> str:
        return "memory"

    @property
    def description(self) -> str:
        return (
            "Tell the agent to save important information to persistent memory. "
            "Calling this tool triggers a background memory extraction agent that "
            "analyzes the recent conversation and updates the memory files.\n\n"
            "WHEN TO USE:\n"
            "- User corrects you or says 'remember this' / 'don't do that again'\n"
            "- User shares a preference, habit, or personal detail (name, role, timezone, coding style)\n"
            "- You discover important non-derivable facts about the project or user\n"
            "- You need to ensure specific information persists across sessions\n\n"
            "The extraction agent will determine what to save and how to categorize it."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "hint": {
                    "type": "string",
                    "description": (
                        "Optional hint guiding the extraction agent on what to focus on. "
                        "Example: 'User prefers concise responses without summaries'"
                    ),
                },
            },
        }

    async def _execute(self, parameters: dict, context: ToolCallContext) -> ToolResult:
        try:
            hint = parameters.get("hint")

            # 获取 PersistentMemoryManager 实例
            manager = getattr(context, "persistent_memory_manager", None)
            if manager is None:
                # 尝试从 agent 获取
                agent = getattr(context, "agent", None)
                if agent:
                    manager = getattr(agent, "persistent_memory_manager", None)

            if manager is None:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content=json.dumps(
                        {
                            "success": False,
                            "error": (
                                "Persistent memory manager not available. "
                                "Please enable track_persistent_memory in agent config."
                            ),
                        },
                        ensure_ascii=False,
                    ),
                )

            # 获取上下文
            agent_context = getattr(context, "context", None)
            if agent_context is None and agent:
                agent_context = getattr(agent, "context", None)

            if agent_context is None:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content=json.dumps(
                        {
                            "success": False,
                            "error": "Agent context not available for memory extraction.",
                        },
                        ensure_ascii=False,
                    ),
                )

            # 触发异步提取（不 await，不阻塞主 Agent）
            asyncio_create_task = __import__("asyncio").create_task
            asyncio_create_task(
                manager.trigger_extraction(context=agent_context, hint=hint)
            )

            result = {
                "success": True,
                "message": "Memory extraction triggered",
            }
            if hint:
                result["hint"] = hint

            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=json.dumps(result, ensure_ascii=False, indent=2),
            )

        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=json.dumps(
                    {
                        "success": False,
                        "error": f"Memory tool execution failed: {str(e)}",
                    },
                    ensure_ascii=False,
                ),
            )
