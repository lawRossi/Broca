/**
 * 回归测试：VSCode 设置页「LLM 配置保存成功后，顶部仍显示有未同步修改」。
 *
 * Bug 根因：脏检测比较的是含 `__default__`（全局默认 provider/model）的 wire 序列化，
 * 而保存成功后的基线曾写成 `JSON.stringify(config)`（不含 `__default__`）。
 * 只要设置了全局默认 provider/model，两者永远不相等 → 状态永远是脏的。
 *
 * 因此：**保存基线与脏检测必须走同一序列化口径**，且基线取「发起保存时」的快照
 * （否则保存期间的新编辑会被误标为已保存）。
 *
 * 用 Node 内置测试运行器执行（vscode 包本身没有 vitest 等测试框架）：
 *   node --test src/webview/src/utils/llmWireConfig.test.ts
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { buildLLMWireConfig, isLLMConfigDirty, llmBaselineJson } from './llmWireConfig.ts'
import { LLM_DEFAULT_KEY } from '../types.ts'
import type { LLMConfig, LLMDefaultConfig } from '../types.ts'

const CONFIG: LLMConfig = {
  deepseek: {
    base_url: 'https://api.deepseek.com/v1',
    api_key: 'sk-test',
    models: { m1: { model: 'deepseek-chat' } },
  },
}
const WITH_DEFAULT: LLMDefaultConfig = { provider: 'deepseek', model: 'm1' }
const WITHOUT_DEFAULT: LLMDefaultConfig = { provider: '', model: '' }

test('保存成功后立即回到「已同步」：基线与脏检测同口径（含 __default__）', () => {
  // llmBaselineJson(…) = persistConfig 发起保存时记录的 wire 快照
  const baseline = llmBaselineJson(CONFIG, WITH_DEFAULT)
  assert.equal(isLLMConfigDirty(CONFIG, WITH_DEFAULT, baseline), false)
})

test('回归：旧基线写法（不含 __default__）在设置了全局默认时永远判脏', () => {
  const legacyBaseline = JSON.stringify(CONFIG)
  assert.equal(isLLMConfigDirty(CONFIG, WITH_DEFAULT, legacyBaseline), true)
  // 正确的 wire 基线必须包含 __default__ 保留键
  const wire = JSON.parse(llmBaselineJson(CONFIG, WITH_DEFAULT))
  assert.equal(wire[LLM_DEFAULT_KEY]?.provider, 'deepseek')
  assert.equal(wire[LLM_DEFAULT_KEY]?.model, 'm1')
})

test('未设置全局默认 provider/model 时不注入 __default__', () => {
  const wire = buildLLMWireConfig(CONFIG, WITHOUT_DEFAULT)
  assert.equal(LLM_DEFAULT_KEY in wire, false)
  assert.equal(isLLMConfigDirty(CONFIG, WITHOUT_DEFAULT, llmBaselineJson(CONFIG, WITHOUT_DEFAULT)), false)
})

test('编辑提供商配置或全局默认模型都能被判脏', () => {
  const baseline = llmBaselineJson(CONFIG, WITH_DEFAULT)

  const editedProvider: LLMConfig = {
    deepseek: { ...CONFIG.deepseek, api_key: 'sk-rotated' },
  }
  assert.equal(isLLMConfigDirty(editedProvider, WITH_DEFAULT, baseline), true)

  const editedDefault: LLMDefaultConfig = { provider: 'deepseek', model: 'm2' }
  assert.equal(isLLMConfigDirty(CONFIG, editedDefault, baseline), true)
})

test('保存期间的新编辑：以发起保存时的快照为基线后仍判脏（不被误标为已保存）', () => {
  const snapshotAtSaveStart = llmBaselineJson(CONFIG, WITH_DEFAULT)
  // 保存在途时用户又改了 api_key
  const mutatedDuringSave: LLMConfig = {
    deepseek: { ...CONFIG.deepseek, api_key: 'sk-edited-late' },
  }
  assert.equal(isLLMConfigDirty(mutatedDuringSave, WITH_DEFAULT, snapshotAtSaveStart), true)
})

test('基线是快照而非引用：后续修改不会污染已记录的基线', () => {
  const baseline = llmBaselineJson(CONFIG, WITH_DEFAULT)
  const mutated: LLMConfig = {
    deepseek: { ...CONFIG.deepseek, api_key: 'sk-rotated' },
  }
  assert.equal(isLLMConfigDirty(mutated, WITH_DEFAULT, baseline), true)
  // 改回去之后又与基线一致
  assert.equal(isLLMConfigDirty(CONFIG, WITH_DEFAULT, baseline), false)
})
