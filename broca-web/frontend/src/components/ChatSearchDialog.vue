<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { Close } from '@element-plus/icons-vue'
import { useChatStore, useAgentStore } from '@/stores'
import { sessionApi } from '@/api/session'
import type { Message } from '@/api/brocaSocket'
import { formatBeijingTimeShort } from '@/utils/time'

const chatStore = useChatStore()
const agentStore = useAgentStore()

const emit = defineEmits<{
  (e: 'close'): void
}>()

// Dialog visibility
const visible = defineModel<boolean>('visible', { default: false })

// 暴露 open 方法给父组件调用
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
const sortOrder = ref<'desc' | 'asc'>('desc')  // desc=最新在前, asc=最早在前

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
  return agentStore.agents
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

    const res = await sessionApi.searchSessionMessages(chatStore.sessionId, params)
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
    const res = await sessionApi.getSearchFilters(chatStore.sessionId)
    toolNameOptions.value = res.tool_names || []
  } catch {
    toolNameOptions.value = []
  }
}

// ========== Pagination ==========

const totalPages = computed(() => Math.max(1, Math.ceil(totalResults.value / pageSize.value)))

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
    const agent = agentStore.agents.find((a) => a.agent_id === agentId)
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
  <!-- Dialog overlay -->
  <Teleport to="body">
    <Transition name="search-fade">
      <div
        v-if="visible"
        class="search-overlay fixed inset-0 z-40 flex sm:items-start items-end justify-center sm:pt-[10vh]"
        @click.self="handleClose"
      >
        <div
          class="
            search-dialog bg-white shadow-2xl border border-gray-200
            flex flex-col overflow-hidden
            sm:rounded-xl sm:max-w-5xl sm:max-h-[80vh] sm:w-[90vw]
            w-full max-h-[85vh] sm:mx-0
            rounded-t-2xl
          "
        >
          <!-- Header -->
          <div class="flex items-center justify-between px-3 sm:px-5 py-2.5 sm:py-3 border-b border-gray-200 bg-gray-50">
            <h3 class="text-sm sm:text-base font-semibold text-gray-700 flex items-center gap-1.5 sm:gap-2">
              <span>🔍</span>
              <span>消息搜索</span>
            </h3>
            <div class="flex items-center gap-1.5 sm:gap-2">
              <el-button size="small" @click="resetFilters">重置</el-button>
              <el-button size="small" type="default" @click="handleClose" :icon="Close" class="!px-2 sm:!px-3">
                <span class="hidden sm:inline">关闭</span>
              </el-button>
            </div>
          </div>

          <!-- Filter bar -->
          <div class="filter-bar px-3 sm:px-5 py-2.5 sm:py-3 border-b border-gray-100 bg-white">
            <div class="flex flex-col sm:flex-row sm:items-center sm:gap-2 gap-2">
              <!-- Keyword search -->
              <el-input
                ref="searchInputRef"
                v-model="searchKeyword"
                placeholder="搜索关键词..."
                clearable
                size="default"
                class="search-input flex-1 min-w-0"
              >
                <template #prefix>
                  <span class="text-gray-400">🔎</span>
                </template>
              </el-input>

              <!-- Agent filter -->
              <el-select
                v-model="selectedAgentId"
                placeholder="Agent"
                clearable
                size="default"
                :teleported="true"
                style="flex: none; width: 150px"
              >
                <el-option
                  v-for="opt in agentOptions"
                  :key="opt.value"
                  :label="opt.label"
                  :value="opt.value"
                />
              </el-select>

              <!-- Message type -->
              <el-select
                v-model="selectedMessageType"
                placeholder="类型"
                clearable
                size="default"
                :teleported="true"
                style="flex: none; width: 150px"
              >
                <el-option
                  v-for="opt in messageTypeOptions"
                  :key="opt.value"
                  :label="opt.label"
                  :value="opt.value"
                />
              </el-select>

              <!-- Tool name -->
              <el-select
                v-model="selectedToolName"
                placeholder="工具"
                clearable
                size="default"
                :teleported="true"
                style="flex: none; width: 150px"
              >
                <el-option
                  v-for="name in toolNameOptions"
                  :key="name"
                  :label="name"
                  :value="name"
                />
              </el-select>

              <!-- Result count -->
              <span class="text-xs text-gray-400 whitespace-nowrap flex-none">
                <template v-if="loading">⏳</template>
                <template v-else>共 <strong class="text-gray-600">{{ totalResults }}</strong> 条</template>
              </span>
            </div>
          </div>

          <!-- Results / Detail -->
          <div class="flex-1 min-h-0 overflow-auto">
            <!-- ====== Message Detail View ====== -->
            <template v-if="selectedMessage">
              <div class="p-3 sm:p-5">
                <button
                  class="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 mb-3 sm:mb-4 transition-colors"
                  @click="closeDetail"
                >
                  <span class="text-base">←</span>
                  <span>返回搜索结果</span>
                </button>

                <div class="flex flex-wrap items-center gap-2 mb-4">
                  <span
                    class="type-badge inline-block px-2.5 py-1 rounded text-xs font-medium"
                    :class="getTypeBadgeClass(selectedMessage.message_type)"
                  >
                    {{ getTypeLabel(selectedMessage.message_type) }}
                  </span>
                  <span class="text-sm font-semibold text-gray-800">
                    {{ getSenderLabel(selectedMessage) }}
                  </span>
                  <span class="text-xs text-gray-400 ml-auto">
                    {{ formatBeijingTimeShort(selectedMessage.timestamp) }}
                  </span>
                </div>

                <div class="bg-gray-50 rounded-lg border border-gray-200">
                  <div class="px-3 py-2.5 border-b border-gray-200">
                    <div class="flex items-center justify-between">
                      <span class="text-sm font-medium text-gray-700">内容</span>
                      <el-button
                        size="small"
                        text
                        type="primary"
                        @click="showRawJson = !showRawJson"
                      >
                        {{ showRawJson ? '友好视图' : '查看原始 JSON' }}
                      </el-button>
                    </div>
                  </div>

                  <div v-if="!showRawJson" class="divide-y divide-gray-200">
                    <template v-if="selectedMessage.data">
                      <div
                        v-for="(value, key) in selectedMessage.data"
                        :key="String(key)"
                        class="flex items-start gap-3 px-3 py-2.5 text-sm"
                      >
                        <span class="text-gray-500 font-medium shrink-0 w-24 truncate">{{ key }}</span>
                        <span class="text-gray-700 break-all min-w-0 font-mono text-xs leading-5">
                          {{ typeof value === 'object' ? formatJson(value) : String(value) }}
                        </span>
                      </div>
                    </template>
                    <div v-else class="px-3 py-4 text-sm text-gray-400 text-center">
                      无数据
                    </div>
                  </div>

                  <div v-else class="p-3">
                    <pre class="text-xs text-gray-700 font-mono whitespace-pre-wrap break-all leading-5 max-h-96 overflow-auto">{{ formatJson(selectedMessage.data) }}</pre>
                  </div>
                </div>
              </div>
            </template>

            <!-- ====== List View ====== -->
            <template v-else>
              <!-- Loading -->
              <div
                v-if="loading && results.length === 0"
                class="flex flex-col items-center justify-center py-12 text-gray-400"
              >
                <div class="text-3xl mb-3">⏳</div>
                <div class="text-sm">搜索中...</div>
              </div>

              <!-- Empty state -->
              <div
                v-else-if="results.length === 0"
                class="flex flex-col items-center justify-center py-10 sm:py-12 text-gray-400"
              >
                <div class="text-3xl sm:text-4xl mb-2 sm:mb-3">📭</div>
                <div class="text-sm">没有匹配的消息</div>
                <div class="text-xs mt-1">尝试修改筛选条件或关键词</div>
              </div>

              <!-- Results list -->
              <template v-else>
                <!-- Mobile: card layout -->
                <div class="sm:hidden divide-y divide-gray-100">
                  <div
                    v-for="(m, index) in results"
                    :key="m.message_id || index"
                    class="px-3 py-3 active:bg-gray-50 cursor-pointer"
                    @click="viewMessage(m)"
                  >
                    <div class="flex items-start justify-between gap-2">
                      <div class="flex items-center gap-2 min-w-0 flex-1">
                        <span class="sender-name text-sm font-medium text-gray-700 truncate">
                          {{ getSenderLabel(m) }}
                        </span>
                        <span
                          class="type-badge inline-block px-1.5 py-0.5 rounded text-xs font-medium shrink-0"
                          :class="getTypeBadgeClass(m.message_type)"
                        >
                          {{ getTypeLabel(m.message_type) }}
                        </span>
                      </div>
                      <span class="text-xs text-gray-400 whitespace-nowrap shrink-0">
                        {{ formatBeijingTimeShort(m.timestamp) }}
                      </span>
                    </div>
                    <div class="mt-1.5 text-sm text-gray-600 line-clamp-2">
                      {{ getDataPreview(m) }}
                    </div>
                    <!-- 文件工具：展示文件路径 -->
                    <div v-if="isFileTool(m) && getFilePath(m)" class="text-xs text-blue-500 mt-1 font-mono truncate">
                      📁 {{ getFilePath(m) }}
                    </div>
                  </div>
                </div>

                <!-- Desktop: table layout -->
                <div class="hidden sm:block overflow-x-auto">
                  <table class="search-table w-full">
                    <thead class="sticky top-0 bg-gray-50 z-10">
                      <tr class="text-xs text-gray-500 uppercase tracking-wider">
                        <th class="px-4 py-2.5 text-left w-[120px]">发送者</th>
                        <th class="px-4 py-2.5 text-left w-[100px]">类型</th>
                        <th class="px-4 py-2.5 text-left min-w-[200px]">内容预览</th>
                        <th
                          class="px-4 py-2.5 text-right w-[130px] cursor-pointer select-none hover:text-gray-700 transition-colors"
                          @click="sortOrder = sortOrder === 'desc' ? 'asc' : 'desc'"
                        >
                          <span class="inline-flex items-center gap-1">
                            时间
                            <span class="text-xs">{{ sortOrder === 'desc' ? '↓' : '↑' }}</span>
                          </span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr
                        v-for="(m, index) in results"
                        :key="m.message_id || index"
                        class="search-row cursor-pointer"
                        @click="viewMessage(m)"
                      >
                        <td class="px-4 py-2.5">
                          <span class="sender-name text-sm font-medium text-gray-700">
                            {{ getSenderLabel(m) }}
                          </span>
                        </td>
                        <td class="px-4 py-2.5">
                          <span
                            class="type-badge inline-block px-2 py-0.5 rounded text-xs font-medium"
                            :class="getTypeBadgeClass(m.message_type)"
                          >
                            {{ getTypeLabel(m.message_type) }}
                          </span>
                        </td>
                        <td class="px-4 py-2.5">
                          <div class="data-preview text-sm text-gray-600 truncate max-w-md">
                            {{ getDataPreview(m) }}
                          </div>
                          <!-- 文件工具：展示文件路径 -->
                          <div v-if="isFileTool(m) && getFilePath(m)" class="text-xs text-blue-500 mt-0.5 font-mono truncate">
                            📁 {{ getFilePath(m) }}
                          </div>
                        </td>
                        <td class="px-4 py-2.5 text-right">
                          <span class="text-xs text-gray-400 whitespace-nowrap">
                            {{ formatBeijingTimeShort(m.timestamp) }}
                          </span>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </template>
            </template>
          </div>

          <!-- Footer: Pagination -->
          <div
            v-if="totalPages > 1"
            class="flex items-center justify-between px-3 sm:px-5 py-2.5 sm:py-3 border-t border-gray-200 bg-gray-50 gap-2"
          >
            <span class="text-xs text-gray-400 shrink-0">
              第 {{ currentPage }}/{{ totalPages }} 页
            </span>
            <el-pagination
              v-model:current-page="currentPage"
              :page-size="pageSize"
              :total="totalResults"
              layout="prev, pager, next"
              small
              background
              @current-change="handlePageChange"
            />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
