<script setup lang="ts">
import { ref, computed } from 'vue'
import { ArrowRight } from '@element-plus/icons-vue'
import { useChatStore } from '@/stores'

const chatStore = useChatStore()
const customAnswer = ref('')

const hasOptions = computed(() => {
  return chatStore.agentQueryDialog.options && chatStore.agentQueryDialog.options.length > 0
})

const submitAnswer = (answer: string) => {
  if (!answer.trim()) return
  customAnswer.value = ''
  chatStore.respondUserAnswer(answer)
}

const handleSubmit = () => {
  if (customAnswer.value.trim()) {
    submitAnswer(customAnswer.value)
  }
}

const selectOption = (optionName: string) => {
  submitAnswer(optionName)
}
</script>

<template>
  <el-dialog
    v-model="chatStore.agentQueryDialog.visible"
    title="Question"
    :width="chatStore.isMobile ? '90%' : '520px'"
    :close-on-click-modal="false"
    class="agent-query-dialog"
    @close="submitAnswer('')"
  >
    <div class="flex items-start gap-3" :class="{ 'gap-2': chatStore.isMobile }">
      <div class="text-3xl" :class="{ 'text-2xl': chatStore.isMobile }">❓</div>
      <div
        class="text-sm whitespace-pre-wrap flex-1 leading-relaxed question-text"
        :class="{ 'text-base': chatStore.isMobile }"
      >
        {{ chatStore.agentQueryDialog.question }}
      </div>
    </div>

    <div v-if="hasOptions" class="mt-5" :class="chatStore.isMobile ? 'pl-0' : 'pl-11'">
      <div class="text-sm mb-3 options-label" :class="{ 'mb-2': chatStore.isMobile }">Options:</div>
      <div class="flex flex-col gap-2 sm:gap-3">
        <div
          v-for="option in chatStore.agentQueryDialog.options"
          :key="option.name"
          class="option-card"
          @click="selectOption(option.name)"
        >
          <div class="option-name">
            {{ option.name }}
          </div>
          <div v-if="option.description" class="option-desc">
            {{ option.description }}
          </div>
          <el-icon class="option-arrow">
            <ArrowRight />
          </el-icon>
        </div>
      </div>
    </div>

    <div class="mt-5" :class="chatStore.isMobile ? 'pl-0' : 'pl-11'">
      <div class="text-sm mb-2 answer-label">
        {{ hasOptions ? 'Or enter your own answer:' : 'Enter your answer:' }}
      </div>
      <el-input
        v-model="customAnswer"
        type="textarea"
        :rows="chatStore.isMobile ? 2 : 3"
        placeholder="Type your answer here..."
        @keydown.enter.ctrl="handleSubmit"
      />
    </div>

    <template #footer>
      <div class="flex justify-end gap-2">
        <el-button @click="submitAnswer('')"> Cancel </el-button>
        <el-button :disabled="!customAnswer.trim()" type="primary" @click="handleSubmit"> Submit </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.option-card {
  @apply flex items-center justify-between p-3 sm:p-4 rounded-lg border border-gray-200 bg-white cursor-pointer;
  @apply transition-all duration-200 hover:border-primary-300 hover:shadow-sm hover:bg-primary-50/50;
  min-height: 52px;
}

.option-name {
  @apply font-medium text-gray-800 text-sm sm:text-base;
}

.option-desc {
  @apply text-gray-500 text-xs sm:text-sm mt-0.5;
}

.option-arrow {
  @apply text-gray-300 flex-shrink-0 ml-2 transition-transform duration-200;
}

.option-card:hover .option-arrow {
  @apply text-primary-500 transform translate-x-1;
}

@media (max-width: 640px) {
  .option-card {
    @apply p-3;
  }

  .option-name {
    @apply text-sm;
  }

  .option-desc {
    @apply text-xs;
  }
}

/* ========== 暗色模式 ========== */
@media (prefers-color-scheme: dark) {
  :deep(.el-dialog__title) {
    color: #1a1a2e;
    font-weight: 600;
  }

  .question-text {
    color: #4a4a6a;
  }

  .options-label,
  .answer-label {
    color: #888;
  }

  .option-card {
    background: #f0f2f5;
    border-color: #d9dce0;
  }

  .option-card:hover {
    background: #e4e7ed;
    border-color: var(--color-primary-400);
  }

  .option-name {
    color: #333;
  }

  .option-desc {
    color: #888;
  }

  .option-arrow {
    color: #aaa;
  }

  .option-card:hover .option-arrow {
    color: var(--color-primary-400);
  }
}
</style>
