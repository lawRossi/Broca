/**
 * Regression test: cross-endpoint dialog dismissal.
 *
 * Bug: user answers `ask_user` / permission dialog in VSCode, the VSCode dialog
 * closes immediately, but the Web dialog stays open for a long time — until the
 * whole turn finally ends (or never).
 *
 * Root cause: the server never told other subscribed clients that a request had
 * been answered. Web only closed dialogs on `turn_end`.
 *
 * Fix: the server broadcasts `request_resolved` (carrying request_id) to the
 * whole session subscription on USER_ANSWER / PERMISSION_RESPONSE, and both
 * frontends close the matching dialog by request_id.
 *
 * This test drives the Web chat store's registered socket handlers to verify
 * that a `request_resolved` event closes an already-open dialog.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

// --- Mock dependencies pulled in by the chat store -----------------------
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: {}, query: {} }),
}))

vi.mock('element-plus', () => ({ ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }))

vi.mock('@/api/session', () => ({
  sessionApi: {
    getRunnerStatus: vi.fn(),
    restartRunner: vi.fn(),
    stopRunner: vi.fn(),
    getSessionMessages: vi.fn(),
    getSessionTurns: vi.fn(),
  },
}))

// Capture socket handlers registered by the chat store so the test can fire them.
const handlers: Record<string, (m: any) => void> = {}
let mockSocketStore: any

vi.mock('@/stores', () => ({
  useAgentStore: () => ({
    agents: [],
    currentAgentId: 'agent-1',
    updateAgentStatus: vi.fn(),
    fetchAgents: vi.fn().mockResolvedValue([]),
    clearCache: vi.fn(),
  }),
  useSocketStore: () => mockSocketStore,
}))

import { useChatStore } from '@/stores/chat'

function makeMessage(message_type: string, data: Record<string, any> = {}, extra: Record<string, any> = {}) {
  return {
    message_id: `m_${Math.random()}`,
    message_type,
    timestamp: new Date().toISOString(),
    role: 'system',
    data,
    ...extra,
  }
}

describe('chat store: request_resolved closes dialog by requestId', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    for (const k of Object.keys(handlers)) delete handlers[k]

    mockSocketStore = {
      connected: false,
      connecting: false,
      onConnect: null,
      onDisconnect: null,
      onMessage: (_id: string, h: (m: any) => void) => { handlers.onMessage = h; return () => {} },
      onTurnStart: (_id: string, h: (m: any) => void) => { handlers.onTurnStart = h; return () => {} },
      onTurnEnd: (_id: string, h: (m: any) => void) => { handlers.onTurnEnd = h; return () => {} },
      onAgentResponse: (_id: string, h: (m: any) => void) => { handlers.onAgentResponse = h; return () => {} },
      onToolCall: (_id: string, h: (m: any) => void) => { handlers.onToolCall = h; return () => {} },
      onPermissionRequest: (_id: string, h: (m: any) => void) => { handlers.onPermissionRequest = h; return () => {} },
      onAgentQuery: (_id: string, h: (m: any) => void) => { handlers.onAgentQuery = h; return () => {} },
      onRequestResolved: (_id: string, h: (m: any) => void) => { handlers.onRequestResolved = h; return () => {} },
      connect: vi.fn().mockResolvedValue(undefined),
      subscribe: vi.fn().mockResolvedValue(() => {}),
      unsubscribe: vi.fn().mockResolvedValue(undefined),
    }
  })

  it('registers a request_resolved handler', () => {
    const store = useChatStore()
    store.doConnect()
    expect(typeof handlers.onRequestResolved).toBe('function')
  })

  it('agent_query dialog is closed when request_resolved arrives for the same requestId', () => {
    const store = useChatStore()
    store.doConnect()

    // Simulate agent_query opening the dialog
    handlers.onAgentQuery(makeMessage('agent_query', {
      question: 'Pick one', options: [{ name: 'A' }], request_id: 'q-1',
    }, { sender_id: 'agent-1', turn_id: 'turn-1' }))
    expect(store.agentQueryDialog.visible).toBe(true)
    expect(store.agentQueryDialog.requestId).toBe('q-1')

    // Another endpoint answered → server broadcasts request_resolved
    handlers.onRequestResolved(makeMessage('request_resolved', {
      request_id: 'q-1', resolved_type: 'agent_query',
    }))

    expect(store.agentQueryDialog.visible).toBe(false)
    expect(store.agentQueryDialog.requestId).toBeUndefined()
  })

  it('request_resolved for a different requestId does not close the open dialog', () => {
    const store = useChatStore()
    store.doConnect()

    handlers.onPermissionRequest(makeMessage('permission_request', {
      message: 'allow?', request_id: 'req-1', timeout: 90,
    }, { sender_id: 'agent-1', turn_id: 'turn-1' }))
    expect(store.permissionDialog.visible).toBe(true)

    // resolved for some other request → must not touch our dialog
    handlers.onRequestResolved(makeMessage('request_resolved', {
      request_id: 'req-OTHER', resolved_type: 'permission',
    }))
    expect(store.permissionDialog.visible).toBe(true)

    // now the real one → closes
    handlers.onRequestResolved(makeMessage('request_resolved', {
      request_id: 'req-1', resolved_type: 'permission',
    }))
    expect(store.permissionDialog.visible).toBe(false)
  })
})