/* ========== Overlay ========== */
.search-overlay {
  background-color: rgba(0, 0, 0, 0.35);
  backdrop-filter: blur(2px);
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

/* 移动端：弹框从底部滑入 */
@media (max-width: 639px) {
  .search-fade-enter-active .search-dialog,
  .search-fade-leave-active .search-dialog {
    transition: transform 0.25s ease;
  }
  .search-fade-enter-from .search-dialog,
  .search-fade-leave-to .search-dialog {
    transform: translateY(100%);
  }
}

/* ========== Search input ========== */
.search-input {
  --el-input-focus-border-color: #8b5cf6;
}

/* ========== Table styles ========== */
.search-table {
  border-collapse: separate;
  border-spacing: 0;
}

.search-table thead th {
  border-bottom: 1px solid #e5e7eb;
  font-weight: 600;
}

.search-row {
  transition: background-color 0.15s ease;
  border-bottom: 1px solid #f3f4f6;
}

.search-row:hover {
  background-color: #f5f3ff;
}

.search-row:last-child {
  border-bottom: none;
}

/* ========== Type badges ========== */
.type-badge {
  white-space: nowrap;
}

.type-badge.type-user {
  background-color: #dbeafe;
  color: #1d4ed8;
}

.type-badge.type-agent {
  background-color: #dcfce7;
  color: #15803d;
}

.type-badge.type-tool {
  background-color: #f3e8ff;
  color: #7c3aed;
}

.type-badge.type-error {
  background-color: #fee2e2;
  color: #dc2626;
}

.type-badge.type-system {
  background-color: #f3f4f6;
  color: #6b7280;
}

.type-badge.type-default {
  background-color: #f3f4f6;
  color: #4b5563;
}

/* ========== Sender name ========== */
.sender-name {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ========== Data preview ========== */
.data-preview {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.4;
}

/* ========== 移动端卡片 active 态 ========== */
@media (max-width: 639px) {
  .active\:bg-gray-50:active {
    background-color: #f9fafb;
  }
}
</style>