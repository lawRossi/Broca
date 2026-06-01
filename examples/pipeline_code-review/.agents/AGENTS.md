### Blackboard Information (Shared Memory)

The Blackboard is a shared memory space that all agents can read/write.
Here is the current key structure:

- `code_to_review` - The code content to be reviewed
- `quality_score` - Current quality score (0-10), updated by 质量管理员
- `gate_passed` - Quality gate result (true/false), updated by 审批员
- `loop_phase` - Current loop phase (start/passed/rework), updated by goto_context
- `fix_feedback` - Fix feedback from 审批员 when quality gate fails

Tips for using the Blackboard:
1. Use `list_blackboard()` to see all available keys and versions
2. Use `read_blackboard("code_to_review")` to read the code to review
3. Use `write_blackboard(key, value)` to write your results
4. Use `blackboard_changes(since_version=X)` to get only new changes since your last check
5. Your final response message will be recorded as your step output automatically
