# broca-web LLM 配置管理功能 — Phase 1: 后端 LLM 配置读写接口 — Execution Report

## Overview

| Item | Content |
|------|---------|
| Plan File | plans/llm-config-management-plan.md |
| Phase | Phase 1: 后端 LLM 配置读写接口 |
| Status | ✅ Pass |

## Plan Anchor Confirmation

- [x] 执行前重读计划 Phase 1 章节
- [x] 确认每个任务的验收标准（Task 1.1 四条 AC、Task 1.2 两条 AC）

## Task Completion

| Task | Status | Plan ACs | Actual Result | Deviation |
|:----:|:------:|----------|---------------|-----------|
| Task 1.1: 新增 GET/PUT /api/config/llm 接口 | ✅ | ① GET 返回 code=200 且 data 与文件一致 | 冒烟测试验证：GET 200，data 与文件内容一致 | 无 |
| | | ② PUT 写入 4 空格缩进 JSON 且生成 .bak 旧配置备份 | 真实文件验证：`'\n    "p"'` 缩进存在；.bak 内容为旧 api_key | 无 |
| | | ③ 缺 models 返回 400 且原文件未修改 | 400 + detail "Provider 'p' requires an object 'models'"；文件字节级未变 | 无 |
| | | ④ ruff/mypy 不报新错误 | ruff: All checks passed；mypy: 2 个新文件 0 错误（3 个错误均为既存 auth_service.py，与本次无关） | 无 |
| Task 1.2: 后端集成测试 | ✅ | ① 新增用例全部通过且既有用例无回归 | test_api_config.py 11/11 通过（新增 6 个）；全量回归 196 passed，唯一失败 test_api_files::test_list_files_specific_dir 经 git stash 验证为**既存失败** | 无 |
| | | ② 备份行为有真实文件级验证 | test_put_creates_backup 使用 tmp_path 真实文件 + monkeypatch，断言 .bak 存在且内容为旧配置 | 无 |

## Deviations

1. **测试环境备注（非代码偏差）**：`~/.broca/venv` 的 site-packages 通过路径配置指向已部署副本 `~/.broca/web/backend`，直接运行 pytest 时 `app` 解析到旧副本导致新路由 404。运行测试需 `PYTHONPATH=/Users/luoweiang/code/Broca/broca-web/backend`。已在任务报告中记录，未修改任何环境配置。
2. **测试预期修正**：`test_put_llm_config_invalid_not_object` 传 list 时 pydantic 请求模型在 422 层即拒绝（到不了业务 400 校验），测试断言从 400 调整为 422，符合 FastAPI 惯例，计划 AC「非法配置返回 400」由缺 models 场景覆盖。
3. **审查报告遗留项落实**：异常处理采用「先 `except HTTPException: raise` 透传再转 500」；新增模型交互采用 el-dialog（Phase 2 落实）。

## Quality Checklist

- [x] 所有 Phase 级 AC 满足（含「现有 providers/models 接口行为不变」——既有 5 个用例原样通过，且未改动其代码路径）
- [x] 所有 Task 级 AC 满足
- [x] 无遗漏任务（对照计划：Task 1.1、1.2 均完成）
- [x] 无额外功能（未做连通性测试、未做热重载）
- [x] 关键行为已手动验证（真实文件冒烟测试 4 项）
- [x] 代码遵循项目规范（ApiResponse 统一响应、loguru 日志、ruff 通过）
- [x] 与既有工作兼容（schemas.py 仅追加模型；config.py 仅追加函数与路由）

## Test Evidence

```
tests/integration/test_api_config.py  11 passed
  TestLLMProvidersAPI  3 passed（既有，无回归）
  TestLLMModelsAPI     2 passed（既有，无回归）
  TestLLMConfigAPI     6 passed（新增）
    test_get_llm_config_success / test_get_llm_config_no_file
    test_put_llm_config_success / test_put_llm_config_invalid_missing_models
    test_put_llm_config_invalid_not_object / test_put_creates_backup

全量回归: 196 passed, 1 failed（既存失败，与本功能无关）
ruff: app/api/config.py + app/schemas/schemas.py + test_api_config.py 新增代码 0 错误
mypy: 2 个改动文件 0 错误
```
