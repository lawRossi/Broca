<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted, watch } from 'vue'
import { FolderOpened } from '@element-plus/icons-vue'
import type { CreateSessionParams } from '@/api/session'
import { configApi, type LLMProvider } from '@/api/config'

interface Props {
  visible: boolean
  formData: CreateSessionParams
  workspaceSuggestions: string[]
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

// 移动端检测
const isMobile = ref(false)

const checkIsMobile = () => {
  isMobile.value = window.innerWidth < 768
}

// LLM Provider 选项（从接口动态获取）
const llmProviders = ref<LLMProvider[]>([])
const loadingProviders = ref(false)
const availableModels = ref<Array<{ id: string; name: string }>>([])
const loadingModels = ref(false)

// 加载LLM提供商列表
const loadLLMProviders = async () => {
  try {
    loadingProviders.value = true
    const providers = await configApi.getLLMProviders()
    llmProviders.value = providers
  } catch (error) {
    console.error('Failed to load LLM providers:', error)
  } finally {
    loadingProviders.value = false
  }
}

// 加载指定提供商的模型列表
const loadLLMModels = async (provider: string) => {
  if (!provider) {
    availableModels.value = []
    return
  }

  try {
    loadingModels.value = true
    const models = await configApi.getLLMModels(provider)
    // 转换为前端需要的格式
    availableModels.value = models.map((model) => ({
      id: model.id,
      name: model.name,
    }))
  } catch (error) {
    console.error(`Failed to load models for provider ${provider}:`, error)
    availableModels.value = []
  } finally {
    loadingModels.value = false
  }
}

// 处理提供商变化
const handleProviderChange = (provider: string) => {
  // 清空已选择的模型
  emit('update:formData', {
    ...props.formData,
    model: undefined,
  })

  // 加载新提供商的模型
  loadLLMModels(provider)
}

// 组件挂载时加载提供商列表
onMounted(() => {
  loadLLMProviders()

  // 如果已经有选中的提供商，加载对应的模型
  if (props.formData.provider) {
    loadLLMModels(props.formData.provider)
  }

  checkIsMobile()
  window.addEventListener('resize', checkIsMobile)
})

onUnmounted(() => {
  window.removeEventListener('resize', checkIsMobile)
})

// 监听formData.provider变化
watch(
  () => props.formData.provider,
  (newProvider, oldProvider) => {
    if (newProvider !== oldProvider) {
      loadLLMModels(newProvider || '')
    }
  }
)

// 过滤工作空间建议
const filteredWorkspaceSuggestions = computed(() => {
  const query = props.formData.workspace?.toLowerCase().trim() || ''

  if (!query) {
    return props.workspaceSuggestions
  }

  return props.workspaceSuggestions.filter((ws) => ws.toLowerCase().includes(query))
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
    :width="isMobile ? '100%' : '500px'"
    :fullscreen="isMobile"
    :close-on-click-modal="false"
    @update:model-value="handleClose"
  >
    <el-form ref="createFormRef" :model="formData" label-position="top">
      <el-form-item label="描述（可选）">
        <el-input v-model="formData.description" placeholder="输入会话描述..." clearable />
      </el-form-item>

      <el-form-item label="LLM 提供商（可选）">
        <el-select
          v-model="formData.provider"
          placeholder="选择 LLM 提供商"
          clearable
          class="w-full"
          :loading="loadingProviders"
          @change="handleProviderChange"
        >
          <el-option v-for="provider in llmProviders" :key="provider.id" :label="provider.name" :value="provider.id">
            <div class="flex items-center justify-between">
              <span>{{ provider.name }}</span>
            </div>
          </el-option>
        </el-select>
        <div class="text-xs text-gray-500 mt-1">选择用于此会话的 LLM 提供商。留空则使用默认配置。</div>
      </el-form-item>

      <el-form-item label="LLM 模型（可选）" :disabled="!formData.provider">
        <el-select
          v-model="formData.model"
          :disabled="!formData.provider"
          :placeholder="formData.provider ? '选择 LLM 模型' : '请先选择提供商'"
          clearable
          class="w-full"
          :loading="loadingModels"
        >
          <el-option v-for="model in availableModels" :key="model.id" :label="model.name" :value="model.id" />
        </el-select>
        <div class="text-xs text-gray-500 mt-1">选择用于此会话的具体模型。留空则使用提供商默认模型。</div>
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
            @select="(suggestion: string) => (formData.workspace = suggestion)"
          >
            <template #default="{ item }">
              <div class="flex items-center justify-between w-full">
                <span>{{ item }}</span>
                <el-icon class="text-gray-400">
                  <FolderOpened />
                </el-icon>
              </div>
            </template>
          </el-autocomplete>
          <el-button type="primary" :icon="FolderOpened" title="浏览工作目录" @click="handleOpenWorkspacePicker">
            浏览
          </el-button>
        </div>
        <div class="text-xs text-gray-500 mt-1">如果不指定，系统将自动创建临时目录作为工作空间</div>
      </el-form-item>
    </el-form>
    <template #footer>
      <span class="dialog-footer">
        <el-button @click="handleClose">取消</el-button>
        <el-button type="primary" :loading="creating" @click="handleCreate"> 创建 </el-button>
      </span>
    </template>
  </el-dialog>
</template>

<style scoped>
:deep(.el-select) {
  width: 100%;
}

/* 移动端优化 */
@media (max-width: 768px) {
  :deep(.el-dialog) {
    margin: 0 !important;
    border-radius: 0 !important;
    width: 100% !important;
    max-height: 100vh;
    overflow: hidden;
  }

  :deep(.el-dialog__header) {
    padding: 16px 20px;
    margin: 0;
    border-bottom: 1px solid var(--el-border-color-light);
  }

  :deep(.el-dialog__title) {
    font-size: 18px;
    font-weight: 600;
  }

  :deep(.el-dialog__body) {
    padding: 16px 20px;
    overflow-y: auto;
    flex: 1;
    max-height: calc(100vh - 120px);
  }

  :deep(.el-dialog__footer) {
    padding: 12px 20px;
    border-top: 1px solid var(--el-border-color-light);
  }

  :deep(.el-form-item) {
    margin-bottom: 20px;
  }

  :deep(.el-form-item__label) {
    font-size: 14px;
    font-weight: 500;
    margin-bottom: 8px;
    line-height: 1.4;
  }

  :deep(.el-input__inner) {
    font-size: 16px; /* 防止iOS缩放 */
    padding: 12px 16px;
  }

  :deep(.el-button) {
    min-height: 44px; /* 触摸设备最小点击区域 */
    min-width: 44px;
  }

  /* 工作目录输入区域 */
  :deep(.el-autocomplete) {
    width: 100% !important;
  }

  :deep(.el-autocomplete .el-input__inner) {
    padding-right: 40px;
  }
}
</style>
