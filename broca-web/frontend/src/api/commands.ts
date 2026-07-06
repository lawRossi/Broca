import request from '@/utils/request'

export interface CommandInfo {
  name: string
  description: string
  short_description: string
  type: string
  argument_hint: string
}

export interface CommandsResponse {
  commands: CommandInfo[]
}

export const commandsApi = {
  /**
   * 获取所有可用的命令列表
   */
  async getCommands(): Promise<CommandsResponse> {
    return request.get('/commands')
  },

  /**
   * 获取指定命令的详情
   */
  async getCommand(name: string): Promise<CommandInfo> {
    return request.get(`/commands/${name}`)
  },
}

export default commandsApi
