<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useChatStore } from '../stores/chat'
import { searchApi } from '../utils/api'
import type { Message } from '../types'

const chatStore = useChatStore()

const emit = defineEmits<{
  (e: 'close'): void
}>()

// Dialog visibility
const visible = defineModel<boolean>('visible', { default: false })

// Expose open method for parent
const open = () => {
  visible.value = true
  loadFilterOptions()
  nextTick(() => {
    searchInputRef.value?.focus()
    doSearch()
  })
}

defineExpose({ open })

// ========== Filter states ==========
const searchKeyword = ref('')
const selectedAgentId = ref('')
const selectedMessageType = ref('')
const selectedToolName = ref('')
const sortOrder = ref<'desc' | 'asc'>('desc')

// ========== Pagination ==========
const pageSize = ref(20)
const currentPage = ref(1)

// ========== Focus management ==========
const searchInputRef = ref<HTMLInputElement>()

// ========== Server-side results ==========
const results = ref<Message[]>([])
const totalResults = ref(0)
const loading = ref(false)

// ========== Filter options ==========
const toolNameOptions = ref<string[]>([])

const messageTypeOptions = [
  { value: 'user_message', label: 'User' },
  { value: 'agent_response', label: 'Agent' },
  { value: 'tool_call', label: 'Tool' },
  { value: 'command_result', label: 'Cmd' },
  { value: 'error', label: 'Error' },
  { value: 'agent_error', label: 'Agent Error' },
  { value: 'system_message', label: 'System' },
  { value: 'agent_system_message', label: 'Agent System' },
]

const agentOptions = computed(() => {
  return chatStore.agents
    .filter((a) => a.agent_id)
    .map((a) => ({
      value: a.agent_id,
      label: a.name || a.agent_id,
    }))
    .sort((a, b) => a.label.localeCompare(b.label))
})

// ========== API calls ==========

let searchTimer: ReturnType<typeof setTimeout> | null = null

const doSearch = async () => {
  if (!chatStore.sessionId) return

  loading.value = true

  try {
    const params: Record<string, any> = {
      skip: (currentPage.value - 1) * pageSize.value,
      limit: pageSize.value,
    }

    if (searchKeyword.value.trim()) {
      params.keyword = searchKeyword.value.trim()
    }
    if (selectedAgentId.value) {
      params.sender_id = selectedAgentId.value
    }
    if (selectedMessageType.value) {
      params.message_type = selectedMessageType.value
    }
    if (selectedToolName.value) {
      params.tool_name = selectedToolName.value
    }
    params.order = sortOrder.value

    const res = await searchApi.searchMessages(chatStore.sessionId, params)
    results.value = res.messages || []
    totalResults.value = res.total || 0
  } catch (e) {
    console.error('Search failed:', e)
    results.value = []
    totalResults.value = 0
  } finally {
    loading.value = false
  }
}

const loadFilterOptions = async () => {
  if (!chatStore.sessionId) return
  try {
    const res = await searchApi.getSearchFilters(chatStore.sessionId)
    toolNameOptions.value = res.tool_names || []
  } catch {
    toolNameOptions.value = []
  }
}

// ========== Pagination ==========

const totalPages = computed(() => Math.max(1, Math.ceil(totalResults.value / pageSize.value)))

/** Maximum number of page buttons to show before using ellipsis */
const MAX_VISIBLE_PAGES = 8

/**
 * Generates the list of page numbers / ellipsis markers for pagination display.
 * When totalPages <= MAX_VISIBLE_PAGES, shows all pages.
 * Otherwise, shows: 1 ... current-1 current current+1 ... last
 */
const visiblePages = computed(() => {
  const total = totalPages.value
  if (total <= MAX_VISIBLE_PAGES) {
    // Show all pages
    return Array.from({ length: total }, (_, i) => i + 1)
  }

  const current = currentPage.value
  const pages: (number | 'ellipsis-start' | 'ellipsis-end')[] = []

  // Always show first page
  pages.push(1)

  // Determine the range around the current page
  const rangeStart = Math.max(2, current - 1)
  const rangeEnd = Math.min(total - 1, current + 1)

  // Add ellipsis before range if there's a gap after page 1
  if (rangeStart > 2) {
    pages.push('ellipsis-start')
  }

  // Add pages around current
  for (let i = rangeStart; i <= rangeEnd; i++) {
    pages.push(i)
  }

  // Add ellipsis after range if there's a gap before last page
  if (rangeEnd < total - 1) {
    pages.push('ellipsis-end')
  }

  // Always show last page
  if (total > 1) {
    pages.push(total)
  }

  return pages
})

