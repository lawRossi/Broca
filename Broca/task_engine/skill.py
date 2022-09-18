"""
@author: Rossi
@time: 2021-01-26
"""

from collections import defaultdict
import re

from Broca.message import BotMessage
from .event import SkillStarted, SkillEnded, BotUttered, SlotSetted
from .event import Form, Undo


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


class ReplySkill(Skill):

    def _perform(self, tracker, **parameters):
        slots = tracker.get_slot_values()
        message = self.template.format(**slots)
        self.utter(message, tracker.sender_id)
        return []


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

    slot_cache = defaultdict(lambda: dict())
    slot_trials = defaultdict(lambda: defaultdict(int))
    stages = defaultdict(lambda: dict())

    def __init__(self, required_slots):
        super().__init__()
        self.required_slots = required_slots
        self._build_utter_slot_func(required_slots)
        self.terminated = False
        self.cached_events = []
        self.max_slot_trials = 3

    def from_entity(self, entity, intents=None, not_intents=None):
        return {"type": self.FROM_ENTITY, "entity": entity, "intents": intents, "not_intents": not_intents}

    def from_intent(self, value, intents=None, not_intents=None):
        return {"type": self.FROM_INTENT, "value": value, "intents": intents, "not_intents": not_intents}

    def from_text(self, intents=None, not_intents=None):
        return {"type": self.FROM_TEXT, "intents": intents, "not_intents": not_intents}

    def slot_mappings(self):
        return {slot: self.required_slots[slot].get("mapping", [self.from_entity(slot)])
                for slot in self.required_slots}

    def get_mappings_for_slot(self, slot_name):
        mappings = self.slot_mappings()
        return mappings.get(slot_name)

    def is_desired_intent(self, slot_mapping, tracker):
        intent = tracker.get_latest_intent()
        intents = slot_mapping["intents"]
        not_intents = slot_mapping["not_intents"]
        return (intents is None or intent in intents) and (not_intents is None or intent not in not_intents)

    def is_desired_entity(self, slot_mapping, tracker):
        entity = slot_mapping["entity"]
        return tracker.get_latest_entity_values(entity) is not None

    def _build_utter_slot_func(self, required_slots):
        for slot in required_slots:
            def func(tracker, slot):
                utterance = required_slots[slot].get("utterance")
                retry_utterance = required_slots[slot].get("retry_utterance", utterance)
                fail_utterance = required_slots[slot].get("fail_utterance", "抱歉，这次没帮到你，已退出流程")

                if self._get_slot_trials(tracker.sender_id, slot) == 1:
                    return utterance
                elif self._get_slot_trials(tracker.sender_id, slot) == self.max_slot_trials:
                    return fail_utterance
                else:
                    return retry_utterance

            setattr(self, f"utter_ask_{slot}", func)

    def extract_required_slots(self, tracker):
        slot_dict = {}
        for slot_to_fill, config in self.required_slots.items():
            if self._is_slot_filled(tracker.sender_id, slot_to_fill):
                continue
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
                        value = self._get_cached_slot(tracker.sender_id, slot_to_fill)  # try to find the prefilled value in this form
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

        return self.validate(slot_dict, tracker)

    def _is_slot_filled(self, sender_id, slot_to_fill):
        return self._get_cached_slot(sender_id, slot_to_fill) is not None

    def validate(self, slot_dict, tracker):
        valid_slot_dict = {}
        for slot_name, value in slot_dict.items():
            validate_func_name = f"validate_{slot_name}"
            if hasattr(self, validate_func_name):
                validate_func = getattr(self, validate_func_name)
                value = validate_func(value, tracker)
                if value is not None:
                    valid_slot_dict[slot_name] = value
                    self._set_cached_slot(tracker.sender_id, slot_name, value)
            else:
                valid_slot_dict[slot_name] = value
                self._set_cached_slot(tracker.sender_id, slot_name, value)
        return valid_slot_dict

    def perform(self, tracker, **parameters):
        events = super().perform(tracker, **parameters)
        events.extend(self.cached_events)
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
        if self._is_started(tracker):  # begining of this form
            flag = parameters.get("clear_slot", True)
            if flag:
                self._reset_slot_cache(tracker.sender_id)

    def _perform(self, tracker, **parameters):
        self._check_stage(tracker)
        self._clear_slot_cache_if_required(tracker, **parameters)
        events = self._activate_if_required(tracker)
        slot_dict = self.extract_required_slots(tracker)
        events.extend([SlotSetted(slot, value) for slot, value in slot_dict.items() if tracker.get_slot(slot) != value])
        sender_id = tracker.sender_id
        next_to_fill_slot = None
        for slot_name in self.required_slots:
            if slot_name not in slot_dict and not self._is_slot_filled(sender_id, slot_name):
                next_to_fill_slot = slot_name
                break
        if next_to_fill_slot:
            self._record_slot_trails(sender_id, next_to_fill_slot)
            if hasattr(self, f"utter_ask_{next_to_fill_slot}"):
                utter_func = getattr(self, f"utter_ask_{next_to_fill_slot}")
                utterance = utter_func(tracker, next_to_fill_slot)
                if utterance:
                    self.utter(utterance, sender_id)
            if self._get_slot_trials(sender_id, next_to_fill_slot) == self.max_slot_trials:
                self._terminate(sender_id)
                events.append(Form(None))
        else:
            snapshot = tracker.snapshot()
            snapshot["slots"].update(slot_dict)
            events.extend(self._submit(snapshot))
            events.append(Form(None))  # deactivate
            self._terminate(sender_id)
        return events

    def _get_cached_slot(self, sender_id, slot):
        key = f"{self.name}-{sender_id}"
        return self.slot_cache.get(key, {}).get(slot)

    def _set_cached_slot(self, sender_id, slot, value):
        key = f"{self.name}-{sender_id}"
        self.slot_cache[key][slot] = value

    def _reset_slot_cache(self, sender_id):
        key = f"{self.name}-{sender_id}"
        self.slot_cache[key].clear()

    def _get_slot_trials(self, sender_id, slot):
        key = f"{self.name}-{sender_id}"
        return self.slot_trials.get(key, {}).get(slot, 0)

    def _record_slot_trails(self, sender_id, slot):
        key = f"{self.name}-{sender_id}"
        self.slot_trials[key][slot] += 1

    def _reset_slot_trails(self, sender_id):
        key = f"{self.name}-{sender_id}"
        self.slot_trials[key].clear()

    def _check_stage(self, tracker):
        stage = self.stages.get(self.name, {}).get(tracker.sender_id, None)
        if stage is None:
            self.stages[self.name][tracker.sender_id] = self.STARTED
        elif stage == self.STARTED:
            self.stages[self.name][tracker.sender_id] = self.IN_PROGRESS

    def _terminate(self, sender_id):
        self.terminated = True
        self.stages[self.name][sender_id] = None
        self._reset_slot_trails(sender_id)


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


