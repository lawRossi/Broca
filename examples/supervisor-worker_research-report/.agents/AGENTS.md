### Blackboard Information (Shared Memory)

The Blackboard is a shared memory space that all agents can read/write.
Here is the current key structure:

- `objective` - The research objective
- `plan_iteration_X` - Supervisor's work plan for iteration X
- `worker_results_iteration_X` - Worker results for iteration X

Tips for using the Blackboard:
1. Use `list_blackboard()` to see all available keys and versions
2. Use `read_blackboard("objective")` to read the research objective
3. Use `blackboard_changes(since_version=X)` to get only new changes since your last check
4. Your final response message will be recorded as your contribution automatically

You DO NOT need to write to the Blackboard yourself - your response here will be captured.
