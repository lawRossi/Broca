import request from '@/utils/request'

export interface LLMProvider {
  id: string
  name: string
}

export interface LLMModel {
  id: string
  name: string
}


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
  }
}

export default configApi