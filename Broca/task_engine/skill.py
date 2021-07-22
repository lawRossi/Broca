"""
@author: Rossi
@time: 2021-01-26
"""
from Broca.message import BotMessage
from .event import ExternalEnd, ExternalStart, SkillStarted, SkillEnded
from .event import BotUttered, SlotSetted, Form, Undo
from collections import OrderedDict, defaultdict
import re


class Skill:
    def __init__(self):
        self.name = None
        self.trigger_intent = None
        self.intent_patterns = None
        self.bot_atterances = []
        self.events = []

    def perform(self, tracker, **parameters):
        self.events.append(SkillStarted())
        more_events = self._perform(tracker, **parameters)
        if more_events:
            self.events.extend(more_events)
        self.events.extend(self.bot_atterances)
        self.events.append(SkillEnded(self.name))
        return self.events

    def _perform(self, tracker, **parameters):
        return []

    def utter(self, text, receiver_id, data=None):
        bot_message = BotMessage(receiver_id, text, data)
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
    STARTED = "STARTED"
    IN_PROGRESS = "IN-PROGRESS"

    slot_cache = defaultdict(lambda : dict())
    slot_trials = defaultdict(lambda : defaultdict(int))
    parameters_cache = defaultdict(lambda : dict())
    stages = defaultdict(lambda : dict())

    def __init__(self):
        super().__init__()
        self.required_slots = {}
        self.terminated = False

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
        return mappings.get(slot_name, [self.from_entity(slot_name)])

    def is_desired_intent(self, slot_mapping, tracker):
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
                if self.is_desired_intent(slot_mapping, tracker):
                    value = None
                    if slot_mapping["type"] == self.FROM_ENTITY:
                        value = tracker.get_latest_entity_values(slot_mapping["entity"])
                    elif slot_mapping["type"] == self.FROM_INTENT:
                        value = slot_mapping["value"]
                    elif slot_mapping["type"] == self.FROM_TEXT:
                        value = tracker.latest_message.text
                    if value is None:
                        if config.get("prefilled", True):  # try to find a prefilled slot vlaue
                            value = tracker.get_slot(slot_to_fill)
                        else: # try to find the prefilled value in this form
                            value = self.slot_cache[self.name].get(slot_to_fill)
                    else:
                        if not config.get("prefilled", True):
                            self.slot_cache[self.name][slot_to_fill] = value
                    if value is None and config.get("default") is not None:
                        default = config["default"]
                        if callable(default):
                            value = default()
                        else:
                            value = default
                    if value is not None:
                        slot_dict[slot_to_fill] = value
                        break
        return self.validate(slot_dict, tracker)

    def validate(self, slot_dict, tracker):
        valid_slot_dict = {}
        for slot_name, value in slot_dict.items():
            validate_func_name = f"validate_{slot_name}"
            if hasattr(self, validate_func_name):
                validate_func = getattr(self, validate_func_name)
                value = validate_func(value, tracker)
                if value is not None:
                    valid_slot_dict[slot_name] = value
            else:
                valid_slot_dict[slot_name] = value
        return valid_slot_dict
    
    def perform(self, tracker, **parameters):
        events = super().perform(tracker, **parameters)
        parameters = self.parameters_cache[self.name].get(tracker.sender_id, {})
        if parameters.get("options") is True:
            events.append(ExternalStart())
            events.append(Form("option_form_skill"))
            events.append(SkillEnded("listen"))   # to activate the option form            
        return events

    def _activate_if_required(self, tracker):
        if tracker.active_form != self.name:
            return [Form(self.name)]
        else:
            return []

    def _submit(self, tracker_snapshot):
        return []
    
    def _is_started(self, tracker):
        stage = self.stages.get(self.name).get(tracker.sender_id)
        return stage == self.STARTED

    def _clear_slot_cache_if_required(self, tracker, **parameters):
        if self._is_started(tracker): # begining of this form
            flag = parameters.get("clear_slot", True)
            if flag:
                self.slot_cache[self.name].clear()

    def _perform(self, tracker, **parameters):
        self._check_stage(tracker)
        if parameters:
            self.parameters_cache[self.name][tracker.sender_id] = parameters
        else:
            parameters = self.parameters_cache.get(self.name, {}).get(tracker.sender_id, {})
        self._clear_slot_cache_if_required(tracker, **parameters)
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
            utterance = utter_func(tracker)
            if utterance:
                self.utter(utterance, tracker.sender_id)
            self.slot_trials[tracker.sender_id][next_to_fill_slot] += 1
            if self.terminated:
                self.slot_trials[tracker.sender_id].clear()
                return [Form(None)]
        else:
            snapshot = tracker.snapshot()
            snapshot["slots"].update(slot_dict)
            events.extend(self._submit(snapshot))
            events.append(Form(None))  # deactivate
            self.slot_trials[tracker.sender_id].clear()
            self.parameters_cache[tracker.sender_id].clear()
            self._terminate(tracker.sender_id)
        return events

    def _check_stage(self, tracker):
        stage = self.stages.get(self.name, {}).get(tracker.sender_id, None) 
        if stage is None:
            self.stages[self.name][tracker.sender_id] = self.STARTED
        elif stage == self.STARTED:
            self.stages[self.name][tracker.sender_id] = self.IN_PROGRESS

    def _terminate(self, sender_id):
        self.terminated = True
        self.stages[self.name][sender_id] = None

    def _show_options_form(self, tracker, options):
        self.events.append(SlotSetted("options_slot", options))
        if self.parameters_cache[self.name].get(tracker.sender_id) is None:
            self.parameters_cache[self.name][tracker.sender_id] = {}
        self.parameters_cache[self.name][tracker.sender_id]["options"] = True
        self.events.append(SlotSetted("main_form", self.name))

    def _hide_options_form(self, tracker):
        self.parameters_cache[self.name][tracker.sender_id]["options"] = False


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


