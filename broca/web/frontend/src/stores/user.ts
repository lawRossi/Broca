import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

import { type LoginForm, type UserInfo, userApi } from '@/api/user'
import router from '@/router'
import { supabase, SupabaseAuth } from '@/utils/supabase'

const AuthErrorType = {
  INVALID_EMAIL: 'INVALID_EMAIL',
  WEAK_PASSWORD: 'WEAK_PASSWORD',
  EMAIL_ALREADY_EXISTS: 'EMAIL_ALREADY_EXISTS',
  USER_NOT_FOUND: 'USER_NOT_FOUND',
  INVALID_CREDENTIALS: 'INVALID_CREDENTIALS',
  NETWORK_ERROR: 'NETWORK_ERROR',
  SERVER_ERROR: 'SERVER_ERROR',
  RATE_LIMITED: 'RATE_LIMITED',
  UNKNOWN_ERROR: 'UNKNOWN_ERROR',
} as const

type AuthErrorType = (typeof AuthErrorType)[keyof typeof AuthErrorType]

// 错误信息映射
const ErrorMessages = {
  [AuthErrorType.INVALID_EMAIL]: '邮箱格式不正确',
  [AuthErrorType.WEAK_PASSWORD]: '密码强度不够，至少需要6位字符',
  [AuthErrorType.EMAIL_ALREADY_EXISTS]: '该邮箱已被注册',
  [AuthErrorType.USER_NOT_FOUND]: '用户不存在',
  [AuthErrorType.INVALID_CREDENTIALS]: '邮箱或密码错误',
  [AuthErrorType.NETWORK_ERROR]: '网络连接失败，请检查网络设置',
  [AuthErrorType.SERVER_ERROR]: '服务器错误，请稍后重试',
  [AuthErrorType.RATE_LIMITED]: '操作过于频繁，请稍后再试',
  [AuthErrorType.UNKNOWN_ERROR]: '操作失败，请重试',
}

// 解析 Supabase 错误
const parseSupabaseError = (error: any): AuthErrorType => {
  if (!error || !error.message) {
    return AuthErrorType.UNKNOWN_ERROR
  }

  const message = error.message.toLowerCase()

  // 邮箱格式错误
  if (message.includes('invalid email') || message.includes('invalid format')) {
    return AuthErrorType.INVALID_EMAIL
  }

  // 密码强度不够
  if (
    message.includes('password') &&
    (message.includes('weak') || message.includes('short') || message.includes('minimum'))
  ) {
    return AuthErrorType.WEAK_PASSWORD
  }

  // 用户已存在
  if (
    message.includes('already registered') ||
    message.includes('already exists') ||
    message.includes('user already registered')
  ) {
    return AuthErrorType.EMAIL_ALREADY_EXISTS
  }

  // 用户不存在
  if (
    message.includes('invalid login') ||
    message.includes('email not confirmed') ||
    message.includes('user not found')
  ) {
    return AuthErrorType.USER_NOT_FOUND
  }

  // 认证失败
  if (
    message.includes('invalid credentials') ||
    message.includes('wrong password') ||
    message.includes('invalid login')
  ) {
    return AuthErrorType.INVALID_CREDENTIALS
  }

  // 网络错误
  if (
    message.includes('fetch') ||
    message.includes('network') ||
    message.includes('connection') ||
    error.name === 'TypeError'
  ) {
    return AuthErrorType.NETWORK_ERROR
  }

  // 服务器错误
  if (message.includes('500') || message.includes('internal server error') || message.includes('server error')) {
    return AuthErrorType.SERVER_ERROR
  }

  // 频率限制
  if (message.includes('rate limit') || message.includes('too many requests') || message.includes('频率')) {
    return AuthErrorType.RATE_LIMITED
  }

  return AuthErrorType.UNKNOWN_ERROR
}

