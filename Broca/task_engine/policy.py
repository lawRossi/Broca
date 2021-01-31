"""
@author: Rossi
@time: 2021-01-27
"""


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

