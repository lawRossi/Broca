<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { postMessage, onMessage, getInitialData } from './api/vscode'
import type { CrewExecution, PhaseResult, ExecutionStatus, CrewConfigFile } from './types'

// ==================== Init ====================
const initData = getInitialData()
const sessionId = initData?.sessionId || ''

// ==================== State ====================
const activeTab = ref<'executions' | 'configs'>('executions')
const executions = ref<CrewExecution[]>([])
const loading = ref(false)
const statusFilter = ref('')

// Detail view
const selectedExecution = ref<CrewExecution | null>(null)
const detailLoading = ref(false)

// Config files
const configFiles = ref<CrewConfigFile[]>([])
const configFilesLoading = ref(false)

function isConfigExecuting(cfg: CrewConfigFile): boolean {
  // Check if there's a pending/running execution with the same crew name
  return executions.value.some(e => e.crew_name === cfg.name && (e.status === 'pending' || e.status === 'running'))
}

// ==================== Status helpers ====================
const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '待执行', value: 'pending' },
  { label: '运行中', value: 'running' },
  { label: '已完成', value: 'completed' },
  { label: '已失败', value: 'failed' },
  { label: '已中止', value: 'aborted' },
]

const statusLabels: Record<string, string> = {
  pending: '待执行',
  running: '运行中',
  completed: '已完成',
  failed: '已失败',
  aborted: '已中止',
}

const orchestratorLabels: Record<string, string> = {
  pipeline: '流水线',
  'supervisor-worker': '主管-工人',
  'round-table': '圆桌讨论',
  broadcast: '广播分发',
  consensus: '共识评估',
  composite: '组合嵌套',
}

function statusClass(status: string): string {
  switch (status) {
    case 'running': return 'status-running'
    case 'completed': return 'status-completed'
    case 'failed': return 'status-failed'
    case 'aborted': return 'status-aborted'
    default: return 'status-pending'
  }
}

function phaseStatusIcon(status: string): string {
  switch (status) {
    case 'completed': return '✓'
    case 'running': return '⟳'
    case 'failed': return '✕'
    default: return '○'
  }
}

function phaseStatusClass(status: string): string {
  switch (status) {
    case 'completed': return 'phase-completed'
    case 'running': return 'phase-running'
    case 'failed': return 'phase-failed'
    default: return 'phase-pending'
  }
}