export const useUserStore = defineStore('user', () => {
  // 状态
  const token = ref<string | null>(null)
  const userId = ref<string | null>(null)
  const isLoggedIn = ref<boolean>(false)
  const emailConfirmationSent = ref<boolean>(false)
  const confirmationEmail = ref<string>('')
  const userInfo = ref<UserInfo | null>(null)

  const signUp = async (loginForm: LoginForm) => {
    try {
      // 验证输入
      if (!loginForm.username || !loginForm.password) {
        ElMessage.error('请填写邮箱和密码')
        return false
      }

      if (loginForm.password.length < 6) {
        ElMessage.error('密码至少需要6位字符')
        return false
      }

      const data = await SupabaseAuth.signUp(
        loginForm.username,
        loginForm.password,
        `${window.location.origin}/auth/callback`
      )

      // 检查是否需要邮件确认
      if (data.user && !data.session) {
        // 用户已创建但需要邮件确认
        emailConfirmationSent.value = true
        confirmationEmail.value = loginForm.username
        ElMessage.success('注册成功！请检查您的邮箱并点击确认链接来完成注册。')
        return true
      } else if (data.session) {
        // 直接登录（如果Supabase配置允许）
        userId.value = data.session.user.id
        token.value = data.session.access_token
        localStorage.setItem('token', token.value)
        isLoggedIn.value = true
        ElMessage.success('注册成功')
        return true
      } else {
        ElMessage.error('注册响应异常')
        return false
      }
    } catch (error: any) {
      console.error('注册失败:', error)

      // 细分注册失败原因
      const errorType = parseSupabaseError(error)
      const errorMessage = ErrorMessages[errorType] || '注册失败'
      ElMessage.error(errorMessage)
      return false
    }
  }

  // 登录
  const login = async (loginForm: LoginForm) => {
    try {
      // 验证输入
      if (!loginForm.username || !loginForm.password) {
        ElMessage.error('请填写邮箱和密码')
        return false
      }

      const data = await SupabaseAuth.signIn(loginForm.username, loginForm.password)
      token.value = data.session.access_token
      if (token.value) {
        localStorage.setItem('token', token.value)
        userId.value = data.session.user.id
        isLoggedIn.value = true
        userInfo.value = await userApi.getUserInfo()
        ElMessage.success('登录成功')
        return true
      } else {
        ElMessage.error('登录响应异常')
        return false
      }
    } catch (error: any) {
      console.error('登录失败:', error)

      // 细分登录失败原因
      const errorType = parseSupabaseError(error)
      const errorMessage = ErrorMessages[errorType] || '登录失败'

      ElMessage.error(errorMessage)
      return false
    }
  }

  supabase.auth.onAuthStateChange((event, session) => {
    console.log('认证状态变化:', event)
    if (session) {
      userId.value = session.user.id
      token.value = session.access_token
      localStorage.setItem('token', token.value)
      isLoggedIn.value = true
      console.log('用户已登录')
    } else {
      userId.value = null
      token.value = null
      userInfo.value = null
      localStorage.removeItem('token')
      isLoggedIn.value = false
    }
  })

  // 登出
  const logout = async () => {
    try {
      await SupabaseAuth.signOut()
      ElMessage.success('登出成功')
    } catch (error: any) {
      console.error('登出请求失败:', error)
      ElMessage.warning('登出时出现错误，但已清理本地状态')
    } finally {
      // 清理本地状态
      userId.value = null
      token.value = null
      userInfo.value = null
      isLoggedIn.value = false
      localStorage.removeItem('token')
      router.push('/')
    }
  }

  // 获取错误详情
  const getAuthError = (error: any): { type: string; message: string } => {
    const errorType = parseSupabaseError(error)
    return {
      type: errorType,
      message: ErrorMessages[errorType] || '未知错误',
    }
  }

  // 重置密码
  const resetPassword = async (email: string) => {
    try {
      if (!email) {
        ElMessage.error('请输入邮箱地址')
        return false
      }

      await SupabaseAuth.resetPassword(email)
      ElMessage.success('密码重置邮件已发送，请检查您的邮箱')
      return true
    } catch (error: any) {
      console.error('重置密码失败:', error)

      const errorType = parseSupabaseError(error)
      const errorMessage = ErrorMessages[errorType] || '重置密码失败'

      ElMessage.error(errorMessage)
      return false
    }
  }

  // 重新发送确认邮件
  const resendConfirmation = async (email: string) => {
    try {
      if (!email) {
        ElMessage.error('请输入邮箱地址')
        return false
      }

      await SupabaseAuth.resendConfirmation(email)
      ElMessage.success('确认邮件已重新发送，请检查您的邮箱')
      return true
    } catch (error: any) {
      console.error('重新发送确认邮件失败:', error)

      const errorType = parseSupabaseError(error)
      const errorMessage = ErrorMessages[errorType] || '重新发送确认邮件失败'

      ElMessage.error(errorMessage)
      return false
    }
  }

  // 清除邮件确认状态
  const clearEmailConfirmation = () => {
    emailConfirmationSent.value = false
    confirmationEmail.value = ''
  }

  const fetchUserInfo = async () => {
    try {
      if (!userId.value) {
        return
      }
      if (userInfo.value) {
        return userInfo.value
      }
      userInfo.value = await userApi.getUserInfo()
      return userInfo.value
    } catch (error) {
      console.error('获取用户信息失败:', error)
      ElMessage.error('获取用户信息失败')
    }
  }

  const init = async () => {
    console.log('初始化用户信息')
    try {
      const session = await SupabaseAuth.getSession()
      if (session) {
        userId.value = session.user.id
        token.value = session.access_token
        localStorage.setItem('token', token.value)
        isLoggedIn.value = true
        userInfo.value = await userApi.getUserInfo()
      } else {
        console.log('No active session found')
        userId.value = null
        token.value = null
        isLoggedIn.value = false
        userInfo.value = null
        localStorage.removeItem('token')
      }
    } catch (error) {
      console.error('Error initializing user store:', error)
      userId.value = null
      token.value = null
      isLoggedIn.value = false
      localStorage.removeItem('token')
    }
  }

  return {
    confirmationEmail,
    emailConfirmationSent,
    isLoggedIn,
    token,
    userId,
    userInfo,
    login,
    signUp,
    logout,
    init,
    fetchUserInfo,
    getAuthError,
    resetPassword,
    resendConfirmation,
    clearEmailConfirmation,
  }
})
