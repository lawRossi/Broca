/**
 * 回归测试：mid-turn 注入的用户消息必须出现在 turn card 的 userMessages 聚合里。
 *
 * Bug：non-blocking 模式下用户在 agent 执行途中继续输入，engine 会在 step 之间
 * 把新消息以相同 turn_id 广播给前端。Web 端逐条追加到 turn.userMessages 并堆叠
 * 展示；VS Code 端原来用 `if (!turn.userMessage)` 只保留第一条，导致 mid-turn
 * 消息在 turn card 里完全看不到（历史回填的 userMessages 也被 card 忽略）。
 *
 * 用 Node 内置测试运行器执行：
 *   node --test src/webview/src/utils/turnUserMessages.test.ts
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  accumulateUserMessage,
  extractUserMessageText,
  getDisplayUserMessages,
  type UserMessagesTurn,
} from './turnUserMessages.ts'

function makeTurn(): UserMessagesTurn {
  return { userMessage: null, userMessages: [], userFiles: null }
}

test('首条 user_message：写入 userMessages 并同步 userMessage（向后兼容）', () => {
  const turn = makeTurn()
  const seen = new Set<string>()

  assert.equal(accumulateUserMessage(turn, 'm1', { raw_input: 'Hello' }, seen), true)

  assert.deepEqual(turn.userMessages, ['Hello'])
  assert.equal(turn.userMessage, 'Hello')
})

test('mid-turn 注入的第二/三条消息必须按顺序追加（核心回归）', () => {
  const turn = makeTurn()
  const seen = new Set<string>()

  accumulateUserMessage(turn, 'm1', { raw_input: '第一条' }, seen)
  accumulateUserMessage(turn, 'm2', { raw_input: 'mid-turn 补充' }, seen)
  accumulateUserMessage(turn, 'm3', { raw_input: '再补充一条' }, seen)

  assert.deepEqual(turn.userMessages, ['第一条', 'mid-turn 补充', '再补充一条'])
  // userMessage 仍是第一条
  assert.equal(turn.userMessage, '第一条')
  // 展示层拿到全部三条
  assert.deepEqual(getDisplayUserMessages(turn), ['第一条', 'mid-turn 补充', '再补充一条'])
})

test('同一 message_id 的重复广播只追加一次（去重）', () => {
  const turn = makeTurn()
  const seen = new Set<string>()

  assert.equal(accumulateUserMessage(turn, 'm1', { raw_input: 'Hello' }, seen), true)
  assert.equal(accumulateUserMessage(turn, 'm1', { raw_input: 'Hello' }, seen), false)

  assert.deepEqual(turn.userMessages, ['Hello'])
})

test('tool_injected 的内部消息被过滤，不进入 TurnCard', () => {
  const turn = makeTurn()
  const seen = new Set<string>()

  const appended = accumulateUserMessage(turn, 'm1', { raw_input: '[image]', tool_injected: true }, seen)

  assert.equal(appended, false)
  assert.deepEqual(turn.userMessages, [])
  assert.equal(turn.userMessage, null)
  // 被过滤的消息也不应占用 seenIds（后续同 id 非注入消息仍可进入）
  assert.equal(seen.has('m1'), false)
})

test('用户附件跨多条消息累积', () => {
  const turn = makeTurn()
  const seen = new Set<string>()

  accumulateUserMessage(
    turn,
    'm1',
    { raw_input: 'a', files: [{ name: 'a.png', url: '', path: '', size: 1, type: 'image/png' }] },
    seen
  )
  accumulateUserMessage(
    turn,
    'm2',
    { raw_input: 'b', files: [{ name: 'b.txt', url: '', path: '', size: 2, type: 'text/plain' }] },
    seen
  )

  assert.equal(turn.userFiles?.length, 2)
  assert.equal(turn.userFiles?.[0].name, 'a.png')
  assert.equal(turn.userFiles?.[1].name, 'b.txt')
})

test('raw_input 缺失时从 JSON content 提取文本', () => {
  const turn = makeTurn()
  const seen = new Set<string>()

  accumulateUserMessage(turn, 'm1', { content: JSON.stringify({ content: '来自 content' }) }, seen)

  assert.deepEqual(turn.userMessages, ['来自 content'])
})

test('getDisplayUserMessages：userMessages 为空时回退到单条 userMessage', () => {
  const turn: UserMessagesTurn = { userMessage: 'Fallback', userMessages: [], userFiles: null }
  assert.deepEqual(getDisplayUserMessages(turn), ['Fallback'])
})

test('getDisplayUserMessages：没有任何消息时返回空数组', () => {
  assert.deepEqual(getDisplayUserMessages(makeTurn()), [])
})

test('extractUserMessageText：无 data / 空 content 返回 null', () => {
  assert.equal(extractUserMessageText(undefined), null)
  assert.equal(extractUserMessageText({}), null)
})
