### Blackboard Information (Shared Memory)

The Blackboard is a shared memory space that all agents can read/write.
Here is the current key structure:

- `objective` - The overall assessment objective
- `product_info` - Detailed product information
- `sub_crew_市场调研分析` - Results from the market research broadcast sub-crew
- `sub_crew_发布决策评审` - Results from the launch decision consensus sub-crew

Tips for using the Blackboard:
1. Use `list_blackboard()` to see all available keys and versions
2. Use `read_blackboard("product_info")` to read product details
3. Use `read_blackboard("objective")` to read the assessment objective
4. Use `blackboard_changes(since_version=X)` to get only new changes since your last check
5. Your final response message will be recorded as your contribution automatically

You DO NOT need to write to the Blackboard yourself - your response here will be captured.
