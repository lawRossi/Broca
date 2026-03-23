<script setup lang="ts">
import { computed } from 'vue'
import { FolderOpened } from '@element-plus/icons-vue'
import type { CreateSessionParams } from '@/api/session'

// LLM Provider 选项（与后端 llm_config.json 保持一致）
const LLM_PROVIDERS = [
  { label: 'OpenRouter', value: 'openrouter' },
  { label: 'DeepSeek', value: 'deepseek' },
  { label: 'NVIDIA', value: 'nvidia' },
  { label: 'Z-AI', value: 'z-ai' }
]

interface Props {
  visible: boolean
  formData: CreateSessionParams
  workspaceSuggestions: string[]
  availableModels: { label: string; value: string }[]
  creating: boolean
}

interface Emits {
  (e: 'update:visible', value: boolean): void
  (e: 'update:formData', value: CreateSessionParams): void
  (e: 'create'): void
  (e: 'open-workspace-picker'): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

// 过滤工作空间建议
const filteredWorkspaceSuggestions = computed(() => {
  const query = props.formData.workspace?.toLowerCase().trim() || ''
  
  if (!query) {
    return props.workspaceSuggestions
  }
  
  return props.workspaceSuggestions.filter(ws => 
    ws.toLowerCase().includes(query)
  )
})

// 打开工作空间选择器
const handleOpenWorkspacePicker = () => {
  emit('open-workspace-picker')
}

// 关闭对话框
const handleClose = () => {
  emit('update:visible', false)
}

// 创建会话
const handleCreate = () => {
  emit('create')
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    title="创建新会话"
    width="500px"
    :close-on-click-modal="false"
    @update:model-value="handleClose"
  >
    <el-form
      ref="createFormRef"
      :model="formData"
      label-position="top"
    >
      <el-form-item label="描述（可选）">
        <el-input
          v-model="formData.description"
          placeholder="输入会话描述..."
          clearable
        />
      </el-form-item>
      
      <el-form-item label="LLM 提供商（可选）">
        <el-select
          v-model="formData.provider"
          placeholder="选择 LLM 提供商"
          clearable
          class="w-full"
        >
          <el-option
            v-for="provider in LLM_PROVIDERS"
            :key="provider.value"
            :label="provider.label"
            :value="provider.value"
          />
        </el-select>
        <div class="text-xs text-gray-500 mt-1">
          选择用于此会话的 LLM 提供商。留空则使用默认配置。
        </div>
      </el-form-item>
      
      <el-form-item label="LLM 模型（可选）" :disabled="!formData.provider">
        <el-select
          v-model="formData.model"
          :disabled="!formData.provider"
          :placeholder="formData.provider ? '选择 LLM 模型' : '请先选择提供商'"
          clearable
          class="w-full"
        >
          <el-option
            v-for="model in availableModels"
            :key="model.value"
            :label="model.label"
            :value="model.value"
          />
        </el-select>
        <div class="text-xs text-gray-500 mt-1">
          选择用于此会话的具体模型。留空则使用提供商默认模型。
        </div>
      </el-form-item>
      
      <el-form-item label="工作目录（可选）">
        <div class="flex gap-2">
          <el-autocomplete
            ref="workspaceInputRef"
            v-model="formData.workspace"
            :suggestions="filteredWorkspaceSuggestions"
            :trigger-on-focus="false"
            clearable
            placeholder="输入或选择工作目录路径"
            class="flex-1"
            @select="(suggestion: string) => formData.workspace = suggestion"
          >
            <template #default="{ item }">
              <div class="flex items-center justify-between w-full">
                <span>{{ item }}</span>
                <el-icon class="text-gray-400"><FolderOpened /></el-icon>
              </div>
            </template>
          </el-autocomplete>
          <el-button
            type="primary"
            :icon="FolderOpened"
            @click="handleOpenWorkspacePicker"
            title="浏览工作目录"
          >
            浏览
          </el-button>
        </div>
        <div class="text-xs text-gray-500 mt-1">
          如果不指定，系统将自动创建临时目录作为工作空间
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <span class="dialog-footer">
        <el-button @click="handleClose">取消</el-button>
        <el-button
          type="primary"
          :loading="creating"
          @click="handleCreate"
        >
          创建
        </el-button>
      </span>
    </template>
  </el-dialog>
</template>

<style scoped>
:deep(.el-select) {
  width: 100%;
}
</style>
