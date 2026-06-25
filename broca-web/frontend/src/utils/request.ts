import axios, { type AxiosInstance, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'

// 扩展 AxiosRequestConfig 类型，支持自定义选项
declare module 'axios' {
  interface AxiosRequestConfig {
    /** 静默模式：不弹出错误提示，适用于后台轮询等场景 */
    silent?: boolean
  }
}

/** 从各种可能的响应格式中提取错误消息 */
function extractErrorMsg(data: any): string {
  if (!data) return ''
  return data.detail || data.msg || data.message || (typeof data === 'string' ? data : '')
}

// 判断当前请求是否为本地自动登录（静默处理，无错误提示）
function isLocalLoginRequest(config: InternalAxiosRequestConfig | undefined): boolean {
  return !!config?.url?.includes('/auth/local-login')
}
function isSilent(config: InternalAxiosRequestConfig | undefined): boolean {
  return !!(config as any)?.silent
}

// 创建 Axios 实例
const request: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 15000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器
request.interceptors.request.use(
  (config) => {
    // 本地自动登录请求自动设为静默模式（无错误提示）
    if (config.url?.includes('/auth/local-login')) {
      ;(config as any).silent = true
    }
    // 在请求发送前添加 token 等逻辑
    const token = localStorage.getItem('token')
    if (token) {
      config.headers = config.headers || {}
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    console.error('请求错误:', error)
    return Promise.reject(error)
  }
)

// 响应拦截器
request.interceptors.response.use(
  (response: AxiosResponse) => {
    const { data, config } = response
    const silent = isSilent(config)

    // 处理业务状态码
    if (data.code === 200) {
      return data.data
      } else {
        const errMsg = data.msg || '请求失败'
        if (!silent && !isLocalLoginRequest(config)) {
          ElMessage.error(errMsg)
      }
      return Promise.reject(new Error(errMsg))
    }
  },
  (error) => {
    console.error('响应错误:', error)
    const config = error.config as InternalAxiosRequestConfig | undefined
    const silent = isSilent(config)

    if (error.response) {
      // HTTP 错误状态码处理
      const { status, data } = error.response
      const detail = extractErrorMsg(data)

      switch (status) {
        case 401:
          // 清除本地 token 并跳转到登录页（静默处理，无错误提示）
          localStorage.removeItem('token')
          localStorage.removeItem('user_id')
          localStorage.removeItem('username')
          router.push('/auth')
          break
        case 403:
          if (!silent && !isLocalLoginRequest(config)) ElMessage.error(detail || '拒绝访问')
          break
        case 404:
          if (!silent) ElMessage.error(detail || '请求地址不存在')
          break
        case 500:
          if (!silent) ElMessage.error(detail || '服务器内部错误，请稍后重试')
          break
        default:
          if (!silent && !isLocalLoginRequest(config)) ElMessage.error(detail || data?.msg || '网络连接失败')
      }
    } else if (error.request) {
      if (!silent && !isLocalLoginRequest(config)) ElMessage.error('网络连接失败，请检查网络设置')
    } else {
      console.error('请求配置错误:', error.message)
    }

    return Promise.reject(error)
  }
)

export default request
