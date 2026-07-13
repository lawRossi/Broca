---
name: persistent-memory-extraction
version: "1.0.0"
description: "Analyze conversation and update persistent memory. Always use this skill when managing memory."
---

# Persistent Memory Extraction

Analyze the conversation above and update the persistent memory system.

## Available Tools

- Read-only tools: read_file, glob, grep, list_dir, tree_dir
- Write tools: edit_file, write_file (only for paths inside the memory directory)
- All other tools are DENIED.
- Efficient strategy: turn 1 — read all files you might update in parallel; turn 2 — write/edit all files in parallel.

## Memory Types

There are 4 discrete types of memory. Use them strictly:

### user
- **What to store**: The user's role, goals, responsibilities, knowledge, working habits, preferences
- **When to save**: When you learn any detail about the user's personal characteristics
- **How to use**: To tailor future behavior to the user's preferences

### feedback
- **What to store**: Guidance the user has given about how to approach work — both what to avoid and what to keep doing
- **When to save**: When the user corrects your approach OR confirms a non-obvious approach worked
- **Body structure**: Rule itself, then **Why:** (reason), then **How to apply:** (when this kicks in)

### project
- **What to store**: Information about ongoing work, goals, initiatives, bugs, or incidents NOT derivable from code or git history
- **When to save**: When you learn who is doing what, why, or by when
- **IMPORTANT**: Always convert relative dates to absolute dates (e.g., 'next Thursday' → '2026-03-12')
- **Body structure**: Fact/decision, then **Why:**, then **How to apply:**

### reference
- **What to store**: Pointers to where information lives in external systems
- **When to save**: When you learn about external resources and their purpose
- **How to use**: When the user references an external system

## What NOT to Save

These exclusions apply even when the user explicitly asks you to save.
If they ask you to save PR lists or activity summaries, what's worth saving
is what was *surprising* or *non-obvious*:

- Code patterns, conventions, architecture, file paths, project structure (derivable from project state)
- Git history, recent changes, who-changed-what (`git log`/`git blame` are authoritative)
- Debugging solutions or fix recipes (the fix is in the code)
- Anything already documented in project docs
- Ephemeral task details: in-progress work, temporary state, current conversation context
- Raw data dumps or verbose output

## How to Save Memories

Saving a memory is a two-step process:

**Step 1** — Write the memory to its own .md file using this frontmatter format:
```
---
name: descriptive_name
description: One-sentence summary
type: user | feedback | project | reference
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

<memory content here>
```

**Step 2** — Update `MEMORY.md` index:
Format: `- [Title](filename.md) — one-line hook (YYYY-MM-DD)`
- Each entry: one line, under ~150 characters
- Do NOT write memory content directly into MEMORY.md — it's an index only
- MEMORY.md is always loaded in context, so keep it concise
- The date in the index line is the 'updated' date from the frontmatter

## Critical Rules for File Management

### 1. Organize by Topic — Do NOT Create Scattered Files

- **Group related memories into the same file**. If new information fits an existing memory file, update that file instead of creating a new one.
- For example: instead of creating `user-prefers-dark-theme.md`, `user-likes-vim.md`, `user-works-at-night.md`, combine them into a single `user-preferences.md` file.
- A good heuristic: one file per **subject area** (e.g., `user-preferences.md`, `project-goals.md`, `coding-style-feedback.md`), not one file per individual fact.
- Before creating a new memory file, **scan existing files** to check if there's already one covering the same topic.

### 2. NEVER Overwrite Existing Files — Use edit_file

- **Never use `write_file` on an existing file**. Using `write_file` on an existing path destroys the current content.
- **Always use `edit_file`** to update existing memory files — it surgically replaces the specific section that needs updating.
- Workflow for updating an existing memory:
  1. `read_file` the existing memory file to see current content
  2. Use `edit_file` to replace the relevant section (update the `updated` date in frontmatter, add/modify content)
  3. Use `edit_file` on `MEMORY.md` to update the index entry's date if needed
- Only use `write_file` when creating a **brand new** memory file that does not exist yet.

### 3. Keep Files Focused and Coherent

- Don't stuff unrelated topics into the same file — that defeats the purpose of organization.
- If a file grows too large (more than ~50 lines of content), consider whether it should be split into subtopics.

## Constraints

- You ONLY have data from the recent messages above.
- If nothing worth saving was said, do nothing and stop.
- Make all edits in parallel where possible, then stop.
- Do not continue after the edits.
