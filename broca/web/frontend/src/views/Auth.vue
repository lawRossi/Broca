<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores'
import type { LoginForm } from '@/api/user'
import { ElMessageBox } from 'element-plus'

const router = useRouter()
const userStore = useUserStore()

// 响应式数据
const loginForm = ref<LoginForm>({
  username: 'example@email.com',
  password: '123456',
})

const loading = ref(false)
const isRegisterMode = ref(false)
const resetEmail = ref('')
const resetLoading = ref(false)
const resendConfirmationLoading = ref(false)
const showResetPassword = ref(false)

// 计算属性
const isLoggedIn = computed(() => userStore.isLoggedIn)
const emailConfirmationSent = computed(() => userStore.emailConfirmationSent)
const confirmationEmail = computed(() => userStore.confirmationEmail)

// 登录方法
const handleLogin = async () => {
  loading.value = true
  try {
    const success = await userStore.login(loginForm.value)
    if (success) {
      console.log('登录成功')
      router.push('/')
    }
  } finally {
    loading.value = false
  }
}

// 注册方法
const handleRegister = async () => {
  loading.value = true
  try {
    const success = await userStore.signUp(loginForm.value)
    if (success) {
      console.log('注册成功')
    }
  } finally {
    loading.value = false
  }
}

// 切换登录/注册模式
const toggleMode = () => {
  isRegisterMode.value = !isRegisterMode.value
  // 切换模式时重置重置密码状态
  showResetPassword.value = false
  resetEmail.value = ''
}

const handleResetPassword = async () => {
  if (!resetEmail.value) {
    ElMessageBox.alert('请输入邮箱地址', '提示', {
      confirmButtonText: '确定',
    })
    return
  }

  resetLoading.value = true
  try {
    const success = await userStore.resetPassword(resetEmail.value)
    if (success) {
      resetEmail.value = '' // 清空输入框
      showResetPassword.value = false // 重置后隐藏重置密码UI
    }
  } finally {
    resetLoading.value = false
  }
}

const handleResendConfirmation = async () => {
  if (!confirmationEmail.value) {
    ElMessageBox.alert('邮箱地址不存在', '提示', {
      confirmButtonText: '确定',
    })
    return
  }

  resendConfirmationLoading.value = true
  try {
    await userStore.resendConfirmation(confirmationEmail.value)
  } finally {
    resendConfirmationLoading.value = false
  }
}

const cancelResetPassword = () => {
  showResetPassword.value = false
  resetEmail.value = ''
}

const handleBackToLogin = () => {
  userStore.clearEmailConfirmation()
  isRegisterMode.value = false
}

// 组件挂载时初始化
onMounted(async () => {
  await userStore.init()
  console.log(isLoggedIn.value)
  if (isLoggedIn.value) {
    router.push('/')
  }
})
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-gray-50 p-4">
    <div class="w-full max-w-lg">
      <div class="card hover-lift">
        <div class="card-header">
          <h2 class="text-3xl font-bold text-center text-gray-900">
            欢迎使用我们的平台
          </h2>
          <p class="text-center text-gray-600 mt-2">
            {{ isRegisterMode ? '创建新账户' : '登录到您的账户' }}
          </p>
        </div>

        <div class="card-body">
          <!-- 登录/注册表单 - 仅在未登录时显示 -->
          <div class="space-y-6">
            <el-form :model="loginForm" label-position="top" class="space-y-4">
              <div class="form-group">
                <label class="form-label">邮箱地址</label>
                <el-input v-model="loginForm.username" placeholder="请输入邮箱地址" class="form-input" />
              </div>

              <div class="form-group">
                <label class="form-label">密码</label>
                <el-input v-model="loginForm.password" type="password" placeholder="请输入密码" class="form-input" />
              </div>
            </el-form>

            <div class="flex flex-col sm:flex-row gap-3">
              <button
                class="btn btn-primary flex-1 sm:flex-none"
                :disabled="loading"
                @click="isRegisterMode ? handleRegister() : handleLogin()"
              >
                <svg v-if="loading" class="animate-spin -ml-1 mr-3 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                  <path
                    class="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  />
                </svg>
                {{ loading ? (isRegisterMode ? '注册中...' : '登录中...') : isRegisterMode ? '注册账户' : '登录' }}
              </button>

              <button class="btn btn-outline flex-1 sm:flex-none btn-hover-fix" @click="toggleMode">
                切换到{{ isRegisterMode ? '登录' : '注册' }}
              </button>

              <!-- 忘记密码链接 - 仅在登录模式下显示，位置在最右边 -->
              <button
                v-if="!isRegisterMode && !showResetPassword"
                class="text-sm text-primary-600 hover:text-primary-500 underline self-center whitespace-nowrap px-3"
                @click="showResetPassword = true"
              >
                忘记密码？
              </button>
            </div>

            <!-- 重置密码UI - 默认隐藏，点击忘记密码后显示在下方，位置在右边 -->
            <div v-if="!isRegisterMode && showResetPassword" class="bg-gray-50 p-4 rounded-lg border border-gray-200">
              <div class="text-center mb-4">
                <h4 class="text-sm font-medium text-gray-700">
                  重置密码
                </h4>
                <p class="text-xs text-gray-500 mt-1">
                  请输入您的邮箱地址，我们将发送重置链接给您
                </p>
              </div>

              <div class="flex flex-col sm:flex-row gap-3">
                <el-input v-model="resetEmail" placeholder="请输入邮箱地址" class="form-input flex-1" />
                <button class="btn btn-warning w-full sm:w-auto" :disabled="resetLoading" @click="handleResetPassword">
                  {{ resetLoading ? '发送中...' : '发送重置邮件' }}
                </button>
              </div>

              <div class="text-center mt-3">
                <button class="text-xs text-gray-500 hover:text-gray-700" @click="cancelResetPassword">
                  取消
                </button>
              </div>
            </div>
          </div>

          <!-- 邮件确认状态显示 -->
          <div v-if="emailConfirmationSent" class="alert alert-info">
            <div class="flex items-start space-x-3">
              <svg
                class="h-6 w-6 text-primary-500 flex-shrink-0 mt-0.5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M3 8l7.89 4.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
                />
              </svg>

              <div class="flex-1">
                <h4 class="text-sm font-semibold text-primary-800 mb-2">
                  需要确认邮箱
                </h4>
                <p class="text-sm text-primary-700 mb-2">
                  我们已向 <strong>{{ confirmationEmail }}</strong> 发送了一封确认邮件。
                </p>
                <p class="text-sm text-primary-600 mb-4">
                  请检查您的邮箱并点击确认链接来完成注册。如果没收到邮件，请检查垃圾邮件文件夹。
                </p>

                <div class="flex flex-col sm:flex-row gap-3">
                  <button
                    class="btn btn-primary btn-sm"
                    :disabled="resendConfirmationLoading"
                    @click="handleResendConfirmation"
                  >
                    {{ resendConfirmationLoading ? '发送中...' : '重新发送确认邮件' }}
                  </button>

                  <button class="btn btn-secondary btn-sm" @click="handleBackToLogin">
                    返回登录
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
