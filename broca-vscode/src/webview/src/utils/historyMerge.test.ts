/**
 * 回归测试：明细模式下「撤销成功后页面不刷新」。
 *
 * Bug：撤销后 WebView 调用 loadHistory(skip=0) 重载消息。服务端
 * `/session/{id}/messages` 会过滤 `reverted=True`，被撤销的消息不再出现在响应里。
 * 旧实现没有在请求前清空列表，重载时又把「API 未返回的现有消息」当成请求期间新到的
 * live 消息保留（liveExtras），于是被撤销的消息一直留在列表里 —— 撤销成功但页面毫无变化。
 * 简洁模式不受影响（loadTurnHistory(reset=true) 直接清空重建）。
 *
 * 现在的约定（与 Web 端一致）：loadHistory(skip=0) 先清空 messages，
 * 服务端数据是唯一权威 base，只额外保留请求往返期间新到的消息。
 *
 * 用 Node 内置测试运行器执行：
 *   node --test src/webview/src/utils/historyMerge.test.ts
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { applyHistoryReload } from './historyMerge.ts'

interface Msg {
  message_id: string
}

const m = (id: string): Msg => ({ message_id: id })

test('核心回归：请求前列表中的消息（已撤销、服务端不再返回）不得残留', () => {
  // 撤销前列表：m1, m2, m3 → 撤销后服务端只返回 m1。
  // loadHistory(skip=0) 已先清空列表，因此这里传入的 liveMessages 为空。
  const result = applyHistoryReload({
    apiMessages: [m('m1')],
    liveMessages: [],
  })

  assert.deepEqual(
    result.map((x) => x.message_id),
    ['m1']
  )
})

test('请求往返期间新到达的消息仍被保留（不被重载误删）', () => {
  const result = applyHistoryReload({
    apiMessages: [m('m1'), m('m2')],
    liveMessages: [m('m3')],
  })

  assert.deepEqual(
    result.map((x) => x.message_id),
    ['m1', 'm2', 'm3']
  )
})

test('请求期间新到的消息若已被服务端返回，不重复追加', () => {
  const result = applyHistoryReload({
    apiMessages: [m('m1'), m('m2')],
    liveMessages: [m('m2')],
  })

  assert.deepEqual(
    result.map((x) => x.message_id),
    ['m1', 'm2']
  )
})

test('API 消息顺序为权威（升序展示顺序不被 live 消息打乱）', () => {
  const result = applyHistoryReload({
    apiMessages: [m('m1'), m('m2'), m('m3')],
    liveMessages: [m('m4')],
  })

  assert.deepEqual(
    result.map((x) => x.message_id),
    ['m1', 'm2', 'm3', 'm4']
  )
})

test('清空历史（服务端返回空且无 live 消息）后列表为空', () => {
  const result = applyHistoryReload({
    apiMessages: [],
    liveMessages: [],
  })

  assert.deepEqual(result, [])
})
