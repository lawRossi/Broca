<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores'
import { supabase } from '@/utils/supabase'
import { ElMessage } from 'element-plus'

const router = useRouter()
const userStore = useUserStore()

const loading = ref(true)
const error = ref<string | null>(null)

onMounted(async () => {
  try {
    // 解析URL参数（处理query参数和hash fragment）
    let token: string | null = null
    let type: string | null = null
    let access_token: string | null = null

    // 首先尝试从query参数获取
    const queryParams = new URLSearchParams(window.location.search)
    token = queryParams.get('token')
    type = queryParams.get('type')
    access_token = queryParams.get('access_token')

    // 如果query参数中没有，再尝试从hash fragment获取
    if (!access_token && window.location.hash) {
      const hashParams = new URLSearchParams(window.location.hash.substring(1))
      access_token = hashParams.get('access_token')
      const signup_type = hashParams.get('type')

      // 如果hash中有type参数且是signup，则可能需要处理邮箱确认
      if (signup_type === 'signup') {
        type = 'signup'
      }
    }

    console.log('Parsed token:', token)
    console.log('Parsed type:', type)
    console.log('Parsed access_token:', access_token)

    if (type === 'signup' && token) {
      // 处理邮箱确认OTP
      console.log('Verifying OTP with token:', token)
      const { data, error: supabaseError } = await supabase.auth.verifyOtp({
        token_hash: token,
        type: 'signup',
      })

      if (supabaseError) {
        throw new Error(supabaseError.message)
      }

      if (data.user && data.session) {
        // 邮箱确认成功，设置用户状态
        userStore.token = data.session.access_token
        userStore.isLoggedIn = true
        userStore.clearEmailConfirmation()

        // 保存token到localStorage
        localStorage.setItem('token', data.session.access_token)

        ElMessage.success('邮箱确认成功！欢迎使用我们的服务')

        // 延迟跳转到主页，让用户看到成功消息
        setTimeout(() => {
          router.push('/')
        }, 2000)
      } else {
        throw new Error('邮箱确认失败')
      }
    } else if (access_token) {
      // 处理OAuth回调（带access_token的情况）
      console.log('Handling OAuth callback with access_token:', access_token.substring(0, 20) + '...')

      try {
        // 设置session
        const { data, error: sessionError } = await supabase.auth.setSession({
          access_token,
          refresh_token: new URLSearchParams(window.location.hash.substring(1)).get('refresh_token') || '',
        })

        if (sessionError) {
          throw new Error(sessionError.message)
        }

        if (data.user && data.session) {
          // OAuth认证成功，设置用户状态
          userStore.token = data.session.access_token
          userStore.isLoggedIn = true

          // 保存token到localStorage
          localStorage.setItem('token', data.session.access_token)

          ElMessage.success('登录成功！欢迎回来')

          // 延迟跳转到主页
          setTimeout(() => {
            router.push('/')
          }, 2000)
        } else {
          throw new Error('OAuth认证失败')
        }
      } catch (oauthError: any) {
        console.error('OAuth处理失败:', oauthError)
        throw new Error('登录失败：' + oauthError.message)
      }
    } else {
      throw new Error('无效的确认链接')
    }
  } catch (err: any) {
    console.error('邮箱确认失败:', err)
    error.value = '确认失败，请重试'
    ElMessage.error(error.value)

    // 3秒后跳转到主页
    setTimeout(() => {
      router.push('/')
    }, 3000)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-gray-50 p-4">
    <div class="w-full max-w-md">
      <div class="card text-center">
        <div class="card-body py-12">
          <!-- 加载状态 -->
          <div v-if="loading" class="flex flex-col items-center space-y-6">
            <div class="relative">
              <div class="animate-spin rounded-full h-16 w-16 border-4 border-primary-200" />
              <div
                class="animate-spin rounded-full h-16 w-16 border-4 border-primary-500 border-t-transparent absolute top-0 left-0"
              />
            </div>

            <div class="space-y-2">
              <h2 class="text-2xl font-semibold text-gray-900">
                正在确认您的邮箱
              </h2>
              <p class="text-gray-600">
                请稍候，我们正在处理您的邮箱确认...
              </p>
            </div>

            <div class="flex space-x-1">
              <div class="w-2 h-2 bg-primary-500 rounded-full animate-pulse" style="animation-delay: 0ms" />
              <div class="w-2 h-2 bg-primary-500 rounded-full animate-pulse" style="animation-delay: 150ms" />
              <div class="w-2 h-2 bg-primary-500 rounded-full animate-pulse" style="animation-delay: 300ms" />
            </div>
          </div>

          <!-- 错误状态 -->
          <div v-else-if="error" class="flex flex-col items-center space-y-6">
            <div class="rounded-full h-16 w-16 bg-red-100 flex items-center justify-center">
              <svg class="h-8 w-8 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </div>

            <div class="space-y-2">
              <h2 class="text-2xl font-semibold text-gray-900">
                确认失败
              </h2>
              <p class="text-gray-600">
                {{ error }}
              </p>
              <p class="text-sm text-gray-500">
                3秒后自动跳转到主页...
              </p>
            </div>

            <div class="flex space-x-2">
              <div class="w-2 h-2 bg-red-400 rounded-full animate-pulse" style="animation-delay: 0ms" />
              <div class="w-2 h-2 bg-red-400 rounded-full animate-pulse" style="animation-delay: 500ms" />
              <div class="w-2 h-2 bg-red-400 rounded-full animate-pulse" style="animation-delay: 1000ms" />
            </div>
          </div>

          <!-- 成功状态 -->
          <div v-else class="flex flex-col items-center space-y-6">
            <div class="rounded-full h-16 w-16 bg-green-100 flex items-center justify-center">
              <svg class="h-8 w-8 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
              </svg>
            </div>

            <div class="space-y-2">
              <h2 class="text-2xl font-semibold text-gray-900">
                邮箱确认成功！
              </h2>
              <p class="text-gray-600">
                感谢您确认邮箱，欢迎使用我们的平台
              </p>
              <p class="text-sm text-gray-500">
                正在跳转到主页...
              </p>
            </div>

            <div class="animate-pulse">
              <div class="flex space-x-1">
                <div class="w-2 h-2 bg-green-500 rounded-full animate-bounce" />
                <div class="w-2 h-2 bg-green-500 rounded-full animate-bounce" style="animation-delay: 0.1s" />
                <div class="w-2 h-2 bg-green-500 rounded-full animate-bounce" style="animation-delay: 0.2s" />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
