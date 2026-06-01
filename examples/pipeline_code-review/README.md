# 代码审查流水线 Demo — 完整 Pipeline 特性演示

一个完整的 Pipeline 流水线编排 Demo，演示 Pipeline 的全部编排能力。

## 场景

模拟一个全流程的代码审查流水线：

```
static_analysis ─→ fan-out ─→ fan-in ─→ quality_gate ──passed──→ final_approval
                      │          │            │
                      │          │            └──failed──→ fix_issues ─→ goto static_analysis (循环)
                      │          │
               security_audit  aggregation
               performance_review
```

## 使用的 Pipeline 特性

| 特性　　　　　　　　　　| 步骤　　　　　　| 说明　　　　　　　　　　　　　　　　　　　|
| :------------------------| :----------------| :------------------------------------------|
| **task**　　　　　　　　| Step 1, 4, 5, 6 | 单 Agent 顺序执行任务　　　　　　　　　　 |
| **fan-out**　　　　　　 | Step 2　　　　　| 并行分发到安全审计员 + 性能工程师　　　　 |
| **fan-in** (agent 策略) | Step 3　　　　　| 质量管理员汇聚所有审查结果　　　　　　　　|
| **step name**　　　　　 | 全部步骤　　　　| 命名步骤用于 goto 引用　　　　　　　　　　|
| **on_result goto**　　　| Step 4　　　　　| 质量不达标时跳转到 fix_issues　　　　　　 |
| **on_result goto**　　　| Step 5　　　　　| 修复后跳转回 static_analysis 形成循环　　 |
| **goto_context**　　　　| Step 4, 5　　　 | 跳转时写入 loop_phase、gate_result 到黑板 |
| **max_iterations**　　　| Step 4　　　　　| 最多 3 次修复循环，防无限循环　　　　　　 |
| **accumulated_context** | 全局　　　　　　| 前一步输出自动汇入下一步上下文　　　　　　|

## 执行流程

1. **static_analysis** — 代码审查员静态代码审查
2. **parallel_reviews** — 扇出：安全审计员 + 性能工程师 并行执行
3. **aggregation** — 扇入：质量管理员汇聚所有结果，写入 `quality_score`
4. **quality_gate** — 审批员检查 `quality_score`，写 `gate_passed`
   - `gate_passed=true` → 跳转到 final_approval
   - `gate_passed=false` → 跳转到 fix_issues
5. **fix_issues** — 代码审查员根据反馈修复代码
   - 修复完成后跳转回 static_analysis（重审循环）
6. **final_approval** — 审批员输出最终批准报告

## 使用方法

### 方式一：通过 Web UI

1. 启动 Broca 服务
2. 访问 Web 界面
3. 创建「Agent 编排」类型会话，工作目录指向 `examples/pipeline_code-review`
4. 进入编排管理页面，提交 `crew_configs/crew.yaml`

## 自定义

### 修改审查代码

编辑 `crew.yaml` 中 `blackboard.initial_entries` 下的 `code_to_review` 值。

### 调整审查标准

修改 `quality_gate` 步骤的 `on_result` 条件，或调整 agent 配置中的审查要求。

## 文件结构

```
examples/pipeline_code-review/
├── README.md
└── crew_configs/
    ├── crew.yaml                  # 编排配置（主入口）
    ├── code_reviewer.md           # 代码审查员 Agent 配置
    ├── security_auditor.md        # 安全审计员 Agent 配置
    ├── performance_engineer.md    # 性能工程师 Agent 配置
    ├── quality_manager.md         # 质量管理员 Agent 配置
    └── approver.md                # 审批员 Agent 配置
