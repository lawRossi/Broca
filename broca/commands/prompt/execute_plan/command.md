---
name: execute_plan
description: execute a plan with builtin skills.
type: prompt
use_sub_agent: false
argument_hint: "<你的计划文件>"
---
# 执行计划

## 任务

你的任务是执行用户指定的计划，计划文件是：{{ args }}。

## 任务步骤

### 1. 深入理解与思考

仔细阅读计划文件，充分理解计划内容

### 2. 规划任务

使用plan-with-tasks技能，将计划转换成任务，要写清楚任务的通过条件。

### 3. 完成任务

使用execute—tasks技能，按正确顺序一个个完成任务。

### 4. 向用户报告

执行完成后，向用户总结：
1. **执行概览**：简要说明执行是否达到预期，执行了哪些关键步骤。
2. **关键核查点**：说明用户可以重点核查哪些地方检验你的执行效果。
