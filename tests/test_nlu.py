from Broca.nlu.parser import RENaturalLanguageParser
from Broca.message import UserMessage


class Base:
    cache = {}


class Sub1(Base):
    def __init__(self) -> None:
        self.cache["a"] = 1

class Sub2(Base):
    def __init__(self) -> None:
        self.cache["b"] = 2

s1 = Sub1()
s2 = Sub2()
print(s1.cache)
print(s2.cache)


if __name__ == "__main__":
    parser = RENaturalLanguageParser.from_config({"intent_file": "tests/data/intent_patterns.json"})
    message1 = UserMessage("sender", "意图一实体")
    message2 = UserMessage("sender", "意图二")

    parser.parse(message1)
    assert "intent" in message1.parsed_data
    intent = message1.get("intent")
    assert intent["name"] == "intent1"
    assert "entities" in message1.parsed_data
    entities = message1.get("entities")
    assert len(entities) == 1
    entity = entities["entity"]
    assert(len(entity)) == 1
    entity = entity[0]
    assert entity["type"] == "entity"
    assert entity["value"] == "实体"

    parser.parse(message2)
    intent = message2.get("intent")
    assert "intent" in message2.parsed_data
    assert intent["name"] == "intent2"
    assert "entities" in message2.parsed_data
    assert len(message2.get("entities")) == 0
