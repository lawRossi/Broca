"""
@Author: Rossi
Created At: 2021-01-30
"""

class Slot:
    def __init__(self, name, from_entity=None):
        self.name = name
        self.from_entity = from_entity
        self.value = None
        self.featurized = False
        self.turn_no = None

    def featurize(self):
        return {self.name: self.value}

    @classmethod
    def from_config(cls, config):
        name = config["name"]
        from_entity = config.get("from_entity")
        return cls(name, from_entity)
