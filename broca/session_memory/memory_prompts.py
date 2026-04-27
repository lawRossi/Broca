"""
Session Memory Prompt 模板

"""


def build_extraction_user_prompt(memory_path, current_content) -> str:
    """构建子代理的 user prompt"""
    return """Based on the user conversation above (EXCLUDING this note-taking instruction message as well as system prompt), update the session notes file {memory_path}.
Your ONLY task is to use the edit_file tool to update the notes file, then stop. You can make multiple edits (update every section as needed).  
The content of the file {memory_path} has already been read for you. Here is its current contents:

{current_content}

Critical Rules for Editing:

1. Preserve the exact file structure - do NOT modify or delete section headers or italic description lines
2. Do NOT add new sections or remove existing ones
3. Skip sections with no substantial new insights
4. Write DETAILED, INFO-DENSE content with specific file paths, function names, error messages, etc.
5. Keep each section under ~2000 tokens - condense older info if needed
6. Total file under ~12000 tokens
7. Always update "Current State" to reflect the most recent work
8. You ONLY have access to edit_file tool -

REMEMBER: Make all edits in one step and stop. Do not continue after the edits. 
""".format(memory_path=memory_path, current_content=current_content)
