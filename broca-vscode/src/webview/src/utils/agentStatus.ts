/**
 * Agent 运行时状态的合并逻辑（纯函数，便于单测）。
 *
 * 背景：AgentSidebar 每 10s 会通过 `fetchAgents` 刷新一次 agent 列表，
 * 刷新读到的是数据库里的 `agent_status`。而数据库状态由 Runner 心跳每 5s
 * 才同步一次（且心跳快照可能比 Runner 的直接写入更旧）。
 *
 * 长工具执行期间没有任何 socket 事件来纠正状态，若用滞后的 DB `idle`
 * 覆盖由 `turn_start` / `tool_call` 事件设置好的 `running`，就会出现
 * 「turn 执行中却显示空闲」的假象。
 *
 * 因此：`running → idle` 的权威信号只能来自 `turn_end` 事件，
 * 周期性刷新时不允许把 `running` 降级为 `idle`。
 */

export type AgentStatus = 'idle' | 'running' | 'connecting' | 'disconnected'

export interface AgentStatusInput {
  agent_id: string
  /** 来自后端 DB 的原始状态字符串 */
  status?: string
}

/**
 * 把后端返回的 agent 列表合并为新的运行时状态表。
 *
 * @param agentList 后端返回的 agent 列表（含 DB 状态）
 * @param prevStatuses 当前前端已知的运行时状态（来自 socket 事件）
 * @returns 合并后的状态表
 */
export function mergeAgentStatuses(
  agentList: AgentStatusInput[],
  prevStatuses: Record<string, AgentStatus>
): Record<string, AgentStatus> {
  const result: Record<string, AgentStatus> = {}
  for (const agent of agentList) {
    const dbStatus: AgentStatus = agent.status === 'running' ? 'running' : 'idle'
    const prev = prevStatuses[agent.agent_id]
    result[agent.agent_id] =
      prev === 'running' && dbStatus === 'idle' ? 'running' : dbStatus
  }
  return result
}
