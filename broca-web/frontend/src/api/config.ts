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
  execution?: ExecutionConfig
}

/** 执行引擎配置（configs.json 中的 execution 分组，数字型） */
export interface ExecutionConfig {
  step_max_errors?: number
  llm_retry_delay?: number
  tool_call_timeout?: number
  assign_task_timeout?: number
  llm_timeout?: number
  llm_first_chunk_timeout?: number
  dead_loop_window?: number
  message_queue_size?: number
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

/** 单个 MCP 服务器配置（stdio 与 HTTP 二选一） */
export interface McpServerConfig {
  /** stdio 传输：可执行命令（与 url 二选一） */
  command?: string
  /** stdio 传输：命令参数列表 */
  args?: string[]
  /** stdio 传输：环境变量 */
  env?: Record<string, string>
  /** stdio 传输：工作目录 */
  cwd?: string
  /** HTTP 传输：MCP 服务 URL（与 command 二选一） */
  url?: string
  /** HTTP 传输：请求头 */
  headers?: Record<string, string>
  /** 单次工具调用超时秒数 */
  tool_timeout?: number
  [key: string]: unknown
}

/** 完整 MCP 配置：服务器名 → 服务器配置 */
export type McpConfig = Record<string, McpServerConfig>

/** MCP 传输类型 */
export const MCP_TRANSPORTS = ['stdio', 'http'] as const
export type McpTransport = (typeof MCP_TRANSPORTS)[number]

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

  /**
   * 获取 MCP 服务器配置（mcp_config.json）
   */
  async getMcpConfig(): Promise<McpConfig> {
    return await request.get('/config/mcp')
  },

  /**
   * 保存 MCP 服务器配置
   */
  async saveMcpConfig(config: McpConfig): Promise<void> {
    await request.put('/config/mcp', { config })
  },
}

export default configApi
