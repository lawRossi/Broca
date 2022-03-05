from Broca.task_engine.engine import Engine
from Broca.channel import CollectingOutputChannel
from Broca.message import UserMessage
from .test_agent import read_scenes


if __name__ == "__main__":
    engine = Engine.from_config_file("tests/data/engine_config.json")
    engine.load_agents("tests")
    assert len(engine.agents) == 1
    agent = engine.agents[0]
    # assert len(agent.skills) == 11
    engine.collect_intent_patterns()

    user_msg = UserMessage("", "我要买电影票")
    responses = engine.handle_message(user_msg)
    print([response.text for response in responses])
    user_msg = UserMessage("", "第一个")
    responses = engine.handle_message(user_msg)
    print([response.text for response in responses])

    scenes = read_scenes("tests/data/dialogues.txt")
    for scene in scenes:
        engine = Engine.from_config_file("tests/data/engine_config.json")
        engine.load_agents("tests")
        engine.collect_intent_patterns()
        for turn in scene:
            user_message = UserMessage("", turn[0])
            messages = engine.handle_message(user_message)
            
            if turn[1][0] == "null":
                assert messages == []
            else:
                assert len(messages) == len(turn[1])
                for message, text in zip(messages, turn[1]):
                    if message.text != text:
                        print(text, message.text)
                    assert message.text == text
