/**
 * 统一文件上传模块
 * 全部使用 S3 兼容 API (AWS SDK)，统一支持：
 * - Supabase Storage (S3 兼容端点)
 * - Cloudflare R2 (S3 兼容)
 * 无需用户登录，路径为 uploads/日期/文件名
 */

import { S3Client, PutObjectCommand } from '@aws-sdk/client-s3'

// ==================== 类型定义 ====================

export type StorageType = 'supabase' | 'cloudflare' | 'none'

export interface UploadResult {
  name: string
  url: string
  path: string
  size: number
  type: string
}

interface S3Config {
  type: StorageType
  region: string
  endpoint: string
  bucket: string
  credentials: { accessKeyId: string; secretAccessKey: string }
  publicUrlBase: string // 公开访问的基础 URL
}

// ==================== 配置检测 ====================

function detectConfig(): S3Config | null {
  // 1. Cloudflare R2（优先）
  const cfAccountId = import.meta.env.VITE_CLOUDFLARE_ACCOUNT_ID as string | undefined
  const cfAccessKey = import.meta.env.VITE_CLOUDFLARE_ACCESS_KEY_ID as string | undefined
  const cfSecretKey = import.meta.env.VITE_CLOUDFLARE_SECRET_ACCESS_KEY as string | undefined
  const cfBucket = (import.meta.env.VITE_CLOUDFLARE_BUCKET as string) || 'upload'
  const cfPublicUrl = import.meta.env.VITE_CLOUDFLARE_PUBLIC_URL as string | undefined

  if (cfAccountId && cfAccessKey && cfSecretKey) {
    return {
      type: 'cloudflare',
      region: 'auto',
      endpoint: `https://${cfAccountId}.r2.cloudflarestorage.com`,
      bucket: cfBucket,
      credentials: { accessKeyId: cfAccessKey, secretAccessKey: cfSecretKey },
      publicUrlBase: cfPublicUrl || `https://${cfBucket}.${cfAccountId}.r2.dev`,
    }
  }

  // 2. Supabase Storage（S3 兼容）
  const supabaseUrl = import.meta.env.VITE_SUPABASE_URL as string | undefined
  const supabaseKey = import.meta.env.VITE_SUPABASE_KEY as string | undefined
  const supabaseBucket = (import.meta.env.VITE_SUPABASE_BUCKET as string) || 'upload'

  if (supabaseUrl && supabaseKey) {
    // S3 凭证：优先使用独立配置，否则回退到 anon key
    const s3AccessKey = (import.meta.env.VITE_SUPABASE_S3_ACCESS_KEY_ID as string) || supabaseKey
    const s3SecretKey = (import.meta.env.VITE_SUPABASE_S3_SECRET_ACCESS_KEY as string) || supabaseKey

    return {
      type: 'supabase',
      region: 'auto',
      endpoint: `${supabaseUrl}/storage/v1/s3`,
      bucket: supabaseBucket,
      credentials: { accessKeyId: s3AccessKey, secretAccessKey: s3SecretKey },
      publicUrlBase: `${supabaseUrl}/storage/v1/object/public/${supabaseBucket}`,
    }
  }

  console.warn('[Upload] No storage configuration found. Set VITE_CLOUDFLARE_* or VITE_SUPABASE_* env vars.')
  return null
}

// 模块初始化时立即检测配置，确保 isStorageConfigured() 等函数可正确判断
const s3Config: S3Config | null = detectConfig()

// S3 客户端延迟初始化（仅在首次上传时创建）
let s3Client: S3Client | null = null

function getClient(): S3Client {
  if (!s3Client) {
    if (!s3Config) throw new Error('No storage backend configured.')
    s3Client = new S3Client({
      region: s3Config.region,
      endpoint: s3Config.endpoint,
      credentials: s3Config.credentials,
      forcePathStyle: true,
    })
  }
  return s3Client
}

// ==================== 工具函数 ====================

/**
 * 生成唯一文件名
 */
export function generateUniqueFilename(originalName: string): string {
  const parts = originalName.split('.')
  const extension = parts.length > 1 ? parts.pop() : ''
  const nameWithoutExt = parts.join('.')
  const uniqueId = Math.random().toString(36).substring(6)
  return extension ? `${nameWithoutExt}_${uniqueId}.${extension}` : `${nameWithoutExt}_${uniqueId}`
}

/**
 * 生成存储路径 (不含 userId，仅基于日期)
 */
export function generateStoragePath(originalName: string): string {
  const safeFilename = generateUniqueFilename(originalName)
  const now = new Date()
  const year = now.getFullYear()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `uploads/${year}${month}${day}/${safeFilename}`
}

// ==================== 统一 S3 上传 ====================

/**
 * 上传单个文件（统一 S3 API，兼容 Supabase 和 Cloudflare R2）
 * @param file 要上传的文件
 * @param customPath 自定义存储路径（可选，默认自动生成）
 * @returns 上传结果
 */
export async function uploadFile(file: File, customPath?: string): Promise<UploadResult> {
  const client = getClient()
  if (!s3Config) throw new Error('No storage backend configured.')

  const path = customPath || generateStoragePath(file.name)

  // 将 File 转为 Uint8Array，避免 S3 SDK 对 Blob 误调用 getReader()
  const arrayBuffer = await file.arrayBuffer()
  const body = new Uint8Array(arrayBuffer)

  const command = new PutObjectCommand({
    Bucket: s3Config.bucket,
    Key: path,
    Body: body,
    ContentType: file.type,
  })

  await client.send(command)

  return {
    name: file.name,
    url: `${s3Config.publicUrlBase}/${path}`,
    path,
    size: file.size,
    type: file.type,
  }
}

/**
 * 获取当前存储配置类型
 */
export function getStorageType(): StorageType {
  return s3Config?.type ?? 'none'
}

/**
 * 检查存储是否已配置
 */
export function isStorageConfigured(): boolean {
  return s3Config !== null
}
