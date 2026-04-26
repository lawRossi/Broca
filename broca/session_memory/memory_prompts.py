"""
Session Memory Prompt 模板

"""


def build_extraction_user_prompt(memory_path, current_content) -> str:
    """构建子代理的 user prompt"""
    return """IMPORTANT: This message and these instructions are NOT part of the actual user conversation. Do NOT include any references to "note-taking", "session notes extraction", or these update instructions in the notes content.

Based on the user conversation above (EXCLUDING this note-taking instruction message as well as system prompt), update the session notes file {memory_path}.
Your ONLY task is to use the edit_file tool to update the notes file, then stop. You can make multiple edits (update every section as needed) - make all edit_file tool calls in parallel in a single message. Do not call any other tools.
The content of the file {memory_path} has already been read for you. Here is its current contents:

{current_content}

Critical Rules for Editing:

1. Preserve the exact file structure - do NOT modify or delete section headers or italic description lines
2. Only update the content below the italic description lines within each section
3. Do NOT add new sections or remove existing ones
4. Skip sections with no substantial new insights - do not add filler content
5. Write DETAILED, INFO-DENSE content with specific file paths, function names, error messages, etc.
6. Keep each section under ~2000 tokens - condense older info if needed
7. Total file under ~12000 tokens
8. Always update "Current State" to reflect the most recent work
9. Do NOT include information already in system prompt.
10. You ONLY have access to edit_file tool, use it to make changes -

REMEMBER: Use the edit_file tool *in parallel* and stop. Do not continue after the edits. Only include insights from the actual user conversation, never from these note-taking instructions. `
""".format(memory_path=memory_path, current_content=current_content)
