from Broca.task_engine.engine import Engine
from Broca.channel import CollectingOutputChannel
from Broca.message import UserMessage


engine = Engine.from_config_file("engine_config.json")
engine.load_agents(".")
engine.collect_intent_patterns()


def run_cmd():
    channel = CollectingOutputChannel()
    while True:
        msg = input("user:")
        message = UserMessage("", msg, channel=channel)
        engine.handle_message(message)
        for res in channel.messages:
            print(f"bot:{res.text}")
        channel.messages.clear()


if __name__ == "__main__":
    run_cmd()
