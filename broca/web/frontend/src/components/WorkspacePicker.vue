<script setup lang="ts">
import { ref } from 'vue'
import FileBrowser from './FileBrowser.vue'
import type { FileItem } from '@/api/files'

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
  initialPath: '/home'
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
    width="80%"
    :fullscreen="false"
    :close-on-click-modal="false"
    @update:model-value="handleClose"
  >
    <div class="workspace-picker-dialog">
      <p class="text-sm text-gray-600 mb-4">
        浏览并选择一个目录作为工作空间。您可以点击目录进行导航，然后点击"确定选择当前目录"按钮，或直接点击目录自动选择并关闭。
      </p>
      <FileBrowser
        ref="fileBrowserRef"
        :initial-path="initialPath"
        @file-click="handleFileClick"
      />
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
</style>
