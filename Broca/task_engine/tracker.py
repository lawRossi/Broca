"""
@author: Rossi
@time: 2021-01-27
"""

import copy

from .event import SkillEnded, SlotSetted, UserUttered, Form


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
        self.active_scene = None
        self.scene_expire_time = None
        self.turns = 0

    def init_copy(self):
        tracker = DialogueStateTracker(self.sender_id, self.agent)
        return tracker

    def copy(self):
        tracker = self.init_copy()
        for event in self.events:
            tracker.update(event)
        return tracker

    def current_state(self):
        state = {}
        state["latest_skill"] = self.latest_skill
        state["active_form"] = self.active_form
        if self.latest_message:
            intent = self.latest_message.get("intent")
            if intent:
                agent = intent.get("agent")
                intent_name = "public#" + intent["name"] if agent == "public" else intent["name"]
            else:
                intent_name = None
        else:
            intent_name = None
        state["intent"] = intent_name
        intent_config = self.agent.intents.get(intent_name)
        if intent_config and intent_config["use_entities"]:
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

    def pop_last_state(self):
        self.past_states.pop()

    def update_states(self):
        self.past_states.append(self.current_state())

    def update(self, event):
        self.events.append(event)
        event.apply(self)

    def add_user_message(self, message):
        self.latest_message = message
        entities = message.get("entities")
        self.turns += 1
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

    def pop_user_message(self):
        self.latest_message = None

    def set_slot(self, slot, value):
        if slot in self.slots:
            self.slots[slot].value = value
            self.slots[slot].turn_no = self.turns

    def get_slot(self, slot, within_turns=None):
        slot = self.slots.get(slot)
        if slot:
            if slot.value is None:
                return None
            if within_turns is not None and self.turns - slot.turn_no + 1 > within_turns:
                return None
            return slot.value
        return None

    def get_slot_values(self, within_turns=None):
        slot_values = {}
        for slot_name, slot in self.slots.items():
            if slot:
                if within_turns is not None and self.turns - slot.turn_no + 1 > within_turns:
                    continue
                slot_values[slot_name] = slot.value
        return slot_values

    def get_latest_intent(self):
        if self.latest_message is None:
            return None
        intent = self.latest_message.get("intent")
        if not intent:
            return None
        return intent["name"]

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

    def get_last_n_turns_events(self, turns, ignoring_in_form_skills=True):
        events = []
        if turns == 0:
            return events
        n = 0
        in_form = False
        for event in reversed(self.events):
            if in_form and ignoring_in_form_skills:
                if not isinstance(event, SlotSetted) and not isinstance(event, Form):
                    continue
            if isinstance(event, UserUttered):
                events.append(event)
                n += 1
                if n == turns:
                    break
            elif isinstance(event, Form):
                if event.form is not None: # form activation
                    events.append(SkillEnded(event.form))
                events.append(event)
                in_form = True if not in_form else False
            else:
                events.append(event)
        return list(reversed(events))

    def snapshot(self):
        return {
            "sender_id": self.sender_id, 
            "agent": self.agent,
            "latest_message": self.latest_message, 
            "slots": {slot.name: slot.value for slot in self.slots.values()},
            "turns": self.turns
        }