const handlePageChange = (page: number) => {
  currentPage.value = page
  doSearch()
}

// ========== Message detail state ==========

const selectedMessage = ref<Message | null>(null)
const showRawJson = ref(false)

const viewMessage = (m: Message) => {
  selectedMessage.value = m
  showRawJson.value = false
}

const closeDetail = () => {
  selectedMessage.value = null
}

// ========== Display helpers ==========

const getSenderLabel = (m: Message): string => {
  if (m.message_type === 'user_message' || m.role === 'user') {
    return 'You'
  }
  const agentId = m.sender_id || m.agent_id
  if (agentId) {
    const agent = chatStore.agents.find((a) => a.agent_id === agentId)
    return agent?.name || agentId
  }
  if (m.role === 'system' || m.role === 'agent_system') return 'System'
  return 'Unknown'
}

const getFilePath = (m: Message): string | null => {
  if (m.message_type !== 'tool_call') return null
  const toolName = m.data?.tool_name
  if (toolName !== 'read_file' && toolName !== 'write_file' && toolName !== 'edit_file') return null
  try {
    const args = typeof m.data?.arguments === 'string' ? JSON.parse(m.data.arguments) : m.data?.arguments
    return args?.path || null
  } catch {
    return null
  }
}

const isFileTool = (m: Message): boolean => {
  if (m.message_type !== 'tool_call') return false
  const toolName = m.data?.tool_name
  return toolName === 'read_file' || toolName === 'write_file' || toolName === 'edit_file'
}

const getContentPreview = (m: Message): string => {
  if (m.message_type === 'tool_call') {
    const toolName = m.data?.tool_name || 'unknown_tool'
    const status = m.data?.status
    const hasResult = m.data?.result !== undefined
    let preview = `[${toolName}]`
    if (hasResult) preview += status === 'error' ? ' ❌' : ' ✅'
    else preview += ' ⏳'
    return preview
  }

  if (m.message_type === 'command_result') {
    const result = m.data?.result
    if (typeof result === 'object' && result !== null) {
      return result.message || result.value || JSON.stringify(result)
    }
    return result || m.data?.message || ''
  }

  const content = m.data?.content || m.data?.message || ''
  if (typeof content === 'string') {
    try {
      const parsed = JSON.parse(content)
      if (parsed && typeof parsed === 'object') {
        if (Array.isArray(parsed.content)) {
          const textParts = parsed.content.filter((p: any) => p.type === 'text')
          return textParts.map((p: any) => p.text).join('')
        }
        return parsed.content || JSON.stringify(parsed).slice(0, 200)
      }
    } catch { /* not json */ }
    return content.slice(0, 300)
  }
  return String(content).slice(0, 300)
}

const getDataPreview = (m: Message): string => {
  const preview = getContentPreview(m)
  return preview.replace(/<[^>]*>/g, '').slice(0, 200)
}

const getTypeBadgeClass = (messageType: string): string => {
  switch (messageType) {
    case 'user_message': return 'type-user'
    case 'agent_response': return 'type-agent'
    case 'tool_call': return 'type-tool'
    case 'error':
    case 'agent_error': return 'type-error'
    case 'system_message':
    case 'agent_system_message': return 'type-system'
    default: return 'type-default'
  }
}

const getTypeLabel = (messageType: string): string => {
  switch (messageType) {
    case 'user_message': return 'User'
    case 'agent_response': return 'Agent'
    case 'tool_call': return 'Tool'
    case 'error':
    case 'agent_error': return 'Error'
    case 'system_message':
    case 'agent_system_message': return 'System'
    case 'command_result': return 'Cmd'
    default: return messageType
  }
}

const formatJson = (data: unknown): string => {
  try {
    return JSON.stringify(data, null, 2)
  } catch {
    return String(data)
  }
}

