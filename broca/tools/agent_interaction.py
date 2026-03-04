from broca.tools.tool import Tool, ToolCallContext


class AssignTask(Tool):
    def __init__(self):
        super().__init__()

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
                "agent_id": {
                    "type": "string",
                    "description": "the id of the agent to assign the task to",
                },
                "task_id": {
                    "type": "string",
                    "description": "the id of the task",
                },
                "task": {
                    "type": "string",
                    "description": "a self-explanatory description of the task",
                },
            },
            "required": ["agent", "task_id", "task"],
        }

    async def _execute(self, arguments, context: ToolCallContext):
        agent_id = arguments["agent_id"]
        task_id = arguments["task_id"]
        task = arguments["task"]

        agent = context.agent
        await agent.communicator.send_task_start(task_id, task, receiver_id=agent_id)

        return "The task has been assigned to the agent and you will be notified when it is completed."
