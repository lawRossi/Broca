from Broca.task_engine.agent import Agent
from Broca.message import UserMessage
from Broca.channel import CollectingOutputChannel
from .test_skill import GreetSkill, GreetFormSkill


if __name__ == "__main__":
    # channel = CollectingOutputChannel()
    # message = UserMessage("sender", "嘿,我是罗西", channel)
    # agent = Agent.from_config("tests/data/agent_config.json")
    # agent.add_skill(GreetSkill)
    # agent.handle_message(message)
    # assert len(channel.messages) == 1
    # bot_message = channel.messages[0]
    # print(bot_message.to_dict())
    # tracker = agent.tracker_store.get_tracker(message.sender_id)
    # assert len(tracker.get_past_states()) == 2
    # print(tracker.get_past_states())

    channel = CollectingOutputChannel()
    message = UserMessage("sender", "嘿,我是罗西", channel)
    agent = Agent.from_config("tests/data/agent_config.json")
    agent.add_skill(GreetFormSkill)
    agent.handle_message(message)
    print(message.parsed_data)
    assert len(channel.messages) == 1
    bot_message = channel.messages[0]
    print(bot_message.to_dict())
    tracker = agent.tracker_store.get_tracker(message.sender_id)
    assert len(tracker.get_past_states()) == 1
    print(tracker.get_past_states())

    message = UserMessage("sender", "我28岁了", channel)
    agent.handle_message(message)
    print(message.parsed_data)
    assert len(channel.messages) == 2
    bot_message = channel.messages[1]
    print(bot_message.to_dict())
    tracker = agent.tracker_store.get_tracker(message.sender_id)
    assert len(tracker.get_past_states()) == 2
    print(tracker.get_past_states())
