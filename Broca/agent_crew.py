from jinja2 import Template


class AgentCrewConfig:
    def __init__(self):
        self.background = ""
        self.rules = ""
        self.context_template = None


class BlackBoard:
    def __init__(self):
        self.content = ""

    def update(self, new_content):
        self.content = new_content


class AgentCrew:
    def __init__(self, config: AgentCrewConfig, blackboard):
        self.config = config
        self.blackboard = blackboard
        self.crew_leader = None
        self.members:dict = {}

    def add_crew_leader(self, leader):
        self.crew_leader = leader 
        self.add_member(leader)

    def add_member(self, member):
        self.members[member.role] = member

    def _update_context(self, member):
        if hasattr(member, "original_system_prompt"):
            instruction = member.original_system_prompt
        else:
            instruction = member.system_prompt
            member.original_system_prompt = instruction
        new_system_prompt = Template(self.config.context_template).render(
            background=self.config.background,
            rules=self.config.rules,
            members=self._format_members(),
            member_instruction=instruction, 
            blackboard_content=self.blackboard.content
        )
        member.system_prompt = new_system_prompt

    def _format_members(self):
        members_str = ""
        for name, member in self.members.items():
            members_str += f"{member.role}\n"
        return members_str.strip()

    def run_member_step(self, role):
        member = self.members[role]
        return self._run_member_step(member)

    def _run_member_step(self, member):
        self._update_context(member)
        member.reset()
        return member.run_step()

    def run(self):
        need_more_steps = True
        while need_more_steps:
            need_more_steps = self._run_member_step(self.crew_leader)
