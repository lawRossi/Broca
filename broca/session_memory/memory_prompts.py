"""
Session Memory Prompt 模板

"""

# 默认模板（启动时写入文件）
DEFAULT_MEMORY_TEMPLATE = """# Session Title
_A short and distinctive 5-10 word descriptive title for the session._ (DO NOT DELETE THIS LINE)

# Current State
_What is actively being worked on right now? Pending tasks not yet completed._ (DO NOT DELETE THIS LINE)

# Task Specification
_What did the user ask to do? Design decisions and context._ (DO NOT DELETE THIS LINE)

# Files and Functions
_Important files and their purposes._ (DO NOT DELETE THIS LINE)

# Workflow
_Commands and their execution order._ (DO NOT DELETE THIS LINE)

# Errors & Corrections
_Errors encountered and how they were fixed, what did the user correct/feedback?._ (DO NOT DELETE THIS LINE)

# Project Documentation
_Important project components/modules and their purposes._ (DO NOT DELETE THIS LINE)

# Learnings
_What has worked well? What has not?_ (DO NOT DELETE THIS LINE)

# Key Results
_Specific outputs requested by the user._ (DO NOT DELETE THIS LINE)

# Worklog
_Step by step actions taken. Very terse summary for each step_ (DO NOT DELETE THIS LINE)
"""


def build_extraction_user_prompt(memory_path, current_content) -> str:
    """构建子代理的 user prompt"""
    return """Based on the user conversation above (EXCLUDING this note-taking instruction message as well as system prompt), update the session notes file {memory_path}.
Your ONLY task is to use the edit_file tool to update the notes file, then stop. You can make multiple edits (update every section as needed).  
The content of the file {memory_path} has already been read for you. Here is its current contents:

{current_content}

Critical Rules for Editing:

1. Preserve the exact file structure - *MUST NOT* modify or delete section headers or italic description lines
2. Do NOT add new sections or remove existing ones
3. Skip sections with no substantial new insights
4. Write DETAILED, INFO-DENSE content with specific file paths, function names, error messages, etc.
5. Keep each section under ~2000 tokens - condense older info if needed
6. Total file under ~12000 tokens
7. Always update "Current State" to reflect the most recent work
8. You ONLY have access to edit_file tool

REMEMBER: Make all edits in one step and stop. Do not continue after the edits. 
""".format(memory_path=memory_path, current_content=current_content)
