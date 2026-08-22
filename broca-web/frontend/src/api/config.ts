import request from '@/utils/request'

export interface LLMProvider {
  id: string
  name: string
}

export interface LLMModel {
  id: string
  name: string
}

/** 模型元信息（modality、上下文窗口等） */
export interface LLMModelMeta {
  modality?: Record<string, unknown>
  context_window?: number
  [key: string]: unknown
}

/** 单个模型配置 */
export interface LLMModelConfig {
  /** 实际模型名，如 openai/deepseek-v4-flash */
  model: string
  temperature?: number
  max_tokens?: number
  extra_body?: Record<string, unknown>
  reasoning_effort?: string
  allowed_openai_params?: string[]
  meta?: LLMModelMeta
  [key: string]: unknown
}

/** 单个提供商配置 */
export interface LLMProviderConfig {
  base_url: string
  api_key: string
  models: Record<string, LLMModelConfig>
  [key: string]: unknown
}

/** 完整 LLM 配置：provider id → 提供商配置 */
export type LLMConfig = Record<string, LLMProviderConfig>

export const configApi = {
  /**
   * 获取可用的LLM提供商列表
   */
  async getLLMProviders(): Promise<LLMProvider[]> {
    return await request.get('/config/llm/providers')
  },

  /**
   * 获取指定提供商的可用模型
   */
  async getLLMModels(provider: string): Promise<LLMModel[]> {
    return await request.get(`/config/llm/models/${provider}`)
  },

  /**
   * 获取完整 LLM 配置（含提供商、模型、api_key）
   */
  async getLLMConfig(): Promise<LLMConfig> {
    return await request.get('/config/llm')
  },

  /**
   * 保存完整 LLM 配置
   */
  async saveLLMConfig(config: LLMConfig): Promise<void> {
    await request.put('/config/llm', { config })
  },
}

export default configApi
