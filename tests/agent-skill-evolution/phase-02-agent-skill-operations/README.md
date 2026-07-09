# Phase 2: Agent Skill Operations — Test Mapping
> Plan: plans/agent-skill-evolution-plan.md

## Task 2.1: SkillManage Tool

| AC | Test Function |
|----|---------------|
| 子 Agent 可调用创建 Skill | `test_ac01_create_skill`, `test_ac01_create_duplicate_fails` |
| 名称清洗、来源标记正确 | `test_ac02_name_cleaned_to_slug`, `test_ac02_source_marked_agent` |
| 路径穿越防护有效 | `test_ac03_path_traversal_write_file`, `test_ac03_path_traversal_remove_file` |
| patch/delete/write_file 正常 | `test_ac04_patch_skill`, `test_ac04_delete_archives_skill`, `test_ac04_write_file_in_skill_dir`, `test_ac04_remove_file_in_skill_dir` |

## Task 2.2: run_skill_sub_agent() + /skill-create

| AC | Test Function |
|----|---------------|
| `run_skill_sub_agent()` 正确创建子 Agent | `test_ac01_run_skill_sub_agent_is_async_function`, `test_ac01_run_skill_sub_agent_signature`, `test_ac01_references_extraction_subagent_pattern` |
| `/skill-create my-skill` 通过子 Agent 创建 | `test_ac02_skill_create_command_registered`, `test_ac02_skill_create_command_md`, `test_ac02_skill_create_prompt_template` |
| 工具限制生效 | `test_ac03_allowed_tools_defined`, `test_ac03_sub_agent_receives_allowed_tools` |
| 超时控制 (120s) | `test_ac04_timeout_parameter`, `test_ac04_timeout_handling_in_source` |

## Task 2.3: /skill-suggest

| AC | Test Function |
|----|---------------|
| `/skill-suggest` 分析所有 Skill 输出文档到 `plans/` | `test_ac01_skill_suggest_command_registered`, `test_ac01_skill_suggest_command_md`, `test_ac01_no_arg_analyzes_all_skills` |
| `/skill-suggest my-skill` 只分析指定 Skill | `test_ac02_skill_suggest_args_parsed` |
| 文档包含改进理由、方案、预期效果 | `test_ac03_suggest_prompt_template_has_required_sections`, `test_ac03_output_path_is_in_plans_dir` |
| 子 Agent 不调用 skill_manage 修改 Skill | `test_ac04_allowed_tools_no_skill_manage`, `test_ac04_allowed_tools_only_read_and_write_file`, `test_ac04_no_modify_tools` |

## Phase Integration Tests

| Test File | What It Verifies |
|-----------|------------------|
| `phase-ac-tests/test_phase_integration.py` | Phase AC: SkillManage create/patch/delete 生命周期, 名称清洗+路径穿越, skill-create/skill-suggest 命令结构 |
