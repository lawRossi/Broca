"""
@Author: Rossi
Created At: 2020-12-13
"""
import re
import json
from collections import defaultdict


class NaturalLanguageParser:
    """base class parsers
    """

    def parse(self, message):
        """parse a user message

        Args:
            message (UserMessage): the user message to be parsed
        """
        pass

    @classmethod
    def from_config(cls, config):
        """Create a parser according to a configuration

        Args:
            config (dict): the configuration

        Returns:
            NaturalLangeParser: the parser created
        """ 
        return cls()


class RENaturalLanguageParser(NaturalLanguageParser):
    """Regular expression based nl parser. This parser will judge the intent
    of the user message and extract some specified entities from the message.
    """

    def __init__(self, intent_patterns) -> None:
        super().__init__()
        self.intent_patterns = intent_patterns

    def parse(self, message):
        text = message.text
        for intent, patterns in self.intent_patterns:
            for pattern in patterns:
                m = pattern.match(text)
                if m is not None:
                    intent = {"name": intent["name"], "agent": intent["agent"], "confidence": 1.0}
                    message.set("intent", intent)
                    entities = message.get("entities", defaultdict(list))
                    for k, v in m.groupdict().items():
                        if k[-1].isdigit():
                            k = k[:-1]
                        entities[k].append({"type": k, "value": v, "confidence": 1.0, "start": m.start(), "end": m.end()})
                    message.set("entities", entities)
                    break  # at most one pattern will apply

    @classmethod
    def from_config(cls, config):
        intent_file = config["intent_file"]
        with open(intent_file, encoding="utf-8") as fi:
            json_data = json.load(fi)
        intent_pattens = []
        for item in json_data:
            intent = item["intent"]
            patterns = [re.compile(pattern) for pattern in item["patterns"]]
            intent_pattens.append((intent, patterns))
        return cls(intent_pattens)
