"""
@author: Rossi
@time: 2021-01-27
"""
import copy
from .event import SlotSetted


class DialogueStateTracker:
    def __init__(self, sender_id, agent) -> None:
        self.sender_id = sender_id
        self.agent = agent
        self.latest_message = None
        self.latest_skill = None
        self.slots = {}
        for slot in agent.slots:
            self.slots[slot.name] = copy.deepcopy(slot)
        self.events = []
        self.past_states = []
        self.active_form = None

    def current_state(self):
        state = {}
        state["latest_skill"] = self.latest_skill
        state["active_form"] = self.active_form
        intent = self.latest_message.get("intent")["name"]
        state["intent"] = intent
        intent_config = self.agent.intents[intent]
        if intent_config["use_entities"]:
            entities = {}
            parsed_entities = self.latest_message.get("entities")
            for entity in intent_config["use_entities"]:
                entity_values = parsed_entities.get(entity)
                if entity_values:
                    entities[entity] = [item["value"] for item in entity_values]
            state["entities"] = entities
        slots = {}
        for slot in self.slots.values():
            if slot.featurized:
                slots.update(slot.featurize())
        state["slots"] = slots
        return state

    def get_past_states(self):
        return self.past_states

    def pop_past_states(self):
        self.past_states.pop()

    def update_states(self):
        self.past_states.append(self.current_state())

    def update(self, event):
        self.events.append(event)
        event.apply(self)

    def add_user_message(self, message):
        self.latest_message = message
        entities = message.get("entities")
        if entities:
            events = []
            for slot in self.slots.values():
                if slot.from_entity:
                    entity_values = entities.get(slot.from_entity)
                    if entity_values:
                        values = [item["value"] for item in entity_values]
                        events.append(SlotSetted(slot.name, values))
            for event in events:
                self.update(event)

    def pop_user_message(self, message):
        self.latest_message = None

    def set_slot(self, slot, value):
        if slot in self.slots:
            self.slots[slot].value = value
    
    def get_slot(self, slot):
        slot = self.slots.get(slot)
        if slot:
            return slot.value
        return None

    def get_latest_intent(self):
        if self.latest_message is None:
            return None
        return self.latest_message.get("intent")["name"]

    def get_latest_entity_values(self, entity):
        if self.latest_message is None:
            return None
        entities = self.latest_message.get("entities")
        if entities:
            values = entities.get(entity)
            if values is None or len(values) == 0:
                return None
            else:
                return [value["value"] for value in values]
        return None

    def snapshot(self):
        return {
            "sender_id": self.sender_id, 
            "agent": self.agent,
            "latest_message": self.latest_message, 
            "slots": {slot.name: slot.value for slot in self.slots.values()}
        }