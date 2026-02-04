from Broca.prompts import main_agent_base, subagent_base


main_agent_config = {
    "llm_config_name": "minimax",
    "system_prompt_template": main_agent_base,
    "subagents": ["requirment analyzer", "frontend developer", "backend developer"],
    "tools": ["create_task", "execute_code", "load_skill"],
    "skills": ["skill-creator"],
    "interactive": True,
    "save_history": True,
    "environment": None,
    "verbose": True
}


sub_agent_config = {
    "llm_config_name": "minimax",
    "system_prompt_template": subagent_base,
    "tools": ["execute_code", "load_skill"],
    "skills": [],
    "interactive": True,
    "save_history": False,
    "environment": None,
    "verbose": True
}
