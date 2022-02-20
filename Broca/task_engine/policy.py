"""
@author: Rossi
@time: 2021-01-27
"""

from collections import OrderedDict
import json
import re

from Broca.task_engine.event import BotUttered, Event, Form, SkillEnded
from Broca.task_engine.tracker import DialogueStateTracker
from Broca.utils import find_class


class Policy:
    """
    """
    def predict_skill_probabilities(self, tracker):
        pass

    def parse_script(self, script, agent):
        pass

    def pick_skill(self, tracker):
        probabilities = self.predict_skill_probabilities(tracker)
        if probabilities:
            return self._get_most_likely_skill(probabilities)
        else:
            return None

    def _get_most_likely_skill(self, probabilities):
        most_likely_skill = max(probabilities.keys(), key=lambda k: probabilities[k])
        return most_likely_skill

    @classmethod
    def from_config(cls, config):
        return cls()


class MappingPolicy(Policy):
    def __init__(self) -> None:
        super().__init__()
        self.name = "mapping_policy"
        self.mappings = None

    def predict_skill_probabilities(self, tracker):
        probabilities = {}
        state = tracker.current_state()
        intent = state["intent"]
        skill = self.mappings.get(intent)
        if state["latest_skill"] == "listen" and skill is not None:
            probabilities[skill] = 1.0
        return probabilities

    def parse_script(self, script, agent):
        mappings = script.get("mappings")
        self.mappings = mappings


class FormPolicy(Policy):
    def __init__(self) -> None:
        super().__init__()
        self.name = "form_policy"

    def predict_skill_probabilities(self, tracker):
        if tracker.latest_skill == "listen" and tracker.active_form is not None:
            return {tracker.active_form: 1.0}
        return {}


class MemoryPolicy(Policy):
    def __init__(self, max_memory_depth=5):
        super().__init__()
        self.name = "memory_policy"
        self.memories = {}
        self.max_memory_depth = max_memory_depth
        self.max_scene_turns = 0
        self.event_pattern = re.compile("^(?P<event>([a-zA-Z\d_]+?))(?P<parameters>\{.+\}$)")
        self.skill_parameters = re.compile(":\{.+\}")

    def predict_skill_probabilities(self, tracker):
        skill = self.search_memory(tracker)
        probabilities = {}
        if skill:
            probabilities[skill] = 1.0
        else:
            for n in range(self.max_scene_turns, -1, -1):
                new_tracker = tracker.init_copy()
                events = tracker.get_last_n_turns_events(n)
                for event in events:
                    if not isinstance(event, BotUttered):
                        event = event.copy()
                    new_tracker.update(event)
                skill = self.search_memory(new_tracker)
                if skill:
                    probabilities[skill] = 1.0
                    break
        return probabilities

    def search_memory(self, tracker):
        states = tracker.get_past_states()
        memeory_key = json.dumps(states[-self.max_memory_depth:])
        skill = self.memories.get(memeory_key)
        return skill

    def parse_script(self, script, agent):
        scenes = script["scenes"]
        for scene in scenes:
            self._parse_scene(scene, agent)

    def _parse_scene(self, scene, agent):
        tracker = DialogueStateTracker(None, agent)
        turns = 0
        active_form = None
        for line in scene.strip().split("\n"):
            line = line.strip()
            if line == "":
                continue
            if line.startswith("user:"):
                parameter_string = line[len("user:"):].strip()
                user_uttered = Event.from_parameter_string("user_uttered", parameter_string)
                tracker.update(user_uttered)
                agent.listen(tracker)
                turns += 1
            elif line.startswith("bot:"):
                line = line[len("bot:"):].strip()
                match = self.event_pattern.match(line)
                if match:
                    event_name = match.group("event")
                    parameter_string = match.group("parameters")
                    event = Event.from_parameter_string(event_name, parameter_string)
                    if event_name == "form":
                        parameters = json.loads(parameter_string)
                        skill_name = parameters["name"]
                        if skill_name is not None: 
                            active_form = skill_name
                            states = tracker.get_past_states()
                            memory_key = json.dumps(states[-self.max_memory_depth:])
                            self.memories[memory_key] = skill_name
                            tracker.update(event)
                            tracker.update(SkillEnded(skill_name))
                        else:
                            tracker.update(event)
                            tracker.update(SkillEnded(active_form))
                    else:
                        tracker.update(event)
                else:
                    skill_name = line
                    states = tracker.get_past_states()
                    memory_key = json.dumps(states[-self.max_memory_depth:])
                    self.memories[memory_key] = skill_name
                    if skill_name == "deactivate_form":
                        tracker.update(Form(None))
                    raw_skill_name = self.skill_parameters.sub("", skill_name)
                    tracker.update(SkillEnded(raw_skill_name))
        self.max_scene_turns = max(self.max_scene_turns, turns)


class EnsemblePolicy(Policy):
    def __init__(self, policies):
        super().__init__()
        self.policies = policies
    
    def pick_skill(self, tracker):
        policy_probabilities = self.predict_skill_probabilities(tracker)
        if policy_probabilities:
            for policy, probabilities in policy_probabilities.items():
                if policy == "form_policy":
                    for _, probas in policy_probabilities.items():
                        most_likeley_skill = self._get_most_likely_skill(probas)
                        if most_likeley_skill == "deactivate_form":
                            return most_likeley_skill
                return self._get_most_likely_skill(probabilities)
        return None

    def predict_skill_probabilities(self, tracker):
        policy_probabilities = OrderedDict()
        for policy in self.policies:
            probabilities = policy.predict_skill_probabilities(tracker)
            if probabilities:
                policy_probabilities[policy.name] = probabilities
        return policy_probabilities

    @classmethod
    def from_config(cls, config):
        policies = []
        for policy_config in config["policies"]:
            policy_cls = find_class(policy_config["class"])
            policies.append(policy_cls.from_config(policy_config))
        return cls(policies)

    def parse_script(self, script, agent):
        for policy in self.policies:
            policy.parse_script(script, agent)
