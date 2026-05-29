"""
end_execution 工具

Agent 调用此工具来请求停止整个编排执行。
典型场景：
- Worker 在黑板中找不到分配的任务，编排无法继续
- Agent 发现前置条件不满足，继续执行没有意义
"""

from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus

# Orchestrator 通过检查 Agent 输出中是否包含此标记来决定是否中止编排
STOP_ORCHESTRATION_MARKER = "[STOP_ORCHESTRATION]"


class EndExecution(Tool):
    """
    Agent 调用此工具来请求停止整个编排执行。

    当 Agent 确认编排无法继续或不应该继续时，
    调用此工具可在编排层面优雅终止。
    """

    def __init__(self):
        super().__init__(max_content_length=500)

    @property
    def name(self) -> str:
        return "end_execution"

    @property
    def description(self) -> str:
        return (
            "Call this tool to request stopping the entire orchestration execution. "
            "Use when there is no work to do, a critical condition is not met, "
            "or continuing the workflow doesn't make sense. "
            "The orchestrator will gracefully abort the remaining steps."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "The reason for stopping the orchestration (e.g., 'no task assigned', 'prerequisite not met')",
                }
            },
            "required": ["reason"],
        }

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        reason = arguments.get("reason", "No reason provided")
        return ToolResult(
            status=ToolStatus.SUCCESS,
            content=f"{STOP_ORCHESTRATION_MARKER}: {reason}",
        )
