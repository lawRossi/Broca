/**
 * LLM 配置「工作集 ↔ wire 格式」的组装与脏检测基线（纯函数，便于单测）。
 *
 * 回归背景（VSCode 设置页 bug）：
 * 「LLM 配置保存成功后顶部仍显示有未同步修改」。
 * 根因：脏检测比较的是含 `__default__` 保留键的 wire 序列化，
 * 而保存成功后的基线写成了 `JSON.stringify(config)`（不含 `__default__`）——
 * 只要设置了全局默认 provider/model，两者永远不相等，状态永远是脏的。
 *
 * 约定：**基线与脏检测必须走同一序列化口径**（本模块的 `llmBaselineJson`），
 * 且保存基线应取「发起保存时」的快照（而非保存完成时的当前状态），
 * 否则保存期间的新编辑会被误判为已落盘。
 */
import { LLM_DEFAULT_KEY } from '../types.ts'
import type { LLMConfig, LLMDefaultConfig, LLMWireConfig } from '../types.ts'

/** 工作集（提供商 + 可选全局默认 provider/model）→ 后端 wire 格式 */
export function buildLLMWireConfig(config: LLMConfig, llmDefault: LLMDefaultConfig | undefined): LLMWireConfig {
  const full: LLMWireConfig = { ...config }
  if (llmDefault?.provider) full[LLM_DEFAULT_KEY] = { ...llmDefault }
  return full
}

/** 保存基线：与脏检测完全同口径的 JSON 字符串（含 `__default__`） */
export function llmBaselineJson(config: LLMConfig, llmDefault: LLMDefaultConfig | undefined): string {
  return JSON.stringify(buildLLMWireConfig(config, llmDefault))
}

/** 当前工作集是否与基线不一致（即“有未保存修改”） */
export function isLLMConfigDirty(
  config: LLMConfig,
  llmDefault: LLMDefaultConfig | undefined,
  baselineJson: string
): boolean {
  return llmBaselineJson(config, llmDefault) !== baselineJson
}
