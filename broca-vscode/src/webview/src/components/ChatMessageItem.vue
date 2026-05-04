<script setup lang="ts">
import { ref, computed } from 'vue'
import type { Message } from '../types'

const props = defineProps<{
  message: Message
}>()

const showParameters = ref(false)
const showResult = ref(false)
const showReasoning = ref(false)

const isUser = computed(() => props.message.role === 'user')
const isSystem = computed(() => props.message.message_type === 'system_message')
const isToolCall = computed(() => props.message.message_type === 'tool_call')
const isAgentResponse = computed(() => props.message.message_type === 'agent_response')

const timestamp = computed(() => {
  const date = new Date(props.message.timestamp)
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
})

const agentResponseContent = computed(() => {
  if (!isAgentResponse.value || !props.message.data?.content) return ''
  try {
    const parsed = JSON.parse(props.message.data.content)
    return parsed.content || ''
  } catch {
    return props.message.data.content
  }
})

const agentReasoning = computed(() => {
  if (!isAgentResponse.value || !props.message.data?.content) return ''
  try {
    const parsed = JSON.parse(props.message.data.content)
    return parsed.reasoning_content || ''
  } catch {
    return ''
  }
})

const toolName = computed(() => props.message.data?.name || props.message.data?.tool_name || 'Tool')
const toolArgs = computed(() => {
  try {
    const args = props.message.data?.arguments || props.message.data?.args || {}
    return typeof args === 'string' ? JSON.parse(args) : args
  } catch {
    return props.message.data?.arguments || {}
  }
})
const toolResult = computed(() => {
  const result = props.message.data?.result
  if (!result) return ''
  if (typeof result === 'string') return result
  return JSON.stringify(result, null, 2)
})
</script>

<template>
  <div
    class="message-item"
    :class="{
      'message-user': isUser,
      'message-system': isSystem,
      'message-agent': !isUser && !isSystem,
      'message-tool': isToolCall,
    }"
  >
    <!-- User message -->
    <template v-if="isUser">
      <div class="message-header">
        <span class="sender-name">You</span>
        <span class="message-time">{{ timestamp }}</span>
      </div>
      <div class="message-content">{{ message.data?.content }}</div>
      <!-- File attachments -->
      <div v-if="message.data?.files" class="file-attachments">
        <div v-for="file in message.data.files" :key="file.url" class="file-attachment">
          <a :href="file.url" target="_blank" rel="noopener">{{ file.name }}</a>
        </div>
      </div>
    </template>

    <!-- System message -->
    <template v-else-if="isSystem">
      <div class="system-content">
        {{ message.data?.content }}
      </div>
    </template>

    <!-- Tool call -->
    <template v-else-if="isToolCall">
      <div class="tool-call-header" @click="showParameters = !showParameters">
        <span class="tool-icon">🔧</span>
        <span class="tool-name">{{ toolName }}</span>
        <span class="expand-icon">{{ showParameters ? '▼' : '▶' }}</span>
      </div>
      <div v-if="showParameters && Object.keys(toolArgs).length > 0" class="tool-args">
        <pre>{{ JSON.stringify(toolArgs, null, 2) }}</pre>
      </div>
      <div v-if="toolResult" class="tool-result-header" @click="showResult = !showResult">
        <span>📊 Result</span>
        <span class="expand-icon">{{ showResult ? '▼' : '▶' }}</span>
      </div>
      <div v-if="showResult && toolResult" class="tool-result">
        <pre>{{ toolResult }}</pre>
      </div>
    </template>

    <!-- Agent response -->
    <template v-else>
      <div class="message-header">
        <span class="sender-name">{{ message.sender_id || 'Assistant' }}</span>
        <span class="message-time">{{ timestamp }}</span>
      </div>

      <!-- Reasoning -->
      <div v-if="agentReasoning" class="reasoning-section">
        <div class="reasoning-header" @click="showReasoning = !showReasoning">
          <span>🧠 Reasoning</span>
          <span class="expand-icon">{{ showReasoning ? '▼' : '▶' }}</span>
        </div>
        <div v-if="showReasoning" class="reasoning-content">
          {{ agentReasoning }}
        </div>
      </div>

      <!-- Content -->
      <div class="message-content markdown-body">
        {{ agentResponseContent }}
      </div>
    </template>
  </div>
</template>

<style scoped>
.message-item {
  padding: 8px 12px;
  border-radius: 6px;
  margin-bottom: 4px;
  font-size: 13px;
  line-height: 1.5;
}

.message-user {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
}

.message-agent {
  background: transparent;
}

.message-system {
  text-align: center;
}

.message-tool {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  font-size: 12px;
}

.message-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.sender-name {
  font-weight: 600;
  color: var(--text-link);
  font-size: 12px;
}

.message-time {
  font-size: 11px;
  color: var(--text-secondary);
}

.message-content {
  word-break: break-word;
  color: var(--text-primary);
}

.system-content {
  color: var(--text-secondary);
  font-style: italic;
  font-size: 12px;
  padding: 4px 0;
}

/* Tool call */
.tool-call-header {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  padding: 4px 0;
}

.tool-icon {
  font-size: 14px;
}

.tool-name {
  font-weight: 500;
  color: var(--warning-fg);
}

.expand-icon {
  font-size: 10px;
  color: var(--text-secondary);
}

.tool-args,
.tool-result {
  margin-top: 4px;
  padding: 6px 8px;
  background: var(--bg-tertiary);
  border-radius: 4px;
  overflow-x: auto;
}

.tool-result-header {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  margin-top: 4px;
  padding: 4px 0;
  font-size: 12px;
}

pre {
  margin: 0;
  font-family: var(--code-font-family);
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-all;
}

/* Reasoning */
.reasoning-section {
  margin-bottom: 8px;
}

.reasoning-header {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  padding: 4px 0;
  font-size: 12px;
  color: var(--text-secondary);
}

.reasoning-content {
  padding: 8px;
  background: var(--bg-tertiary);
  border-radius: 4px;
  border-left: 3px solid var(--warning-fg);
  font-size: 12px;
  color: var(--text-secondary);
  font-style: italic;
}

/* File attachments */
.file-attachments {
  margin-top: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.file-attachment {
  padding: 2px 8px;
  background: var(--bg-tertiary);
  border-radius: 4px;
  font-size: 11px;
}

.file-attachment a {
  color: var(--text-link);
  text-decoration: none;
}

.file-attachment a:hover {
  text-decoration: underline;
}
</style>
