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
  /** Agent 角色，用于识别子 Agent */
  role?: string
}

/** 子 Agent 角色集合——不发送 turn_end，不需要 preserveRunning 保护 */
const SUBAGENT_ROLES = new Set(['session_memory_manager', 'persistent_memory_manager'])

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
    // 子 Agent 不发送 turn_end socket 事件，若被 preserveRunning 锁在
    // running 将永远无法降级。它们生命周期只有几秒，无需防心跳滞后保护。
    if (prev === 'running' && dbStatus === 'idle' && !SUBAGENT_ROLES.has(agent.role || '')) {
      result[agent.agent_id] = 'running'
    } else {
      result[agent.agent_id] = dbStatus
    }
  }
  return result
}
