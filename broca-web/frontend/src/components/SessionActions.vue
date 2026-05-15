<script setup lang="ts">
import { Delete } from '@element-plus/icons-vue'

interface Props {
  isAllSelected: boolean
  isIndeterminate: boolean
  selectedCount: number
  deleteLoading: boolean
}

interface Emits {
  (e: 'select-all'): void
  (e: 'deselect-all'): void
  (e: 'batch-delete'): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

// 全选按钮点击
const handleSelectAll = () => {
  if (props.isAllSelected) {
    emit('deselect-all')
  } else {
    emit('select-all')
  }
}

// 批量删除按钮点击
const handleBatchDelete = () => {
  emit('batch-delete')
}
</script>

<template>
  <div
    v-if="selectedCount > 0"
    class="session-actions bg-blue-50 border border-blue-200 rounded-lg p-3 mb-4 flex items-center justify-between"
  >
    <div class="flex items-center gap-3">
      <el-checkbox :model-value="isAllSelected" :indeterminate="isIndeterminate" @change="handleSelectAll">
        已选择 {{ selectedCount }} 项
      </el-checkbox>
    </div>

    <div class="flex items-center gap-2">
      <el-button type="danger" size="small" :loading="deleteLoading" :icon="Delete" @click="handleBatchDelete">
        批量删除 ({{ selectedCount }})
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.session-actions {
  animation: slideDown 0.2s ease-out;
}

@keyframes slideDown {
  from {
    opacity: 0;
    transform: translateY(-10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
