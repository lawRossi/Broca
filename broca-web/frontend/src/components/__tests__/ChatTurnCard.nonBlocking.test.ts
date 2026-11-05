/**
 * ChatTurnCard non-blocking mode tests.
 *
 * Verifies:
 * - 1 user message → single .user-msg-row, no --not-first class
 * - 3 user messages → 3 .user-msg-row, 2nd/3rd have --not-first
 * - displayUserMessages computed: falls back to userMessage if userMessages empty
 * - No user messages but has files → file section renders
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ChatTurnCard from '@/components/ChatTurnCard.vue'

function mountCard(turn: any, extra: any = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  return mount(ChatTurnCard, {
    props: { turn, consecutiveAgent: false, ...extra },
    global: {
      plugins: [pinia],
      stubs: { teleport: true },
    },
  })
}

function makeTurn(overrides: Record<string, any> = {}) {
  return {
    turnId: 'turn-1',
    sequenceNumber: 1,
    agentId: 'agent-1',
    agentName: 'Test Agent',
    userMessage: null as string | null,
    userMessages: [] as string[],
    status: 'completed' as const,
    currentTool: null,
    currentFilePath: null,
    currentTodoList: [],
    totalDuration: 5,
    totalSteps: 2,
    toolCallStats: [],
    finalResponse: 'Done',
    reasoningContent: '',
    isActive: false,
    startedAt: Date.now(),
    createdAt: '2025-01-01T00:00:00Z',
    lastMessageId: 'msg-1',
    changedFiles: null,
    errorMessage: null,
    errorSeverity: null,
    recoveryHint: null,
    userFiles: null,
    ...overrides,
  }
}

describe('ChatTurnCard — non-blocking user messages', () => {
  it('1 user message: single .user-msg-row, no --not-first class', () => {
    const turn = makeTurn({
      userMessage: 'Hello',
      userMessages: ['Hello'],
    })
    const wrapper = mountCard(turn)

    const rows = wrapper.findAll('.user-msg-row')
    expect(rows.length).toBe(1)
    expect(rows[0].classes()).not.toContain('user-msg-row--not-first')
    expect(rows[0].text()).toContain('Hello')
  })

  it('3 user messages: 3 .user-msg-row, 2nd/3rd have --not-first', () => {
    const turn = makeTurn({
      userMessage: 'Msg 1',
      userMessages: ['Msg 1', 'Msg 2', 'Msg 3'],
    })
    const wrapper = mountCard(turn)

    const rows = wrapper.findAll('.user-msg-row')
    expect(rows.length).toBe(3)
    expect(rows[0].classes()).not.toContain('user-msg-row--not-first')
    expect(rows[1].classes()).toContain('user-msg-row--not-first')
    expect(rows[2].classes()).toContain('user-msg-row--not-first')
  })

  it('no user messages but has files: file section renders, no msg rows', () => {
    const turn = makeTurn({
      userMessage: null,
      userMessages: [],
      userFiles: [{ name: 'test.png', url: 'http://x', path: '/x', size: 100, type: 'image/png' }],
    })
    const wrapper = mountCard(turn)

    // Section with files is present
    const sections = wrapper.findAll('.section-accent.accent-user')
    expect(sections.length).toBe(1)
    // No user-msg-row (no messages)
    expect(wrapper.findAll('.user-msg-row').length).toBe(0)
    // File image rendered
    expect(wrapper.find('img.user-file-thumb').exists()).toBe(true)
  })

  it('displayUserMessages falls back to userMessage when userMessages is empty', () => {
    const turn = makeTurn({
      userMessage: 'Fallback message',
      userMessages: [],
    })
    const wrapper = mountCard(turn)

    const rows = wrapper.findAll('.user-msg-row')
    expect(rows.length).toBe(1)
    expect(rows[0].text()).toContain('Fallback message')
  })
})
