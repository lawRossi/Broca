import re
import time

from Broca.task_engine.engine import Engine
from Broca.message import UserMessage


def read_scenes(script_file):
    scenes = []
    with open(script_file, encoding="utf-8") as fi:
        lines = fi.readlines()
        scene = []
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                scenes.append(scene)
                scene = []
                i += 1
            elif line.startswith("user:"):
                user_utterance = line[len("user:"):].strip()
                i += 1
                bot_utterances = []
                while i < len(lines):
                    line = lines[i].strip()
                    if line.startswith("bot:"):
                        line = line.replace("\\n", "\n")
                        bot_utterances.append(line[len("bot:"):].strip())
                        i += 1
                    else:
                        break
                scene.append((user_utterance, bot_utterances))
        if scene:
            scenes.append(scene)
    return scenes


if __name__ == "__main__":
    engine = Engine.from_config_file("tests/data/engine_config.json")
    engine.load_agents("tests")
    assert len(engine.agents) == 1
    agent = engine.agents[0]
    engine.collect_intent_patterns()

    # user_msg = UserMessage("", "我要买电影票")
    # responses = engine.handle_message(user_msg)
    # assert len(responses) == 1
    # response = responses[0].text
    # assert response == "你想看哪部电影？\n  1:海王\n  2:魔戒"
    # user_msg = UserMessage("", "第一个")
    # responses = engine.handle_message(user_msg)
    # assert len(responses) == 1
    # response = responses[0].text
    # assert response == "已为你预定海王的票"

    silence_pattern = re.compile(r"silence-(\d+)s")

    scenes = read_scenes("tests/data/dialogues.txt")
    for scene in scenes:
        engine = Engine.from_config_file("tests/data/engine_config.json")
        engine.load_agents("tests")
        engine.collect_intent_patterns()
        for turn in scene:
            match = silence_pattern.match(turn[0])
            if match:
                interval = int(match.group(1))
                time.sleep(interval)
                continue
            user_message = UserMessage("", turn[0])
            messages = engine.handle_message(user_message)

            if turn[1][0] == "null":
                assert messages == []
            else:
                if len(messages) != len(turn[1]):
                    print(turn, [msg.text for msg in messages])
                    raise RuntimeError
                for message, text in zip(messages, turn[1]):
                    if message.text != text:
                        print(text, message.text)
                        raise RuntimeError
