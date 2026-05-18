/**
 * 统一文件上传模块 (VS Code WebView 侧)
 *
 * WebView 侧只负责将文件读取为 base64 并通过 postMessage 发送给扩展进程，
 * 实际上传由扩展进程 (chatWebView.ts) 在 Node.js 环境中执行，
 * 支持 Supabase Storage 和 Cloudflare R2 (S3 兼容)
 */

import { postMessage } from '../api/vscode'

// ==================== 类型定义 ====================

export interface UploadResult {
  name: string
  url: string
  path: string
  size: number
  type: string
}

// ==================== 工具函数 ====================

/**
 * 将 File 读取为 base64 字符串
 */
function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result as string
      const base64 = result.split(',')[1] || result
      resolve(base64)
    }
    reader.onerror = () => reject(new Error('读取文件失败'))
    reader.readAsDataURL(file)
  })
}

/**
 * 通过扩展进程上传文件
 * 向扩展发送 'uploadFile' 消息，扩展会使用配置的存储后端（Supabase 或 Cloudflare）上传
 *
 * @param file 要上传的文件
 * @returns Promise，在上传完成后 resolve 上传结果
 */
export function uploadFile(file: File): Promise<UploadResult> {
  return new Promise(async (resolve, reject) => {
    try {
      const base64 = await fileToBase64(file)

      // 监听上传结果
      const messageHandler = (event: MessageEvent) => {
        const data = event.data
        if (data.type === 'fileUploaded') {
          const { name, url, path: filePath, size, type } = data.payload
          if (name === file.name && size === file.size) {
            window.removeEventListener('message', messageHandler)
            resolve({ name, url, path: filePath, size, type } as UploadResult)
          }
        } else if (data.type === 'error') {
          // 检查是否与此文件相关（通过文件名匹配）
          if (data.payload?.fileName === file.name) {
            window.removeEventListener('message', messageHandler)
            reject(new Error(data.payload?.message || '上传失败'))
          }
        }
      }

      window.addEventListener('message', messageHandler)

      // 发送上传请求到扩展
      postMessage({
        type: 'uploadFile',
        payload: {
          fileName: file.name,
          fileType: file.type,
          base64Data: base64,
          fileSize: file.size,
        },
      })

      // 超时处理（5分钟）
      setTimeout(() => {
        window.removeEventListener('message', messageHandler)
        reject(new Error('上传超时'))
      }, 5 * 60 * 1000)
    } catch (error: any) {
      reject(error)
    }
  })
}
