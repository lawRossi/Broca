<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores'
import type { UserInfo } from '@/api/user'
import { userApi } from '@/api/user'
import { SupabaseStorage } from '@/utils/supabase'
import { ElMessage } from 'element-plus'

const router = useRouter()
const userStore = useUserStore()

// 响应式数据
const userInfo = ref<UserInfo | null>(null)
const loading = ref(false)
const addingInfo = ref(false)
const userId = computed(() => userStore.userId)

// 添加用户信息的表单
const addInfoForm = ref({
  name: '',
  avatarFile: null as File | null,
  avatarPreview: '', // 预览URL
})

// 文件输入引用
const avatarInputRef = ref<HTMLInputElement>()

// 计算属性：是否已登录
const isLoggedIn = computed(() => userStore.isLoggedIn)

// 检查登录状态并获取用户信息
const checkAuthAndLoadUserInfo = async () => {
  if (!isLoggedIn.value) {
    router.push('/auth')
    return
  }

  try {
    loading.value = true
    userInfo.value = await userApi.getUserInfo()
  } catch (error) {
    console.error('获取用户信息失败:', error)
    ElMessage.error('获取用户信息失败')
  } finally {
    loading.value = false
  }
}

// 处理文件选择
const handleFileSelect = (event: Event) => {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]

  if (file) {
    // 验证文件类型
    if (!file.type.startsWith('image/')) {
      ElMessage.warning('请选择图片文件')
      target.value = ''
      return
    }

    // 验证文件大小 (最大 5MB)
    if (file.size > 5 * 1024 * 1024) {
      ElMessage.warning('图片大小不能超过 5MB')
      target.value = ''
      return
    }

    addInfoForm.value.avatarFile = file

    // 创建预览URL
    const reader = new FileReader()
    reader.onload = (e) => {
      addInfoForm.value.avatarPreview = e.target?.result as string
    }
    reader.readAsDataURL(file)
  } else {
    addInfoForm.value.avatarFile = null
    addInfoForm.value.avatarPreview = ''
  }
}

// 移除头像
const removeAvatar = () => {
  addInfoForm.value.avatarFile = null
  addInfoForm.value.avatarPreview = ''
  if (avatarInputRef.value) {
    avatarInputRef.value.value = ''
  }
}

// 处理添加用户信息
const handleAddUserInfo = async () => {
  if (!addInfoForm.value.name.trim()) {
    ElMessage.warning('请输入姓名')
    return
  }

  if (!addInfoForm.value.avatarFile) {
    ElMessage.warning('请上传头像')
    return
  }

  try {
    addingInfo.value = true

    let avatarUrl = ''

    // 如果有头像文件，先上传到 Supabase Storage
    if (addInfoForm.value.avatarFile) {
      try {
        const originalName = addInfoForm.value.avatarFile.name
        const newfileName = SupabaseStorage.generateUniqueFilename(originalName)
        const date = new Date()
        const year = date.getFullYear()
        const month = String(date.getMonth() + 1).padStart(2, '0')
        const day = String(date.getDate()).padStart(2, '0')
        const fileName = `${userId.value}/${year}${month}${day}/${newfileName}`
        await SupabaseStorage.upload('images', fileName, addInfoForm.value.avatarFile)
        avatarUrl = SupabaseStorage.getPublicUrl('images', fileName)
      } catch (uploadError) {
        console.error('头像上传失败:', uploadError)
        ElMessage.error('头像上传失败')
        return
      }
    }

    const newUserInfo: UserInfo = {
      id: userId.value || '',
      name: addInfoForm.value.name.trim(),
      avatar: avatarUrl,
    }

    userInfo.value = await userApi.addUserInfo(newUserInfo)
    ElMessage.success('用户信息添加成功')
  } catch (error) {
    console.error('添加用户信息失败:', error)
    ElMessage.error('添加用户信息失败')
  } finally {
    addingInfo.value = false
  }
}

const handleLogout = async () => {
  userStore.logout()
  router.push('/auth')
}

// 组件挂载时执行
onMounted(async () => {
  await userStore.init()
  await checkAuthAndLoadUserInfo()
})
</script>

