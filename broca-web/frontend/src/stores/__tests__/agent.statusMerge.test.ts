/**
 * Regression tests: agent status merge on periodic refresh.
 *
 * Bug: 「turn 执行中前端偶尔显示空闲，尤其工具执行耗时较久时」。
 *
 * Root cause:
 *   AgentSidebar 每 10s 轮询 fetchAgents()，直接用 DB 中的 agent_status
 *   整体覆盖前端状态。而 DB 状态由 Runner 心跳每 5s 才同步一次（且心跳快照
 *   可能比 Runner 的直接写入更旧）。长工具执行期间没有任何 socket 事件纠正，
 *   于是滞后的 DB 'idle' 会把前端由 turn_start / tool_call 事件设置好的
 *   'running' 覆盖成 'idle'。
 *
 * Fix:
 *   周期性刷新（preserveRunning: true）时不允许把 'running' 降级为 'idle'。
 *   running → idle 的权威信号只能来自 turn_end socket 事件。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

// Mock the session API used by the agent store.
vi.mock('@/api/session', () => ({
  sessionApi: {
    getSessionAgents: vi.fn(),
  },
}))

// Avoid touching real HTTP modules pulled in transitively by the store.
vi.mock('@/api/agent', () => ({ agentApi: {}, LLM_DEFAULT_KEY: '__default__' }))
vi.mock('@/api/config', () => ({ configApi: {}, LLM_DEFAULT_KEY: '__default__' }))

import { sessionApi } from '@/api/session'
import { useAgentStore } from '@/stores/agent'

function makeAgent(overrides: Record<string, any> = {}) {
  return {
    agent_id: 'agent-1',
    config_id: 'cfg-1',
    session_id: 'sess-1',
    name: 'Main Agent',
    role: 'main_agent',
    created_at: new Date().toISOString(),
    type: 'assistant',
    status: 'idle',
    ...overrides,
  }
}

const mockedGetSessionAgents = sessionApi.getSessionAgents as unknown as ReturnType<typeof vi.fn>

describe('agent store: status merge on periodic refresh', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockedGetSessionAgents.mockReset()
  })

  it('首次加载以 DB 状态为准（无 preserveRunning）', async () => {
    mockedGetSessionAgents.mockResolvedValue([makeAgent({ status: 'idle' })])
    const store = useAgentStore()

    await store.fetchAgents('sess-1')

    expect(store.agents[0].status).toBe('idle')
  })

  it('首次加载时 DB running 正常显示为 running', async () => {
    mockedGetSessionAgents.mockResolvedValue([makeAgent({ status: 'running' })])
    const store = useAgentStore()

    await store.fetchAgents('sess-1')

    expect(store.agents[0].status).toBe('running')
  })

  it('周期性刷新：DB 滞后为 idle 时不把 running 降级（核心回归）', async () => {
    // 初始加载
    mockedGetSessionAgents.mockResolvedValue([makeAgent({ status: 'idle' })])
    const store = useAgentStore()
    await store.fetchAgents('sess-1')

    // 收到 socket turn_start / tool_call 事件 → running
    store.updateAgentStatus('agent-1', 'running')
    expect(store.agents[0].status).toBe('running')

    // 长工具执行期间，10s 轮询读到滞后的 DB 'idle'
    mockedGetSessionAgents.mockResolvedValue([makeAgent({ status: 'idle' })])
    await store.fetchAgents('sess-1', { preserveRunning: true })

    // 不能因为滞后的 DB 状态而误显示空闲
    expect(store.agents[0].status).toBe('running')
  })

  it('周期性刷新：DB running 可把 idle 升级为 running', async () => {
    mockedGetSessionAgents.mockResolvedValue([makeAgent({ status: 'idle' })])
    const store = useAgentStore()
    await store.fetchAgents('sess-1')
    expect(store.agents[0].status).toBe('idle')

    mockedGetSessionAgents.mockResolvedValue([makeAgent({ status: 'running' })])
    await store.fetchAgents('sess-1', { preserveRunning: true })

    expect(store.agents[0].status).toBe('running')
  })

  it('周期性刷新：真实断连（disconnected）仍然生效', async () => {
    mockedGetSessionAgents.mockResolvedValue([makeAgent({ status: 'idle' })])
    const store = useAgentStore()
    await store.fetchAgents('sess-1')

    store.updateAgentStatus('agent-1', 'running')

    mockedGetSessionAgents.mockResolvedValue([makeAgent({ status: 'disconnected' })])
    await store.fetchAgents('sess-1', { preserveRunning: true })

    // 只保护 running→idle，不阻止 running→disconnected
    expect(store.agents[0].status).toBe('disconnected')
  })

  it('turn_end 后（前端已 idle）周期性刷新保持 idle', async () => {
    mockedGetSessionAgents.mockResolvedValue([makeAgent({ status: 'idle' })])
    const store = useAgentStore()
    await store.fetchAgents('sess-1')

    // 模拟一个 turn 结束后前端已是 idle，DB 也最终变为 idle
    store.updateAgentStatus('agent-1', 'idle')
    mockedGetSessionAgents.mockResolvedValue([makeAgent({ status: 'idle' })])
    await store.fetchAgents('sess-1', { preserveRunning: true })

    expect(store.agents[0].status).toBe('idle')
  })
})