class OptionSkill(FormSkill):
    number = r"\d+|[一二三四五六七八九十]"
    reference = re.compile(f"((?P<base>上面|下面|倒数|前面|后面|底下)?第)?(?P<index>{number})(个|这个|那个)?")
    top = re.compile("(最)?上面(的|那个|这个|个)")
    middle = re.compile("(最)?中间(的|那个|这个|个)")
    bottom = re.compile("(最)?(下面|底下|后|后面)(一个|的|那个|这个|个)")
    description = re.compile("(?P<term>.+)(这个|那个|的)?")
    digit_mapping = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    base_mapping = {"上面": 1, "下面": -1, "倒数": -1, "前面": 1, "后面": -1, "底下": -1}

    def __init__(self, required_slots):
        super().__init__(required_slots)
        for slot in required_slots:
            if "options" in required_slots[slot]:
                self._build_option_validate_func(slot)
        self.processed_message_ids = defaultdict(set)

    def _build_utter_slot_func(self, required_slots):
        for slot in required_slots:
            def func(tracker, slot):
                utterance = required_slots[slot].get("utterance")
                if "options" in required_slots[slot]:
                    options = required_slots[slot]["options"]
                    retry_utterance = utterance + f"(请输入数字1-{len(options)}进行选择,或输入退出)"
                    for i, option in enumerate(options):
                        utterance += f"\n  {i+1}:" + option["text"]
                        retry_utterance += f"\n  {i+1}:" + option["text"]
                else:
                    retry_utterance = required_slots[slot].get("retry_utterance", utterance)
                fail_utterance = required_slots[slot].get("fail_utterance", "抱歉，这次没帮到你，已退出流程")

                if self._get_slot_trials(tracker.sender_id, slot) == 1:
                    return utterance
                elif self._get_slot_trials(tracker.sender_id, slot) == self.max_slot_trials:
                    return fail_utterance
                else:
                    return retry_utterance

            setattr(self, f"utter_ask_{slot}", func)

    def _build_option_validate_func(self, slot):
        def func(value, tracker):
            not_filled_slots = 0
            for to_fill_slot in self.required_slots:
                if to_fill_slot == slot:
                    break
                if not self._is_slot_filled(tracker.sender_id, to_fill_slot):
                    not_filled_slots += 1

            if not_filled_slots == 0:
                sender_id = tracker.sender_id
                message_id = tracker.latest_message.message_id
                if self._get_slot_trials(sender_id, slot) == 0:
                    self.cached_events.append(SlotSetted("options_slot", self.required_slots[slot]["options"]))
                    return None

                if message_id in self.processed_message_ids.get(sender_id, {}):
                    return None

                options = tracker.get_slot("options_slot")
                index = self._parse_reference(value, options)
                if index is None:
                    index = self._parse_description(value, options)
                if index is not None and -len(options) <= index < len(options):
                    self.processed_message_ids[sender_id].add(message_id)
                    return options[index]
                else:
                    return None
            else:
                return None

        setattr(self, f"validate_{slot}", func)

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
            if index < 1 or index > len(options):
                return None
            if reverse:
                index *= -1
            else:
                index -= 1   # index starts with 0
        return index

    def _parse_description(self, value, options):
        m = self.description.match(value)
        if m:
            matched = 0
            index = -1
            term = m.group("term")
            for i, option in enumerate(options):
                if (not term.isdigit() and term in option["text"]) or term == option["text"]:
                    index = i
                    matched += 1
            if matched == 1:
                return index

        return None
