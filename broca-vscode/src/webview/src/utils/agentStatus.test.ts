/**
 * 回归测试：Agent 状态在周期性刷新时的合并。
 *
 * Bug：「turn 执行中前端偶尔显示空闲，尤其工具执行耗时较久时」。
 *
 * 用 Node 内置测试运行器执行（vscode 包本身没有 vitest 等测试框架）：
 *   node --test src/webview/src/utils/agentStatus.test.ts
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { mergeAgentStatuses } from './agentStatus.ts'

test('首次加载：无历史状态时以 DB 状态为准', () => {
  const result = mergeAgentStatuses([{ agent_id: 'a1', status: 'idle' }], {})
  assert.equal(result.a1, 'idle')
})

test('首次加载：DB running 显示为 running', () => {
  const result = mergeAgentStatuses([{ agent_id: 'a1', status: 'running' }], {})
  assert.equal(result.a1, 'running')
})

test('周期性刷新：DB 滞后为 idle 时不把 running 降级（核心回归）', () => {
  const result = mergeAgentStatuses(
    [{ agent_id: 'a1', status: 'idle' }],
    { a1: 'running' }
  )
  assert.equal(result.a1, 'running')
})

test('周期性刷新：DB running 可把 idle 升级为 running', () => {
  const result = mergeAgentStatuses(
    [{ agent_id: 'a1', status: 'running' }],
    { a1: 'idle' }
  )
  assert.equal(result.a1, 'running')
})

test('周期性刷新：turn_end 后前端 idle 且 DB idle，保持 idle', () => {
  const result = mergeAgentStatuses(
    [{ agent_id: 'a1', status: 'idle' }],
    { a1: 'idle' }
  )
  assert.equal(result.a1, 'idle')
})

test('多 agent：仅对处于 running 的 agent 保留 running', () => {
  const result = mergeAgentStatuses(
    [
      { agent_id: 'a1', status: 'idle' },
      { agent_id: 'a2', status: 'idle' },
    ],
    { a1: 'running', a2: 'idle' }
  )
  assert.equal(result.a1, 'running')
  assert.equal(result.a2, 'idle')
})
