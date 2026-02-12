import os


def load_prompt(prompt_path):
    with open(prompt_path, encoding="utf-8") as f:
        prompt = f.read().strip()
    return prompt


main_agent_base = load_prompt(os.path.join(os.path.dirname(__file__), "main-agent-base.txt"))
subagent_base = load_prompt(os.path.join(os.path.dirname(__file__), "subagent-base.txt"))
agent_crew_base = load_prompt(os.path.join(os.path.dirname(__file__), "agent-crew-base.txt"))
agent_crew_member_base = load_prompt(os.path.join(os.path.dirname(__file__), "agent-crew-member-base.txt"))