class ConfirmSkill(FormSkill):
    def __init__(self):
        super().__init__()
        self.name = "confirm_form_skill"
        self.required_slots = OrderedDict({"confirmed_slot": {"prefilled": False}})

    def slot_mappings(self):
        return {"confirmed_slot": [self.from_text()]}

    def validate_confirmed_slot(self, value, tracker):
        if value.lower() in ["是的", "没问题", "ok", "确定", "确认", "好的", "没错"]:
            return True
        elif value in ["取消"]:
            return False
        return None

    def utter_ask_confirmed_slot(self, tracker):
        utterance = tracker.get_slot("form_utterance")
        utterance = utterance or "确定吗？"
        return utterance

    def perform(self, tracker, **parameters):
        events = super().perform(tracker, **parameters)
        if tracker.active_form != self.name:
            events.insert(0, ExternalStart())
        return events


class OptionSkill(FormSkill):
    number = "\d+|[一二三四五六七八九十]"
    reference = re.compile(f"((?P<base>上面|下面|倒数|前面|后面|底下)?第)?(?P<index>{number})(个|这个|那个)?")
    top = re.compile("(最)?上面(的|那个|这个|个)")
    middle = re.compile("(最)?中间(的|那个|这个|个)")
    bottom = re.compile("(最)?(下面|底下|后|后面)(一个|的|那个|这个|个)")
    description = re.compile("(?P<term>.+?)(这个|那个|的)?")
    digit_mapping = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九":9, "十": 10}
    base_mapping = {"上面": 1, "下面": -1, "倒数": -1, "前面": 1, "后面": -1, "底下": -1}

    def __init__(self):
        super().__init__()
        self.name = "option_form_skill"
        self.required_slots = OrderedDict({"option_slot": {"prefilled": False}})

    def slot_mappings(self):
        return {"option_slot": [self.from_text()]}

    def validate_option_slot(self, value, tracker):
        options = tracker.get_slot("options_slot")
        index = self._parse_reference(value, options)
        if index is None:
            index = self._parse_description(value, options)            
        if index is not None and -len(options) <= index < len(options):
            return options[index]
        else:
            return None

    def _parse_reference(self, value, options):
        index = None
        reverse = False
        m = self.reference.match(value)
        if m:
            index = m.group("index")
            if m.group("base"):
                reverse = self.base_mapping[m.group("base")] == -1
        elif self.top.match(value):
            return 0
        elif self.middle.match(value):
            return len(options) // 2
        elif self.bottom.match(value):
            return -1
        if index is not None:
            if index.isdigit():
                index = int(index)
            else:
                index = self.digit_mapping[index]
            if reverse:
                index *= -1
            else:
                index -= 1   # index starts with 0
        return index

    def _parse_description(self, value, options):
        m = self.description.match(value)
        if m:
            term = m.group("term")
            for i, option in enumerate(options):
                if term in option["value"]:
                    return i
        return None

    def utter_ask_option_slot(self, tracker):
        utterance = tracker.get_slot("form_utterance")
        options = tracker.get_slot("options_slot")
        for option in options:
            utterance += "\n  " + option["value"]
        return utterance

    def perform(self, tracker, **parameters):
        events = super().perform(tracker, **parameters)

        if self.terminated:
            events.append(ExternalEnd())
            self.events.append(SlotSetted("main_form", None))   # return to the main form
            self.events.append(Form(tracker.get_slot("main_form")))
            self.events.append(SkillEnded("listen"))
        return events
