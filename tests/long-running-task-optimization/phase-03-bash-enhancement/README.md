# Phase 3: Bash 工具增强 — Test Mapping
> Plan: plans/long-running-task-optimization-plan.md

## Task 3.1: 增强 bash 工具参数与描述

| AC | Test Function |
|----|---------------|
| 工具描述清晰说明 background 场景 | `test_ac01_description_background_scenario` |
| notify 参数可被 LLM 理解和调用 | `test_ac02_notify_parameter_exists`, `test_ac02_notify_parameter_llm_understandable` |
| 现有参数兼容 | `test_ac03_existing_parameters_compatible` |

## Task 3.2: 实现 & 检测和 notify 传递

| AC | Test Function |
|----|---------------|
| npm run dev & 自动检测 &，转为后台 | `TestAmpersandDetection.*`, `TestAmpersandStrip.*` (共 10 个测试) |
| background=True, notify=True → 收到通知 | `test_ac02_background_notify_true`, `test_ac02_ampersand_notify_true` |
| background=True, notify=False → 不收通知 | `test_ac03_background_notify_false`, `test_ac03_background_notify_default` |
| 无 background → 保持 120s 超时 | `test_ac04_no_background_uses_code_async` |
| 返回 job_id 和文件路径提示 | `test_ac05_run_background_returns_job_id_and_path` |

## Task 3.3: LoopEngine 超时适配

| AC | Test Function |
|----|---------------|
| background=True 时不设外层超时 | `test_ac01_skip_timeout_for_bash_background` |
| 其他工具和其他 bash 调用不受影响 | `test_ac02_dont_skip_for_bash_no_background`, `test_ac02_dont_skip_for_bash_background_false`, `test_ac02_dont_skip_for_other_tools`, `test_ac02_dont_skip_for_empty_arguments`, `test_ac02_dont_skip_for_none_arguments` |

## Phase Integration Tests

| Test File | What It Verifies |
|-----------|------------------|
| `phase-ac-tests/test_phase03_integration.py` | Phase AC 1-5: & 自动转后台、工具描述、notify 参数、非 background 超时、LoopEngine 适配 |
