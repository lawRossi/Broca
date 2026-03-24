<script setup lang="ts">
import { Search, Plus } from '@element-plus/icons-vue'

interface Props {
  searchKeyword: string
  statusFilter: string
  isLoggedIn: boolean
}

interface Emits {
  (e: 'update:searchKeyword', value: string): void
  (e: 'update:statusFilter', value: string): void
  (e: 'create'): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

// 状态选项
const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '进行中', value: 'active' },
  { label: '已完成', value: 'completed' },
  { label: '已暂停', value: 'paused' },
  { label: '错误', value: 'error' },
]

// 搜索处理
const handleSearch = (value: string) => {
  emit('update:searchKeyword', value)
}

// 状态筛选处理
const handleStatusChange = (value: string) => {
  emit('update:statusFilter', value)
}

// 创建按钮点击
const handleCreate = () => {
  emit('create')
}
</script>

<template>
  <div class="session-search-filter flex flex-col sm:flex-row gap-3">
    <!-- 搜索框 -->
    <el-input
      :model-value="searchKeyword"
      placeholder="搜索会话..."
      clearable
      class="flex-1"
      @input="handleSearch"
    >
      <template #prefix>
        <el-icon><Search /></el-icon>
      </template>
    </el-input>

    <!-- 状态筛选 -->
    <el-select
      :model-value="statusFilter"
      placeholder="筛选状态"
      clearable
      class="w-full sm:w-40"
      @change="handleStatusChange"
    >
      <el-option
        v-for="option in statusOptions"
        :key="option.value"
        :label="option.label"
        :value="option.value"
      />
    </el-select>

    <!-- 创建按钮 -->
    <el-button
      type="primary"
      :icon="Plus"
      @click="handleCreate"
    >
      创建会话
    </el-button>
  </div>
</template>

<style scoped>
.session-search-filter {
  width: 100%;
}
</style>