const formatBeijingTimeShort = (timestamp: string): string => {
  if (!timestamp) return ''
  const d = new Date(timestamp)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// ========== Methods ==========

const resetFilters = () => {
  searchKeyword.value = ''
  selectedAgentId.value = ''
  selectedMessageType.value = ''
  selectedToolName.value = ''
  sortOrder.value = 'desc'
  currentPage.value = 1
  doSearch()
  nextTick(() => searchInputRef.value?.focus())
}

const handleClose = () => {
  visible.value = false
  emit('close')
}

// ========== Keyboard shortcut ==========

const handleKeydown = (e: KeyboardEvent) => {
  if (e.key === 'Escape' && visible.value) {
    handleClose()
  }
}

onMounted(() => {
  document.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeydown)
})

// ========== Watchers: auto-search on filter change ==========

watch([searchKeyword, selectedAgentId, selectedMessageType, selectedToolName, sortOrder], () => {
  currentPage.value = 1
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    doSearch()
  }, 300)
})

// When dialog opens, focus search input
watch(visible, (val) => {
  if (val) {
    loadFilterOptions()
    nextTick(() => {
      searchInputRef.value?.focus()
      doSearch()
    })
  }
})
</script>

<template>
  <Transition name="search-fade">
    <div
      v-if="visible"
      class="search-overlay"
      @click.self="handleClose"
    >
      <div class="search-dialog">
        <!-- Header -->
        <div class="dialog-header">
          <h3 class="dialog-title">
            <span>🔍</span>
            <span>消息搜索</span>
          </h3>
          <div class="dialog-header-actions">
            <button class="btn btn-secondary btn-sm" @click="resetFilters">重置</button>
            <button class="btn btn-secondary btn-sm" @click="handleClose">✕ 关闭</button>
          </div>
        </div>

        <!-- Filter bar -->
        <div class="filter-bar">
          <div class="filter-row">
            <!-- Keyword search -->
            <div class="search-input-wrapper">
              <span class="search-input-icon">🔎</span>
              <input
                ref="searchInputRef"
                v-model="searchKeyword"
                type="text"
                class="search-input"
                placeholder="搜索关键词..."
              />
            </div>

            <!-- Agent filter -->
            <select
              v-model="selectedAgentId"
              class="filter-select"
            >
              <option value="">Agent</option>
              <option
                v-for="opt in agentOptions"
                :key="opt.value"
                :value="opt.value"
              >{{ opt.label }}</option>
            </select>

            <!-- Message type -->
            <select
              v-model="selectedMessageType"
              class="filter-select"
            >
              <option value="">类型</option>
              <option
                v-for="opt in messageTypeOptions"
                :key="opt.value"
                :value="opt.value"
              >{{ opt.label }}</option>
            </select>

            <!-- Tool name -->
            <select
              v-model="selectedToolName"
              class="filter-select"
            >
              <option value="">工具</option>
              <option
                v-for="name in toolNameOptions"
                :key="name"
                :value="name"
              >{{ name }}</option>
            </select>

            <!-- Result count -->
            <span class="result-count">
              <template v-if="loading">⏳</template>
              <template v-else>共 <strong>{{ totalResults }}</strong> 条</template>
            </span>
          </div>
        </div>

        <!-- Results / Detail -->
        <div class="dialog-body">
          <!-- ====== Message Detail View ====== -->
          <template v-if="selectedMessage">
            <div class="detail-view">
              <button class="back-btn" @click="closeDetail">
                ← 返回搜索结果
              </button>

              <div class="detail-header">
                <span
                  class="type-badge"
                  :class="getTypeBadgeClass(selectedMessage.message_type)"
                >
                  {{ getTypeLabel(selectedMessage.message_type) }}
                </span>
                <span class="detail-sender">{{ getSenderLabel(selectedMessage) }}</span>
                <span class="detail-time">{{ formatBeijingTimeShort(selectedMessage.timestamp) }}</span>
              </div>

              <div class="detail-content-box">
                <div class="detail-content-header">
                  <span class="detail-content-title">内容</span>
                  <button
                    class="btn btn-text btn-sm"
                    @click="showRawJson = !showRawJson"
                  >
                    {{ showRawJson ? '友好视图' : '查看原始 JSON' }}
                  </button>
                </div>

                <div v-if="!showRawJson" class="detail-fields">
                  <template v-if="selectedMessage.data">
                    <div
                      v-for="(value, key) in selectedMessage.data"
                      :key="String(key)"
                      class="detail-field"
                    >
                      <span class="field-key">{{ key }}</span>
                      <span class="field-value">{{ typeof value === 'object' ? formatJson(value) : String(value) }}</span>
                    </div>
                  </template>
                  <div v-else class="detail-empty">无数据</div>
                </div>

                <div v-else class="detail-json">
                  <pre>{{ formatJson(selectedMessage.data) }}</pre>
                </div>
              </div>
            </div>
          </template>

          <!-- ====== List View ====== -->
          <template v-else>
            <!-- Loading -->
            <div
              v-if="loading && results.length === 0"
              class="state-empty"
            >
              <div class="state-icon">⏳</div>
              <div class="state-text">搜索中...</div>
            </div>

            <!-- Empty state -->
            <div
              v-else-if="results.length === 0"
              class="state-empty"
            >
              <div class="state-icon">📭</div>
              <div class="state-text">没有匹配的消息</div>
              <div class="state-hint">尝试修改筛选条件或关键词</div>
            </div>

            <!-- Results table -->
            <template v-else>
              <table class="search-table">
                <thead>
                  <tr>
                    <th class="col-sender">发送者</th>
                    <th class="col-type">类型</th>
                    <th class="col-content">内容预览</th>
                    <th
                      class="col-time sortable"
                      @click="sortOrder = sortOrder === 'desc' ? 'asc' : 'desc'"
                    >
                      <span class="sort-header">
                        时间
                        <span class="sort-indicator">{{ sortOrder === 'desc' ? '↓' : '↑' }}</span>
                      </span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="(m, index) in results"
                    :key="m.message_id || index"
                    class="search-row"
                    @click="viewMessage(m)"
                  >
                    <td class="col-sender">
                      <span class="sender-name">{{ getSenderLabel(m) }}</span>
                    </td>
                    <td class="col-type">
                      <span
                        class="type-badge"
                        :class="getTypeBadgeClass(m.message_type)"
                      >
                        {{ getTypeLabel(m.message_type) }}
                      </span>
                    </td>
                    <td class="col-content">
                      <div class="data-preview">{{ getDataPreview(m) }}</div>
                      <div v-if="isFileTool(m) && getFilePath(m)" class="file-path">
                        📁 {{ getFilePath(m) }}
                      </div>
                    </td>
                    <td class="col-time">
                      <span class="time-text">{{ formatBeijingTimeShort(m.timestamp) }}</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </template>
          </template>
        </div>

        <!-- Footer: Pagination -->
        <div
          v-if="totalPages > 1 && !selectedMessage"
          class="dialog-footer"
        >
          <span class="page-info">第 {{ currentPage }}/{{ totalPages }} 页</span>
          <div class="pagination">
            <button
              class="page-btn"
              :disabled="currentPage <= 1"
              @click="handlePageChange(currentPage - 1)"
            >‹</button>
            <template v-for="p in visiblePages" :key="p">
              <span v-if="p === 'ellipsis-start' || p === 'ellipsis-end'" class="page-ellipsis">…</span>
              <button
                v-else
                class="page-btn"
                :class="{ active: p === currentPage }"
                @click="handlePageChange(p)"
              >{{ p }}</button>
            </template>
            <button
              class="page-btn"
              :disabled="currentPage >= totalPages"
              @click="handlePageChange(currentPage + 1)"
            >›</button>
          </div>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
