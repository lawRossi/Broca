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

/** 基础配置（configs.json）：仅已知字段 */
export interface GeneralConfig {
  database_dir?: string
  log_file?: string
  log_level?: string
  llm_config_file?: string
  socket_server_url?: string
  api_server_url?: string
}

/** 工具权限配置（tool_permission_config.json） */
export interface ToolPermissionConfig {
  _description?: string
  _permission_values?: Record<string, string>
  tools: Record<string, string>
}

/** 合法权限值 */
export const PERMISSION_VALUES = ['allow', 'ask', 'forbidden'] as const
export type PermissionValue = (typeof PERMISSION_VALUES)[number]

/** 合法日志级别 */
export const LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] as const

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

  /**
   * 获取基础配置（configs.json）
   */
  async getGeneralConfig(): Promise<GeneralConfig> {
    return await request.get('/config/general')
  },

  /**
   * 保存基础配置（后端仅写回已知字段）
   */
  async saveGeneralConfig(config: GeneralConfig): Promise<void> {
    await request.put('/config/general', { config })
  },

  /**
   * 获取工具权限配置
   */
  async getToolPermissionConfig(): Promise<ToolPermissionConfig> {
    return await request.get('/config/tool-permission')
  },

  /**
   * 保存工具权限配置
   */
  async saveToolPermissionConfig(config: ToolPermissionConfig): Promise<void> {
    await request.put('/config/tool-permission', { config })
  },
}

export default configApi
