from Broca.dialogue_engine.engine import DialogueEngine
from Broca.channel import CollectingOutputChannel
from Broca.message import UserMessage

engine = DialogueEngine()
engine.load_engines(".")
engine.load_dispatching_agent("")


def run_cmd():
    channel = CollectingOutputChannel()
    while True:
        msg = input("user:")
        message = UserMessage("", msg, channel=channel)
        engine.handle_message(message)
        for res in channel.messages:
            if res.text:
                print(f"bot:{res.text}")
            elif res.data:
                print(f"bot:{res.data}")
        channel.messages.clear()


if __name__ == "__main__":
    run_cmd()
