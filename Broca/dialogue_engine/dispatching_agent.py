from Broca.message import UserMessage
from Broca.task_engine.agent import Agent
from Broca.task_engine.event import AgentTriggered, BotUttered, UserUttered


class DispatchingAgent(Agent):
    def set_dialogue_engine(self, dialogue_engine):
        self.dialogue_engine = dialogue_engine

    def handle_message(self, message):
        self._parse_if_needed(message)
        uttered = UserUttered(message)
        tracker = self.tracker_store.get_tracker(message.sender_id)
        tracker.update(uttered)
        self.listen(tracker)
        skill_name = self.policy.pick_skill(tracker)
        responses = []
        triggered_event = None
        if skill_name is not None:
            while skill_name is not None:
                skill_name, parameters = self._parse_skill_name(skill_name)
                skill = self.skills[skill_name]()
                for event in skill.perform(tracker, **parameters):
                    tracker.update(event)
                    if isinstance(event, BotUttered):
                        bot_message = event.bot_message
                        responses.append(bot_message)
                    elif isinstance(event, AgentTriggered):
                        triggered_event = event
                skill_name = self.policy.pick_skill(tracker)
        self.tracker_store.update_tracker(tracker)
        if triggered_event is not None:
            new_message = UserMessage(
                message.sender_id,
                triggered_event.text,
                external_intent=triggered_event.intent,
                external_entities=triggered_event.entities
            )
            responses.extend(self.dialogue_engine.handel_message_with_engines(new_message))
        return responses
