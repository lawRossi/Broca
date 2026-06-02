### Blackboard Information (Shared Memory)

The Blackboard is a shared memory space that all agents can read/write.
Here is the current key structure:

- `topic` - The debate topic
- `debate_rules` - The debate rules
- `discussion_history` - Full history of all debate rounds
- `round_X_name` - Individual round entries for each agent
- `scores` - Judge's scores (written by 评委)
- `winner` - Winner of the debate (written by 评委)
- `judge_comment` - Judge's comments (written by 评委)

### Debate Flow

Tips for using the Blackboard:
1. Use `list_blackboard()` to see all available keys and versions
2. Use `read_blackboard("topic")` to read the debate topic
3. Use `read_blackboard("discussion_history")` to read the full debate history
4. Use `blackboard_changes(since_version=X)` to get only new changes since your last check
5. Your final response message will be recorded as your round contribution automatically

评委（reviewer）请使用 write_blackboard 工具写入 scores、winner、judge_comment。
