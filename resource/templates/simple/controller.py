from Broca.central_controller.controller import Controller
from Broca.channel import CollectingOutputChannel
from Broca.message import UserMessage

controller = Controller()
controller.load_engines(".")


def run_cmd():
    channel = CollectingOutputChannel()
    while True:
        msg = input("user:")
        message = UserMessage("", msg, channel=channel)
        controller.handle_message(message)
        for res in channel.messages:
            print(f"bot:{res.text}")
        channel.messages.clear()


if __name__ == "__main__":
    run_cmd()
