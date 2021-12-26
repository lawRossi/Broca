"""
@Author: Rossi
Created At: 2021-07-14
"""

class Dispatcher:
    def dispatch(self, agents, message):
        """ dispatch the message to an appropriate agent.

        Args:
            agents (Broca.task_engine.agent.Agent): a list of agents.
            message (Broca.message.UserMessage): the user message in the current turn.

        Returns:
            Broca.task_engine.agent.Agent: the agent to handle the message
        """
        return None

    @classmethod
    def from_config(cls, config):
        return cls()


class DefaultDispatcher(Dispatcher):
    def dispatch(self, agents, message):
        for agent in agents:
            if agent.is_active(message.sender_id):
                return agent

        intent = message.get("intent")
        agent_name = intent.get("agent") if intent is not None else None

        if agent_name is not None and agent_name != "public":
            for agent in agents:
                if agent.name == agent_name:
                    return agent
        elif agent_name == "public":
            for agent in agents:
                if agent.can_handle_message(message):
                    return agent
        return None


class EntityMappingDispatcher(DefaultDispatcher):
    def __init__(self, entity_agent_mapping) -> None:
        super().__init__()
        self.entity_agent_mapping = entity_agent_mapping

    def dispatch(self, agents, message):
        for agent in agents:
            agent.parse(message)
        entities = message.get("entities")
        if entities:
            mapped_agents = set()
            for entity_type in entities:
                if entities.get(entity_type) and entity_type in self.entity_agent_mapping:
                    mapped_agents.add(self.entity_agent_mapping[entity_type])
            if len(mapped_agents) == 1:
                agent_name = mapped_agents.pop()
                for agent in agents:
                    if agent.name == agent_name:
                        return agent
        return None

    @classmethod
    def from_config(cls, config):
        entity_agent_mapping = config["entity_agent_mapping"]
        return cls(entity_agent_mapping)
