<script setup lang="ts">
import { ref } from 'vue'
import { useChatStore } from '@/stores'
import FileBrowser from './FileBrowser.vue'
import type { FileItem } from '@/api/files'

const chatStore = useChatStore()

interface Props {
  visible: boolean
  initialPath?: string
}

interface Emits {
  (e: 'update:visible', value: boolean): void
  (e: 'select', file: FileItem): void
  (e: 'confirm', path: string): void
}

const props = withDefaults(defineProps<Props>(), {
  initialPath: '/',
})

const emit = defineEmits<Emits>()

const fileBrowserRef = ref<InstanceType<typeof FileBrowser> | null>(null)

// 关闭对话框
const handleClose = () => {
  emit('update:visible', false)
}

// 文件点击 - 自动选择并关闭
const handleFileClick = (file: FileItem) => {
  if (file.is_dir) {
    emit('select', file)
    emit('update:visible', false)
  }
}

// 确认选择当前目录
const handleConfirm = () => {
  if (fileBrowserRef.value) {
    const currentPath = fileBrowserRef.value.currentPath
    if (currentPath) {
      emit('confirm', currentPath)
      emit('update:visible', false)
    }
  }
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    title="选择工作目录"
    :width="chatStore.isMobile ? '100%' : '80%'"
    :fullscreen="chatStore.isMobile"
    :close-on-click-modal="false"
    @update:model-value="handleClose"
  >
    <div class="workspace-picker-dialog">
      <FileBrowser ref="fileBrowserRef" :initial-path="initialPath" @file-click="handleFileClick" />
    </div>
    <template #footer>
      <span class="dialog-footer">
        <el-button @click="handleClose">取消</el-button>
        <el-button type="primary" @click="handleConfirm">确定选择当前目录</el-button>
      </span>
    </template>
  </el-dialog>
</template>

<style scoped>
.workspace-picker-dialog {
  max-height: 70vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

:deep(.workspace-picker-dialog .file-browser) {
  flex: 1;
  min-height: 400px;
  max-height: 55vh;
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

  .workspace-picker-dialog p {
    font-size: 14px;
    margin-bottom: 16px;
    line-height: 1.5;
  }

  :deep(.file-browser) {
    min-height: 300px !important;
  }
}
</style>
