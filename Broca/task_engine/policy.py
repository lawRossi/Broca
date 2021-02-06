"""
@author: Rossi
@time: 2021-01-27
"""
from Broca.utils import find_class


class Policy:
    """
    """
    def predict_skill_probabilities(self, tracker):
        pass

    def parse_script(self, script):
        pass

    def pick_skill(self, tracker):
        skill_probabilities = self.predict_skill_probabilities(tracker)
        if skill_probabilities:
            most_likely_skill = max(skill_probabilities.items(), key=lambda x:x[1])[0]
            return most_likely_skill
        else:
            return None

    @classmethod
    def from_config(cls, config):
        return cls()


class MappingPolicy(Policy):
    def __init__(self) -> None:
        super().__init__()
        self.mapping = None

    def predict_skill_probabilities(self, tracker):
        state = tracker.current_state()
        intent = state["intent"]
        skill = self.mapping.get(intent)
        probabilities = {}
        if skill:
            probabilities[skill] = 1.0
        return probabilities

    def parse_script(self, script):
        mapping = script.get("mappings")
        self.mapping = mapping


class FormPolicy(Policy):
    def predict_skill_probabilities(self, tracker):
        if tracker.active_form is not None:
            return {tracker.active_form: 1.0}
        return {}


class EnsemblePolicy(Policy):
    def __init__(self, policies):
        super().__init__()
        self.policies = policies

    def predict_skill_probabilities(self, tracker):
        probabilities = {}
        for policy in self.policies:
            probabilities.update(policy.predict_skill_probabilities(tracker))
        print(probabilities)
        return probabilities

    @classmethod
    def from_config(cls, config):
        policies = []
        for policy_config in config["policies"]:
            policy_cls = find_class(policy_config["class"])
            policies.append(policy_cls.from_config(policy_config))
        return cls(policies)

    def parse_script(self, script):
        for policy in self.policies:
            policy.parse_script(script)
