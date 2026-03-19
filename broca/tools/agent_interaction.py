from broca.execution_engine import ExecutionStatus
from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus


class AssignTask(Tool):
    @property
    def name(self):
        return "assign_task"

    @property
    def description(self):
        return "Use this tool to assign a task to an agent."

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "description": "the agent to assign the task to",
                },
                "task_id": {
                    "type": "string",
                    "description": "the id of the task",
                },
                "task": {
                    "type": "string",
                    "description": "a self-explanatory description of the task",
                },
                "execution_type": {
                    "type": "string",
                    "description": "the execution type of the task",
                    "default": "blocking",
                    "enum": ["blocking", "background"],
                },
            },
            "required": ["agent", "task_id", "task"],
        }

    async def _execute(self, arguments, context: ToolCallContext) -> ToolResult:
        from broca.agent_manager import AgentFactory

        agent = context.agent
        factory = AgentFactory()
        agent_name = arguments["agent"]
        target_agent = factory.get_agent(agent.session_id, agent_name)
        if target_agent is None:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"Agent {agent_name} not found"
            )

        agent_id = target_agent.agent_id
        task_id = arguments["task_id"]
        task = arguments["task"]
        execution_type = arguments.get("execution_type", "blocking")
        if execution_type == "blocking":
            execution_result = await target_agent.run_async(task)
            message = target_agent.context.get_latest_assistant_message()
            if message:
                content = "Message from agent: " + message
            if execution_result.status == ExecutionStatus.COMPLETED:
                return ToolResult(status=ToolStatus.SUCCESS, content=content)
            elif execution_result.status == ExecutionStatus.ABORTED:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content=f"The agent {target_agent.agent_id} execution was aborted by user",
                )
            else:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content=f"The agent {target_agent.agent_id} failed to finish the task: {execution_result.error}",
                )
        else:
            await agent.communicator.send_task_start(
                task_id, task, receiver_id=agent_id
            )
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content="The task has been assigned to the agent and you will be notified when it is completed.",
            )
