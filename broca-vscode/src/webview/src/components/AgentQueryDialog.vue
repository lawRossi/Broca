<script setup lang="ts">
import { ref } from 'vue'
import { useChatStore } from '../stores/chat'

const chatStore = useChatStore()
const answer = ref('')
const selectedOption = ref('')

function handleSelectOption(option: string) {
  chatStore.respondAgentQuery(option)
}

function handleSubmit() {
  if (answer.value.trim()) {
    chatStore.respondAgentQuery(answer.value.trim())
  }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="chatStore.agentQueryDialog.visible" class="dialog-overlay">
      <div class="dialog-container">
        <div class="dialog-header">
          <span class="dialog-icon">❓</span>
          <span class="dialog-title">Agent Question</span>
        </div>
        <div class="dialog-body">
          <p class="question">{{ chatStore.agentQueryDialog.question }}</p>

          <!-- Options (if provided) -->
          <div v-if="chatStore.agentQueryDialog.options.length > 0" class="options">
            <button
              v-for="opt in chatStore.agentQueryDialog.options"
              :key="opt.name"
              class="option-button"
              @click="handleSelectOption(opt.name)"
            >
              <span class="option-name">{{ opt.name }}</span>
              <span v-if="opt.description" class="option-desc">{{ opt.description }}</span>
            </button>
          </div>

          <!-- Free text input (if no options) -->
          <div v-else class="text-input-area">
            <textarea
              v-model="answer"
              class="answer-input"
              placeholder="Type your answer..."
              rows="3"
            ></textarea>
            <button class="btn btn-primary" @click="handleSubmit">Submit</button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.dialog-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.dialog-container {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 20px;
  min-width: 320px;
  max-width: 500px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

.dialog-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.dialog-icon { font-size: 20px; }

.dialog-title {
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary);
}

.dialog-body {
  margin-bottom: 8px;
}

.question {
  font-size: 14px;
  color: var(--text-primary);
  line-height: 1.5;
  margin-bottom: 16px;
}

.options {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.option-button {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 10px 14px;
  cursor: pointer;
  text-align: left;
  width: 100%;
}

.option-button:hover {
  border-color: var(--focus-border);
  background: var(--input-bg);
}

.option-name {
  font-weight: 500;
  font-size: 13px;
  color: var(--text-primary);
}

.option-desc {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 2px;
}

.text-input-area {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.answer-input {
  background: var(--input-bg);
  color: var(--input-text);
  border: 1px solid var(--input-border);
  border-radius: 4px;
  padding: 8px 12px;
  font-family: var(--font-family);
  font-size: 13px;
  resize: vertical;
  outline: none;
  width: 100%;
}

.answer-input:focus {
  border-color: var(--focus-border);
}

.btn {
  border: none;
  border-radius: 4px;
  padding: 8px 16px;
  font-size: 13px;
  cursor: pointer;
  font-weight: 500;
  align-self: flex-end;
}

.btn-primary {
  background: var(--button-bg);
  color: var(--button-text);
}

.btn-primary:hover {
  background: var(--button-hover-bg);
}
</style>