/* ========== Overlay ========== */
.search-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 500;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 5vh;
  background-color: rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(2px);
}

/* ========== Dialog ========== */
.search-dialog {
  background: var(--bg-primary, #1e1e1e);
  border: 1px solid var(--border-color, #3c3c3c);
  border-radius: 10px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  width: 90vw;
  max-width: 960px;
  max-height: 80vh;
}

/* ========== Transition ========== */
.search-fade-enter-active,
.search-fade-leave-active {
  transition: opacity 0.2s ease;
}
.search-fade-enter-from,
.search-fade-leave-to {
  opacity: 0;
}
.search-fade-enter-active .search-dialog,
.search-fade-leave-active .search-dialog {
  transition: transform 0.2s ease;
}
.search-fade-enter-from .search-dialog,
.search-fade-leave-to .search-dialog {
  transform: translateY(-20px) scale(0.98);
}

/* ========== Dialog Header ========== */
.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color, #3c3c3c);
  background: var(--bg-secondary, #252526);
  flex-shrink: 0;
}

.dialog-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #cccccc);
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
}

.dialog-header-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

/* ========== Buttons ========== */
.btn {
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-weight: 500;
  font-size: 12px;
  padding: 6px 12px;
  white-space: nowrap;
  transition: background 0.15s;
}

.btn-sm {
  padding: 4px 10px;
  font-size: 11px;
}

.btn-secondary {
  background: var(--bg-tertiary, #3c3c3c);
  color: var(--text-primary, #cccccc);
  border: 1px solid var(--border-color, #3c3c3c);
}
.btn-secondary:hover {
  background: var(--border-color, #555);
}

.btn-text {
  background: none;
  color: var(--text-link, #3794ff);
  border: none;
  padding: 2px 6px;
}
.btn-text:hover {
  text-decoration: underline;
}

/* ========== Filter Bar ========== */
.filter-bar {
  padding: 10px 16px;
  border-bottom: 1px solid var(--border-color, #3c3c3c);
  background: var(--bg-primary, #1e1e1e);
  flex-shrink: 0;
}

.filter-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.search-input-wrapper {
  position: relative;
  flex: 1;
  min-width: 160px;
}

.search-input-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 14px;
  pointer-events: none;
  opacity: 0.5;
}

.search-input {
  width: 100%;
  padding: 7px 12px 7px 32px;
  background: var(--input-bg, #3c3c3c);
  color: var(--input-text, #cccccc);
  border: 1px solid var(--input-border, #3c3c3c);
  border-radius: 4px;
  font-size: 13px;
  outline: none;
  font-family: inherit;
}
.search-input:focus {
  border-color: var(--focus-border, #007fd4);
}
.search-input::placeholder {
  color: var(--text-secondary, #8b8b8b);
}

.filter-select {
  padding: 7px 10px;
  background: var(--input-bg, #3c3c3c);
  color: var(--input-text, #cccccc);
  border: 1px solid var(--input-border, #3c3c3c);
  border-radius: 4px;
  font-size: 12px;
  outline: none;
  cursor: pointer;
  flex: none;
  min-width: 110px;
  font-family: inherit;
}
.filter-select:focus {
  border-color: var(--focus-border, #007fd4);
}

.result-count {
  font-size: 12px;
  color: var(--text-secondary, #8b8b8b);
  white-space: nowrap;
  flex-shrink: 0;
}
.result-count strong {
  color: var(--text-primary, #cccccc);
}

/* ========== Dialog Body ========== */
.dialog-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

/* ========== Empty / Loading State ========== */
.state-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 0;
  color: var(--text-secondary, #8b8b8b);
}
.state-icon {
  font-size: 36px;
  margin-bottom: 8px;
  opacity: 0.6;
}
.state-text {
  font-size: 14px;
}
.state-hint {
  font-size: 12px;
  margin-top: 4px;
  opacity: 0.7;
}

/* ========== Search Table ========== */
.search-table {
  width: 100%;
  border-collapse: collapse;
}

.search-table thead th {
  position: sticky;
  top: 0;
  background: var(--bg-secondary, #252526);
  border-bottom: 1px solid var(--border-color, #3c3c3c);
  padding: 10px 12px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary, #8b8b8b);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  text-align: left;
  z-index: 1;
}

.col-sender { width: 120px; }
.col-type { width: 80px; }
.col-content { min-width: 200px; }
.col-time { width: 120px; text-align: right; }

.sortable {
  cursor: pointer;
  user-select: none;
}
.sortable:hover {
  color: var(--text-primary, #cccccc);
}

.sort-header {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.sort-indicator {
  font-size: 10px;
}

.search-row {
  cursor: pointer;
  transition: background 0.1s ease;
  border-bottom: 1px solid var(--border-color, #3c3c3c);
}
.search-row:hover {
  background: var(--list-hover-bg, rgba(128, 128, 128, 0.08));
}
.search-row:last-child {
  border-bottom: none;
}

.search-row td {
  padding: 8px 12px;
  font-size: 12px;
  vertical-align: top;
}

.sender-name {
  font-weight: 500;
  color: var(--text-primary, #cccccc);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: block;
  max-width: 110px;
}

.type-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 600;
  white-space: nowrap;
}

.type-user {
  background: rgba(59, 130, 246, 0.15);
  color: var(--text-link, #3794ff);
}
.type-agent {
  background: rgba(34, 197, 94, 0.15);
  color: var(--success-fg, #73c991);
}
.type-tool {
  background: rgba(168, 85, 247, 0.15);
  color: #a78bfa;
}
.type-error {
  background: rgba(239, 68, 68, 0.15);
  color: var(--error-fg, #f48771);
}
.type-system {
  background: rgba(156, 163, 175, 0.15);
  color: var(--text-secondary, #8b8b8b);
}
.type-default {
  background: rgba(156, 163, 175, 0.15);
  color: var(--text-secondary, #8b8b8b);
}

.data-preview {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.4;
  color: var(--text-primary, #cccccc);
  font-size: 12px;
  word-break: break-word;
}

.file-path {
  font-size: 11px;
  color: var(--text-link, #3794ff);
  font-family: var(--code-font-family, monospace);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.time-text {
  font-size: 11px;
  color: var(--text-secondary, #8b8b8b);
  white-space: nowrap;
}

/* ========== Detail View ========== */
.detail-view {
  padding: 16px;
}

.back-btn {
  background: none;
  border: none;
  color: var(--text-link, #3794ff);
  cursor: pointer;
  font-size: 13px;
  padding: 4px 0;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 4px;
}
.back-btn:hover {
  text-decoration: underline;
}

.detail-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.detail-sender {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #cccccc);
}

.detail-time {
  font-size: 12px;
  color: var(--text-secondary, #8b8b8b);
  margin-left: auto;
}

.detail-content-box {
  background: var(--bg-secondary, #252526);
  border: 1px solid var(--border-color, #3c3c3c);
  border-radius: 8px;
  overflow: hidden;
}

.detail-content-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-color, #3c3c3c);
}

.detail-content-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary, #cccccc);
}

.detail-fields {
  padding: 4px 0;
}

.detail-field {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 8px 14px;
  border-bottom: 1px solid var(--border-color, #3c3c3c);
  font-size: 12px;
}
.detail-field:last-child {
  border-bottom: none;
}

.field-key {
  color: var(--text-secondary, #8b8b8b);
  font-weight: 500;
  flex-shrink: 0;
  width: 80px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.field-value {
  color: var(--text-primary, #cccccc);
  word-break: break-all;
  font-family: var(--code-font-family, monospace);
  font-size: 11px;
  line-height: 1.5;
  min-width: 0;
}

.detail-empty {
  padding: 20px;
  text-align: center;
  color: var(--text-secondary, #8b8b8b);
  font-size: 13px;
}

.detail-json {
  padding: 14px;
}

.detail-json pre {
  margin: 0;
  font-family: var(--code-font-family, monospace);
  font-size: 11px;
  line-height: 1.5;
  color: var(--text-primary, #cccccc);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 400px;
  overflow-y: auto;
}

/* ========== Footer / Pagination ========== */
.dialog-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-top: 1px solid var(--border-color, #3c3c3c);
  background: var(--bg-secondary, #252526);
  flex-shrink: 0;
}

.page-info {
  font-size: 12px;
  color: var(--text-secondary, #8b8b8b);
}

.pagination {
  display: flex;
  align-items: center;
  gap: 2px;
}

.page-btn {
  min-width: 26px;
  height: 26px;
  padding: 0 6px;
  background: transparent;
  color: var(--text-primary, #cccccc);
  border: 1px solid transparent;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 500;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}

.page-btn:hover:not(:disabled):not(.active) {
  background: var(--bg-tertiary, #3c3c3c);
  border-color: var(--border-color, #3c3c3c);
}

.page-btn.active {
  background: var(--button-bg, #0e639c);
  color: var(--button-text, #ffffff);
  border-color: var(--button-bg, #0e639c);
}

.page-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.page-ellipsis {
  min-width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  color: var(--text-secondary, #8b8b8b);
  letter-spacing: 2px;
  user-select: none;
}

/* ========== Scrollbar ========== */
.dialog-body::-webkit-scrollbar {
  width: 8px;
}
.dialog-body::-webkit-scrollbar-track {
  background: transparent;
}
.dialog-body::-webkit-scrollbar-thumb {
  background: var(--scrollbar-bg, #424242);
  border-radius: 4px;
}
.dialog-body::-webkit-scrollbar-thumb:hover {
  background: var(--scrollbar-hover-bg, #4f4f4f);
}
</style>
