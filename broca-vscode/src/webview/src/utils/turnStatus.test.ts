/**
 * 回归测试：turn 结束后迟到消息不得把卡片状态降级回「进行中」。
 *
 * Bug 1：「简洁模式下，没有调用工具的 turn 结束后，卡片状态偶尔（实际稳定）
 * 不变成已完成」。根因是后端残余流式 chunk 的延迟 flush 晚于 turn_end 广播，
 * 前端收到迟到的 agent_response 后把 status 从 completed 改回 thinking。
 *
 * 设计约束：`error` 不是终态 —— LLM 重试期间后端会广播 error 通知，重试成功后
 * turn 继续跑。因此守卫只能按 `isActive` 判断，绝不能按 `status` 判断。
 * （error 消息现在完全不改卡片状态，卡片终态只由 turn_end 决定。）
 *
 * 用 Node 内置测试运行器执行：
 *   node --test src/webview/src/utils/turnStatus.test.ts
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { canUpdateTurnRunningStatus } from './turnStatus.ts'

test('进行中的 turn：允许被实时消息改状态', () => {
  assert.equal(canUpdateTurnRunningStatus({ isActive: true, status: 'thinking' }), true)
  assert.equal(canUpdateTurnRunningStatus({ isActive: true, status: 'calling_tool' }), true)
})

test('已完成 turn：迟到的 agent_response/tool_call 不得降级（核心回归 Bug 1）', () => {
  assert.equal(canUpdateTurnRunningStatus({ isActive: false, status: 'completed' }), false)
})

test('已中断（turn_end 报告 aborted/error）的 turn：同样保持终态', () => {
  assert.equal(canUpdateTurnRunningStatus({ isActive: false, status: 'error' }), false)
})

test('重试中的 turn：不能按 status 冻结，必须允许回到进行中（核心回归 Bug 2）', () => {
  // 防御性用例：即使某个 turn 的 status 是 'error'，只要还没收到 turn_end
  // （isActive 仍为 true），就必须允许重试成功后的 agent_response 把状态改回进行中。
  assert.equal(canUpdateTurnRunningStatus({ isActive: true, status: 'error' }), true)
})