function formatTime(timeStr?: string): string {
  if (!timeStr) return '-'
  const d = new Date(timeStr)
  return d.toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function getDuration(exec: CrewExecution): string {
  if (!exec.completed_at || !exec.created_at) return '-'
  const start = new Date(exec.created_at).getTime()
  const end = new Date(exec.completed_at).getTime()
  const seconds = Math.round((end - start) / 1000)
  if (seconds < 60) return `${seconds}s`
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
}

// ==================== Actions ====================
function fetchExecutions() {
  loading.value = true
  const params: any = { session_id: sessionId }
  if (statusFilter.value) {
    params.status = statusFilter.value
  }
  postMessage({ type: 'fetchCrewExecutions', payload: params })
}

function viewDetail(exec: CrewExecution) {
  selectedExecution.value = exec
  detailLoading.value = true
  postMessage({ type: 'fetchCrewDetail', payload: { executionId: exec.execution_id } })
}

function backToList() {
  selectedExecution.value = null
}

// ==================== Config Files ====================
function fetchConfigFiles() {
  configFilesLoading.value = true
  postMessage({ type: 'fetchCrewConfigs', payload: { session_id: sessionId } })
}

function submitConfigFile(cfg: CrewConfigFile) {
  if (isConfigExecuting(cfg)) return
  postMessage({ type: 'submitCrew', payload: { yaml_path: cfg.path, session_id: sessionId } })
}

function abortCrew(executionId: string) {
  postMessage({ type: 'confirmAction', payload: { action: 'abortCrew', executionId, message: '确定要中止此编排吗？' } })
}

function deleteCrew(executionId: string) {
  postMessage({ type: 'confirmAction', payload: { action: 'deleteCrew', executionId, message: '确定要删除此编排记录吗？' } })
}

function viewChatLog(exec: CrewExecution) {
  postMessage({ type: 'openChat', payload: { sessionId: exec.session_id, executionId: exec.execution_id } })
}

function openCrewFile(exec: CrewExecution) {
  postMessage({ type: 'openCrewConfigFile', payload: { sessionId: exec.session_id, crewName: exec.crew_name } })
}

function openCrewConfigFile(cfg: CrewConfigFile) {
  postMessage({ type: 'openCrewConfigFile', payload: { sessionId: sessionId, crewName: cfg.name } })
}

// ==================== Message handling ====================
let unsub: (() => void) | null = null

onMounted(() => {
  fetchExecutions()

  unsub = onMessage((data: any) => {
    switch (data.type) {
      case 'crewExecutions':
        executions.value = data.payload.executions || []
        loading.value = false
        break

      case 'crewConfigs':
        configFiles.value = data.payload.configs || []
        configFilesLoading.value = false
        break

      case 'crewDetail':
        if (selectedExecution.value) {
          selectedExecution.value = { ...selectedExecution.value, ...data.payload }
        }
        detailLoading.value = false
        break

      case 'crewEvent':
        // Update execution in list
        const event = data.payload
        if (event.execution_id) {
          const idx = executions.value.findIndex(e => e.execution_id === event.execution_id)
          if (idx >= 0) {
            if (event.event === 'deleted') {
              // Remove from list immediately
              executions.value.splice(idx, 1)
              executions.value = [...executions.value]
            } else if (event.status) {
              // Update status and phases immediately (no need to wait for refresh)
              executions.value[idx] = { ...executions.value[idx], ...event }
              executions.value = [...executions.value]
            } else {
              fetchExecutions()
            }
          }
        }
        // Update detail if viewing
        if (selectedExecution.value && event.execution_id === selectedExecution.value.execution_id) {
          if (event.phases || event.status) {
            selectedExecution.value = { ...selectedExecution.value, ...event }
          } else {
            // Refetch detail
            postMessage({ type: 'fetchCrewDetail', payload: { executionId: event.execution_id } })
          }
        }
        break

      case 'error':
        loading.value = false
        detailLoading.value = false
        configFilesLoading.value = false
        console.error('[CrewPanel] Error:', data.payload?.message)
        break
    }
  })
})

onUnmounted(() => {
  if (unsub) unsub()
})
</script>

<template>
  <div class="crew-container">
    <!-- Tab Bar -->
    <div class="crew-tab-bar">
      <button
        :class="['crew-tab', { active: activeTab === 'executions' }]"
        @click="activeTab = 'executions'"
      >执行记录</button>
      <button
        :class="['crew-tab', { active: activeTab === 'configs' }]"
        @click="fetchConfigFiles(); activeTab = 'configs'"
      >已有编排</button>
    </div>

    <!-- ==================== List View (Executions) ==================== -->
    <div v-if="activeTab === 'executions' && !selectedExecution" class="crew-list-view">
      <!-- Header -->
      <div class="crew-header">
        <h1 class="crew-title">⚡ 编排管理</h1>
        <div class="crew-header-actions">
          <button class="btn btn-secondary" @click="fetchExecutions" :disabled="loading">
            {{ loading ? '⟳' : '🔄' }} 刷新
          </button>
        </div>
      </div>

      <!-- Filter bar -->
      <div class="crew-filter-bar">
        <select v-model="statusFilter" class="filter-select" @change="fetchExecutions">
          <option v-for="opt in statusOptions" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </option>
        </select>
        <span class="filter-count">共 {{ executions.length }} 条记录</span>
      </div>

      <!-- Execution list -->
      <div v-if="loading && !executions.length" class="crew-loading">
        加载中...
      </div>

      <div v-else-if="!executions.length" class="crew-empty">
        <p>暂无编排执行记录</p>
        <p class="crew-empty-hint">提交编排 YAML 配置以开始执行</p>
      </div>

      <div v-else class="crew-list">
        <div v-for="exec in executions" :key="exec.execution_id" class="crew-card" @click="viewDetail(exec)">
          <div class="crew-card-header">
            <div class="crew-card-title-row">
              <span :class="['crew-status-badge', statusClass(exec.status)]">
                {{ statusLabels[exec.status] || exec.status }}
              </span>
              <span class="crew-card-name">{{ exec.crew_name }}</span>
              <span class="crew-card-type" v-if="exec.orchestrator_type">
                {{ orchestratorLabels[exec.orchestrator_type] || exec.orchestrator_type }}
              </span>
            </div>
            <span class="crew-card-id">{{ exec.execution_id.slice(0, 12) }}...</span>
          </div>

          <p class="crew-card-desc">{{ exec.description || '无描述' }}</p>

          <div class="crew-card-meta">
            <span>Agent: {{ exec.agent_count }} 个</span>
            <span v-if="exec.phases">阶段: {{ exec.phases.length }}/{{ exec.phases_total || exec.phases.length }}</span>
            <span>{{ formatTime(exec.created_at) }}</span>
          </div>

          <!-- Progress bar -->
          <div v-if="exec.progress !== undefined" class="crew-progress-bar-container">
            <div
              class="crew-progress-bar"
              :class="exec.status === 'failed' ? 'progress-failed' : exec.status === 'completed' ? 'progress-completed' : ''"
              :style="{ width: Math.round(exec.progress * 100) + '%' }"
            ></div>
            <span class="crew-progress-text">{{ Math.round(exec.progress * 100) }}%</span>
          </div>

          <!-- Action buttons -->
          <div class="crew-card-actions">
            <button class="btn btn-secondary btn-sm" @click.stop="viewChatLog(exec)">查看聊天日志</button>
            <button v-if="exec.status === 'running'" class="btn btn-danger btn-sm" @click.stop="abortCrew(exec.execution_id)">中止</button>
            <button class="btn btn-danger btn-sm" @click.stop="deleteCrew(exec.execution_id)">删除</button>
          </div>
        </div>
      </div>
    </div>

    <!-- ==================== Configs Tab ==================== -->
    <div v-else-if="activeTab === 'configs'" class="crew-list-view">
      <div class="crew-header">
        <h1 class="crew-title">📄 已有编排</h1>
        <div class="crew-header-actions">
          <button class="btn btn-secondary" @click="fetchConfigFiles" :disabled="configFilesLoading">
            {{ configFilesLoading ? '⟳' : '🔄' }} 刷新
          </button>
        </div>
      </div>

      <div class="crew-filter-bar">
        <span class="filter-count">{{ configFiles.length }} 个配置文件</span>
      </div>

      <div v-if="configFilesLoading && !configFiles.length" class="crew-loading">
        加载中...
      </div>

      <div v-else-if="!configFiles.length" class="crew-empty">
        <p>该工作空间下没有编排配置文件</p>
        <p class="crew-empty-hint">请在 workspace 的 crew_configs/ 目录下创建 .yaml 文件</p>
      </div>

      <div v-else class="crew-list">
        <div v-for="cfg in configFiles" :key="cfg.filename" class="crew-card" @click="openCrewConfigFile(cfg)">
          <div class="crew-card-header">
            <div class="crew-card-title-row">
              <span class="crew-card-name">{{ cfg.name }}</span>
              <span v-if="cfg.orchestrator_type" class="crew-card-type">
                {{ orchestratorLabels[cfg.orchestrator_type] || cfg.orchestrator_type }}
              </span>
              <span v-if="cfg.parse_error" class="crew-status-badge status-failed">解析失败</span>
            </div>
            <span class="crew-card-id">{{ cfg.filename }}</span>
          </div>

          <p class="crew-card-desc">{{ cfg.description || '无描述' }}</p>

          <div class="crew-card-meta">
            <span>Agent: {{ cfg.agent_count }} 个</span>
            <span v-if="cfg.agent_names.length">({{ cfg.agent_names.join(', ') }})</span>
            <span>{{ new Date(cfg.modified_time * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) }}</span>
          </div>

          <div class="crew-card-actions" style="margin-top: 8px;">
            <button
              class="btn btn-primary"
              :disabled="isConfigExecuting(cfg)"
              @click.stop="submitConfigFile(cfg)"
            >
              {{ isConfigExecuting(cfg) ? '执行中...' : '执行' }}
            </button>
            <span v-if="cfg.parse_error" class="crew-status-badge status-failed">解析失败</span>
          </div>
        </div>
      </div>
    </div>

    <!-- ==================== Detail / DAG View (from either tab) ==================== -->
    <div v-else-if="selectedExecution" class="crew-detail-view">
      <!-- Detail header -->
      <div class="crew-detail-header">
        <button class="btn btn-secondary" @click="backToList">← 返回</button>
        <h2 class="crew-detail-title">{{ selectedExecution.crew_name }}</h2>
      </div>

      <!-- Summary -->
      <div class="crew-detail-summary">
        <div class="crew-detail-summary-row">
          <span :class="['crew-status-badge', statusClass(selectedExecution.status)]">
            {{ statusLabels[selectedExecution.status] || selectedExecution.status }}
          </span>
          <span class="crew-detail-label" v-if="selectedExecution.orchestrator_type">
            拓扑: {{ orchestratorLabels[selectedExecution.orchestrator_type] || selectedExecution.orchestrator_type }}
          </span>
          <span class="crew-detail-label">Agent: {{ selectedExecution.agent_count }} 个</span>
        </div>

        <!-- Progress -->
        <div class="crew-detail-progress-row">
          <div class="crew-progress-bar-container detail-progress">
            <div
              class="crew-progress-bar"
              :class="selectedExecution.status === 'failed' ? 'progress-failed' : selectedExecution.status === 'completed' ? 'progress-completed' : ''"
              :style="{ width: Math.round((selectedExecution.progress || 0) * 100) + '%' }"
            ></div>
            <span class="crew-progress-text">{{ Math.round((selectedExecution.progress || 0) * 100) }}%</span>
          </div>
            <span v-if="selectedExecution.completed_at" class="crew-detail-duration">
              耗时: {{ getDuration(selectedExecution) }}
            </span>
        </div>
      </div>

      <!-- DAG: Phase List -->
      <div class="crew-dag">
        <div v-if="!detailLoading && (!selectedExecution.phases || !selectedExecution.phases.length)" class="crew-empty">
          <p>暂无阶段信息</p>
        </div>

        <div v-else class="crew-dag-list">
          <!-- Connection line -->
          <div v-if="(selectedExecution.phases?.length || 0) > 1" class="crew-dag-line"></div>

          <div
            v-for="(phase, index) in selectedExecution.phases"
            :key="phase.name"
            class="crew-dag-node"
          >
            <div class="crew-dag-dot">
              <div :class="['crew-dag-dot-inner', phaseStatusClass(phase.status)]"></div>
            </div>
            <div :class="['crew-dag-card', phaseStatusClass(phase.status)]">
              <div class="crew-dag-card-header">
                <span class="crew-dag-phase-name">{{ phase.name }}</span>
                <span :class="['crew-dag-phase-status', phaseStatusClass(phase.status)]">
                  {{ phaseStatusIcon(phase.status) }} {{ phase.status }}
                </span>
              </div>
              <div v-if="phase.agents && phase.agents.length" class="crew-dag-agents">
                <span v-for="agent in phase.agents" :key="agent" class="crew-dag-agent-tag">
                  {{ agent }}
                </span>
              </div>
              <div v-if="phase.error" class="crew-dag-error">
                {{ phase.error }}
              </div>
              <div class="crew-dag-step-num">步骤 {{ index + 1 }} / {{ selectedExecution.phases_total || selectedExecution.phases?.length }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Result -->
      <div v-if="selectedExecution.result" class="crew-detail-result">
        <h3 class="crew-detail-section-title">执行结果</h3>
        <pre class="crew-result-json">{{ JSON.stringify(selectedExecution.result, null, 2) }}</pre>
      </div>

      <!-- Action buttons -->
      <div class="crew-detail-actions">
        <button class="btn btn-primary" @click="viewChatLog(selectedExecution!)">
          查看聊天日志
        </button>
        <button
          v-if="selectedExecution.status === 'running'"
          class="btn btn-danger"
          @click="abortCrew(selectedExecution.execution_id)"
        >
          中止
        </button>
        <button class="btn btn-danger" @click="deleteCrew(selectedExecution.execution_id)">
          删除
        </button>
      </div>
    </div>
  </div>
</template>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body {
  height: 100%;
  overflow: hidden;
  font-family: var(--font-family, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif);
  font-size: var(--font-size, 13px);
  background-color: var(--bg-primary, #1e1e1e);
  color: var(--text-primary, #cccccc);
}

#app {
  height: 100%;
}

.crew-container {
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ==================== Tab Bar ==================== */
.crew-tab-bar {
  display: flex;
  border-bottom: 1px solid var(--border-color, #333);
  background: var(--bg-secondary, #252526);
  flex-shrink: 0;
}

.crew-tab {
  padding: 8px 20px;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-secondary, #888);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: color 0.2s, border-color 0.2s;
}

.crew-tab:hover {
  color: var(--text-primary, #ccc);
}

.crew-tab.active {
  color: var(--vscode-focusBorder, #007fd4);
  border-bottom-color: var(--vscode-focusBorder, #007fd4);
}

/* ==================== List View ==================== */
.crew-list-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.crew-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color, #333);
  flex-shrink: 0;
}

.crew-title {
  font-size: 16px;
  font-weight: 600;
}

.crew-header-actions {
  display: flex;
  gap: 8px;
}

.crew-filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 16px;
  border-bottom: 1px solid var(--border-color, #333);
  background: var(--bg-secondary, #252526);
  flex-shrink: 0;
}

.filter-select {
  padding: 4px 8px;
  background: var(--vscode-dropdown-background, #3c3c3c);
  color: var(--vscode-dropdown-foreground, #cccccc);
  border: 1px solid var(--vscode-dropdown-border, #555);
  border-radius: 4px;
  font-size: 12px;
}

.filter-count {
  font-size: 11px;
  color: var(--text-secondary, #888);
}

.crew-list {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
}

.crew-card {
  padding: 12px 16px;
  margin-bottom: 8px;
  border: 1px solid var(--border-color, #333);
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
  background: var(--bg-secondary, #252526);
}

.crew-card:hover {
  border-color: var(--vscode-focusBorder, #007fd4);
  background: var(--vscode-list-hoverBackground, #2a2d2e);
}

.crew-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.crew-card-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.crew-card-name {
  font-weight: 600;
  font-size: 14px;
}

.crew-card-type {
  font-size: 11px;
  padding: 1px 6px;
  border: 1px solid var(--border-color, #555);
  border-radius: 3px;
  color: var(--text-secondary, #888);
}

.crew-card-id {
  font-size: 10px;
  font-family: monospace;
  color: var(--text-secondary, #555);
}

.crew-card-desc {
  font-size: 12px;
  color: var(--text-secondary, #888);
  margin-bottom: 8px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.crew-card-meta {
  display: flex;
  gap: 16px;
  font-size: 11px;
  color: var(--text-secondary, #888);
  margin-bottom: 8px;
}

.crew-card-actions {
  display: flex;
  gap: 6px;
  padding-top: 8px;
  border-top: 1px solid var(--border-color, #333);
}

/* ==================== Status Badges ==================== */
.crew-status-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
}

.status-pending { background: #555; color: #ccc; }
.status-running { background: #005fb8; color: #fff; }
.status-completed { background: #0d7a3f; color: #fff; }
.status-failed { background: #a12622; color: #fff; }
.status-aborted { background: #b89500; color: #000; }

/* ==================== Progress Bar ==================== */
.crew-progress-bar-container {
  position: relative;
  height: 6px;
  background: var(--bg-tertiary, #333);
  border-radius: 3px;
  overflow: hidden;
}

.crew-progress-bar {
  height: 100%;
  background: var(--vscode-focusBorder, #007fd4);
  border-radius: 3px;
  transition: width 0.3s ease;
}

.crew-progress-bar.progress-completed {
  background: #0d7a3f;
}

.crew-progress-bar.progress-failed {
  background: #a12622;
}

.crew-progress-text {
  position: absolute;
  right: 4px;
  top: -14px;
  font-size: 10px;
  color: var(--text-secondary, #888);
}

/* ==================== Detail View ==================== */
.crew-detail-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.crew-detail-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color, #333);
  flex-shrink: 0;
}

.crew-detail-title {
  font-size: 16px;
  font-weight: 600;
}

.crew-detail-summary {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color, #333);
  background: var(--bg-secondary, #252526);
  flex-shrink: 0;
}

.crew-detail-summary-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.crew-detail-label {
  font-size: 12px;
  color: var(--text-secondary, #888);
}

.crew-detail-progress-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.detail-progress {
  flex: 1;
}

.crew-detail-duration {
  font-size: 11px;
  color: var(--text-secondary, #888);
  white-space: nowrap;
}

/* ==================== DAG View ==================== */
.crew-dag {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.crew-dag-list {
  position: relative;
}

.crew-dag-line {
  position: absolute;
  left: 12px;
  top: 0;
  bottom: 0;
  width: 2px;
  background: var(--border-color, #444);
}

.crew-dag-node {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
  position: relative;
}

.crew-dag-dot {
  position: relative;
  z-index: 1;
  width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.crew-dag-dot-inner {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 2px solid var(--border-color, #555);
}

.crew-dag-dot-inner.phase-completed { background: #0d7a3f; border-color: #0d7a3f; }
.crew-dag-dot-inner.phase-running { background: #005fb8; border-color: #005fb8; }
.crew-dag-dot-inner.phase-failed { background: #a12622; border-color: #a12622; }
.crew-dag-dot-inner.phase-pending { background: transparent; border-color: #555; }

.crew-dag-card {
  flex: 1;
  padding: 10px 14px;
  border: 1px solid var(--border-color, #333);
  border-radius: 6px;
  background: var(--bg-secondary, #252526);
}

.crew-dag-card.phase-completed { border-color: #0d7a3f44; background: #0d7a3f11; }
.crew-dag-card.phase-running { border-color: #005fb844; background: #005fb811; }
.crew-dag-card.phase-failed { border-color: #a1262244; background: #a1262211; }

.crew-dag-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.crew-dag-phase-name {
  font-weight: 600;
  font-size: 13px;
}

.crew-dag-phase-status {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 3px;
}

.crew-dag-phase-status.phase-completed { color: #0d7a3f; }
.crew-dag-phase-status.phase-running { color: #005fb8; }
.crew-dag-phase-status.phase-failed { color: #a12622; }
.crew-dag-phase-status.phase-pending { color: #888; }

.crew-dag-agents {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 4px;
}

.crew-dag-agent-tag {
  display: inline-block;
  padding: 1px 6px;
  font-size: 10px;
  border: 1px solid var(--border-color, #555);
  border-radius: 3px;
  color: var(--text-secondary, #aaa);
}

.crew-dag-error {
  padding: 4px 8px;
  margin-bottom: 4px;
  font-size: 11px;
  color: #f48771;
  background: #a1262211;
  border-radius: 4px;
}

.crew-dag-step-num {
  font-size: 10px;
  color: var(--text-secondary, #666);
}

/* ==================== Result ==================== */
.crew-detail-result {
  padding: 12px 16px;
  border-top: 1px solid var(--border-color, #333);
  flex-shrink: 0;
  max-height: 200px;
  overflow: auto;
}

.crew-detail-section-title {
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--text-secondary, #888);
}

/* ==================== Result ==================== */
.crew-result-json {
  padding: 8px 10px;
  font-size: 11px;
  font-family: monospace;
  white-space: pre-wrap;
  color: var(--text-primary, #ccc);
  margin: 0;
  max-height: 200px;
  overflow: auto;
  background: var(--bg-tertiary, #1a1a1a);
  border-radius: 4px;
}

/* ==================== Action Buttons ==================== */
.crew-detail-actions {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--border-color, #333);
  flex-shrink: 0;
}

/* ==================== Shared Components ==================== */
.btn {
  padding: 6px 14px;
  border: none;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
  font-weight: 500;
  white-space: nowrap;
}

.btn-sm {
  padding: 3px 10px;
  font-size: 11px;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  background: var(--vscode-button-background, #007acc);
  color: var(--vscode-button-foreground, #fff);
}

.btn-primary:hover:not(:disabled) {
  background: var(--vscode-button-hoverBackground, #005a9e);
}

.btn-secondary {
  background: var(--vscode-button-secondaryBackground, #3a3d41);
  color: var(--vscode-button-secondaryForeground, #ccc);
}

.btn-secondary:hover:not(:disabled) {
  background: var(--vscode-button-secondaryHoverBackground, #45494e);
}

.btn-danger {
  background: #a12622;
  color: #fff;
}

.btn-danger:hover:not(:disabled) {
  background: #c53030;
}

.crew-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 200px;
  color: var(--text-secondary, #888);
}

.crew-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 16px;
  color: var(--text-secondary, #888);
}

.crew-empty-hint {
  font-size: 12px;
  margin-top: 8px;
  color: var(--text-secondary, #666);
}
</style>
