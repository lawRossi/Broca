"""
@author: Rossi
@time: 2021-01-26
"""
from Broca.message import BotMessage
from .event import SkillStarted, SkillEnded, BotUttered, SlotSetted, Form, Undo


class Skill:
    def __init__(self):
        self.name = None
        self.trigger_intent = None
        self.intent_patterns = None
        self.bot_atterances = []

    def perform(self, tracker, **parameters):
        events = [SkillStarted()]
        more_events = self._perform(tracker, **parameters)
        if more_events:
            events.extend(more_events)
        events.extend(self.bot_atterances)
        events.append(SkillEnded(self.name))
        return events

    def _perform(self, tracker, **parameters):
        return []

    def utter(self, text, data=None):
        bot_message = BotMessage(text, data)
        utterance = BotUttered(bot_message)
        self.bot_atterances.append(utterance)

    def generate_script(self):
        if self.trigger_intent:
            return {self.trigger_intent: self.name}
        return None


class ListenSkill(Skill):
    def __init__(self):
        super().__init__()
        self.name = "listen"


class FormSkill(Skill):
    FROM_ENTITY = "from_entity"
    FROM_INTENT = "from_intent"
    FROM_TEXT = "from_text"

    def __init__(self):
        super().__init__()
        self.required_slots = {}

    def from_entity(self, entity, intents=None, not_intents=None):
        return {"type": self.FROM_ENTITY, "entity": entity, "intents": intents, "not_intents": not_intents}

    def from_intent(self, value, intents=None, not_intents=None):
        return {"type": self.FROM_INTENT, "value": value, "intents": intents, "not_intents": not_intents}

    def from_text(self, intents=None, not_intents=None):
        return {"type": self.FROM_TEXT, "intents": intents, "not_intents": not_intents}

    def slot_mappings(self):
        return {}

    def get_mappings_for_slot(self, slot_name):
        mappings = self.slot_mappings()
        return mappings.get(slot_name, self.from_entity(slot_name))

    def id_desired_intent(self, slot_mapping, tracker):
        intent = tracker.get_latest_intent()
        intents = slot_mapping["intents"]
        not_intents = slot_mapping["not_intents"]
        return (intents is None or intent in intents) and (not_intents is None or intent not in not_intents)

    def is_desired_entity(self, slot_mapping, tracker):
        entity = slot_mapping["entity"]
        return tracker.get_latest_entity_values(entity) is not None

    def extract_required_slots(self, tracker):
        slot_dict = {}
        for slot_to_fill, config in self.required_slots.items():
            for slot_mapping in self.get_mappings_for_slot(slot_to_fill):
                if self.id_desired_intent(slot_mapping, tracker):
                    value = None
                    if slot_mapping["type"] == self.FROM_ENTITY:
                        value = tracker.get_latest_entity_values(slot_mapping["entity"])
                    elif slot_mapping["type"] == self.FROM_INTENT:
                        value = slot_mapping["value"]
                    elif slot_mapping["type"] == self.FROM_TEXT:
                        value = tracker.latest_message.text
                    if value is None and config.get("prefilled", True):  # try to find a prefilled slot vlaue
                        value = tracker.get_slot(slot_to_fill)
                    if value is None and config.get("default") is not None:
                        default = config["default"]
                        if callable(default):
                            value = default()
                        else:
                            value = default
                    if value is not None:
                        slot_dict[slot_to_fill] = value
                        break
        return self.validate(slot_dict)

    def validate(self, slot_dict):
        valid_slot_dict = {}
        for slot_name, value in slot_dict.items():
            validate_func_name = f"validate_{slot_name}"
            if hasattr(self, validate_func_name):
                validate_func = getattr(self, )
                if validate_func(value):
                    valid_slot_dict[slot_name] = value
            else:
                valid_slot_dict[slot_name] = value
        return valid_slot_dict

    def _activate_if_required(self, tracker):
        if tracker.active_form != self.name:
            return [Form(self.name)]
        else:
            return []

    def _submit(self, tracker_snapshot):
        return []

    def _perform(self, tracker, **parameters):
        events = self._activate_if_required(tracker)
        slot_dict = self.extract_required_slots(tracker)
        events.extend([SlotSetted(slot, value) for slot, value in slot_dict.items() if tracker.get_slot(slot) != value])
        next_to_fill_slot = None
        for slot_name in self.required_slots:
            if slot_name not in slot_dict:
                next_to_fill_slot = slot_name
                break
        if next_to_fill_slot:
            utter_func = getattr(self, f"utter_ask_{next_to_fill_slot}")
            self.utter(utter_func(tracker))
        else:
            snapshot = tracker.snapshot()
            snapshot["slots"].update(slot_dict)
            events.extend(self._submit(snapshot))
            events.append(Form(None))  # deactivate
        return events


class DeactivateFormSkill(Skill):
    def __init__(self):
        super().__init__()
        self.name = "deactivate_form"
    
    def _perform(self, tracker, **parameters):
        return [Form(None)]


class UndoSkill(Skill):
    def __init__(self):
        super().__init__()
        self.name = "undo"
    
    def perform(self, tracker, **parameters):
        return [Undo()]