<template>
  <div class="min-h-screen bg-gray-50 py-8">
    <div class="container mx-auto px-4 max-w-2xl">
      <!-- 加载状态 -->
      <div v-if="loading" class="text-center py-12">
        <div class="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600" />
        <p class="mt-2 text-gray-600">
          加载中...
        </p>
      </div>

      <!-- 已登录但没有用户信息 - 显示添加表单 -->
      <div v-else-if="isLoggedIn && !userInfo" class="card">
        <div class="card-header">
          <h2 class="text-2xl font-bold text-gray-900">
            完善个人信息
          </h2>
          <p class="text-gray-600 mt-2">
            请添加您的基本信息以完成设置
          </p>
        </div>

        <div class="card-body">
          <form class="space-y-6" @submit.prevent="handleAddUserInfo">
            <div class="form-group">
              <label class="form-label">姓名 *</label>
              <el-input
                v-model="addInfoForm.name"
                placeholder="请输入您的姓名"
                class="form-input"
                :disabled="addingInfo"
              />
            </div>

            <div class="form-group">
              <label class="form-label">头像（可选）</label>

              <!-- 头像预览 -->
              <div v-if="addInfoForm.avatarPreview" class="mb-3 flex items-center space-x-3">
                <img
                  :src="addInfoForm.avatarPreview"
                  alt="头像预览"
                  class="w-16 h-16 rounded-full object-cover border-2 border-gray-200"
                >
                <button
                  type="button"
                  class="text-red-500 hover:text-red-700 text-sm underline"
                  :disabled="addingInfo"
                  @click="removeAvatar"
                >
                  移除
                </button>
              </div>

              <!-- 文件选择按钮 -->
              <div class="flex items-center space-x-3">
                <input
                  ref="avatarInputRef"
                  type="file"
                  accept="image/*"
                  class="hidden"
                  :disabled="addingInfo"
                  @change="handleFileSelect"
                >
                <button
                  type="button"
                  class="btn btn-outline btn-sm"
                  :disabled="addingInfo"
                  @click="avatarInputRef?.click()"
                >
                  <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      stroke-width="2"
                      d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
                    />
                  </svg>
                  {{ addInfoForm.avatarPreview ? '更换头像' : '选择头像' }}
                </button>
                <span class="text-sm text-gray-500">支持 JPG、PNG、GIF，大小不超过 5MB</span>
              </div>
            </div>

            <div class="flex gap-4">
              <button type="submit" class="btn btn-primary" :disabled="addingInfo">
                <svg
                  v-if="addingInfo"
                  class="animate-spin -ml-1 mr-3 h-4 w-4 text-white"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                  <path
                    class="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  />
                </svg>
                {{ addingInfo ? '保存中...' : '保存信息' }}
              </button>
            </div>
          </form>
        </div>
      </div>

      <!-- 已登录且有用户信息 - 显示用户信息 -->
      <div v-else-if="isLoggedIn && userInfo" class="card">
        <div class="card-header">
          <h2 class="text-2xl font-bold text-gray-900">
            欢迎回来，{{ userInfo.name }}！
          </h2>
        </div>

        <div class="card-body">
          <div class="flex items-center space-x-6">
            <!-- 头像 -->
            <div class="flex-shrink-0">
              <img
                v-if="userInfo.avatar"
                :src="userInfo.avatar"
                alt="用户头像"
                class="w-20 h-20 rounded-full object-cover border-2 border-gray-200"
              >
              <div v-else class="w-20 h-20 rounded-full bg-gray-300 flex items-center justify-center">
                <svg class="w-8 h-8 text-gray-600" fill="currentColor" viewBox="0 0 20 20">
                  <path
                    fill-rule="evenodd"
                    d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z"
                    clip-rule="evenodd"
                  />
                </svg>
              </div>
            </div>

            <!-- 用户信息 -->
            <div class="flex-1">
              <h3 class="text-xl font-semibold text-gray-900 mb-2">
                {{ userInfo.name }}
              </h3>
              <p class="text-gray-600">
                用户 ID: {{ userInfo.id }}
              </p>
            </div>
          </div>

          <!-- 退出登录按钮 -->
          <div class="mt-6 flex justify-end">
            <button class="btn btn-outline" @click="handleLogout">
              退出登录
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
