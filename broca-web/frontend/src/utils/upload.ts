/**
 * 统一文件上传模块
 * 全部使用 S3 兼容 API (AWS SDK)，统一支持：
 * - Supabase Storage (S3 兼容端点)
 * - Cloudflare R2 (S3 兼容)
 * 无需用户登录，路径为 uploads/日期/文件名
 *
 * 配置来源：运行时通过 API (GET /api/config/general) 获取 configs.json 中的 storage 分组，
 * 不再依赖构建时的 VITE_* 环境变量。
 */

import { S3Client, PutObjectCommand } from '@aws-sdk/client-s3'
import { sha256 as jsSha256 } from 'js-sha256'
import configApi, { type StorageConfig } from '@/api/config'
import { filesApi } from '@/api/files'

// ==================== 类型定义 ====================

export type StorageType = 'supabase' | 'cloudflare' | 'none'

export interface UploadResult {
  name: string
  url: string
  path: string
  size: number
  type: string
  /** S3 直传时的存储 key（云存储通道） */
  storage_key?: string
  /** 后端本地落盘时的绝对路径（无云存储通道） */
  local_path?: string
  /** 文件内容的 SHA-256（hex），用于构造 media ref */
  sha256?: string
}

interface S3Config {
  type: StorageType
  region: string
  endpoint: string
  bucket: string
  credentials: { accessKeyId: string; secretAccessKey: string }
  publicUrlBase: string // 公开访问的基础 URL
}

// ==================== 运行时配置获取 ====================

/** 从 API 获取并缓存存储配置 */
let cachedS3Config: S3Config | null = null
let cachedAt = 0
const CACHE_TTL = 30_000 // 已配置时 30 秒缓存
const NULL_CACHE_TTL = 5_000 // 未配置时 5 秒短期缓存

async function getStorageConfig(forceRefresh = false): Promise<S3Config | null> {
  const now = Date.now()
  if (!forceRefresh && cachedS3Config !== null && now - cachedAt < CACHE_TTL) {
    return cachedS3Config
  }
  if (cachedS3Config === null && !forceRefresh && now - cachedAt < NULL_CACHE_TTL) {
    return null
  }
  try {
    const general = await configApi.getGeneralConfig()
    const storage = general?.storage
    cachedS3Config = buildS3Config(storage)
    cachedAt = now
    return cachedS3Config
  } catch {
    return null
  }
}

/**
 * 根据 configs.json 的 storage 分组构建 S3 客户端配置
 */
function buildS3Config(storage?: StorageConfig): S3Config | null {
  if (!storage || !storage.backend) return null

  if (
    storage.backend === 'cloudflare' &&
    storage.cloudflare_account_id &&
    storage.cloudflare_access_key_id &&
    storage.cloudflare_secret_access_key
  ) {
    const accountId = storage.cloudflare_account_id
    const bucket = storage.cloudflare_bucket || 'upload'
    return {
      type: 'cloudflare',
      region: 'auto',
      endpoint: `https://${accountId}.r2.cloudflarestorage.com`,
      bucket,
      credentials: {
        accessKeyId: storage.cloudflare_access_key_id,
        secretAccessKey: storage.cloudflare_secret_access_key,
      },
      publicUrlBase:
        storage.cloudflare_public_url || `https://${bucket}.${accountId}.r2.dev`,
    }
  }

  if (
    storage.backend === 'supabase' &&
    storage.supabase_url &&
    storage.supabase_s3_access_key_id &&
    storage.supabase_s3_secret_access_key
  ) {
    const url = storage.supabase_url
    const bucket = storage.supabase_bucket || 'upload'
    return {
      type: 'supabase',
      region: 'auto',
      endpoint: `${url}/storage/v1/s3`,
      bucket,
      credentials: {
        accessKeyId: storage.supabase_s3_access_key_id,
        secretAccessKey: storage.supabase_s3_secret_access_key,
      },
      publicUrlBase: `${url}/storage/v1/object/public/${bucket}`,
    }
  }

  return null
}

// ==================== S3 客户端管理 ====================

/** 按配置标识缓存 S3 客户端实例，配置变更时自动重建 */
const clientCache = new Map<string, S3Client>()

function getClient(cfg: S3Config): S3Client {
  const cacheKey = `${cfg.endpoint}:${cfg.credentials.accessKeyId}`
  let client = clientCache.get(cacheKey)
  if (!client) {
    client = new S3Client({
      region: cfg.region,
      endpoint: cfg.endpoint,
      credentials: cfg.credentials,
      forcePathStyle: true,
    })
    clientCache.set(cacheKey, client)
  }
  return client
}

// ==================== 工具函数 ====================

/**
 * 生成唯一文件名（处理中文文件名，避免 Supabase S3 兼容接口报错）
 * 使用 encodeURIComponent 编码非 ASCII 字符，保留原始文件名信息且保证 ASCII 安全
 */
export function generateUniqueFilename(originalName: string): string {
  const parts = originalName.split('.')
  const extension = parts.length > 1 ? parts.pop() : ''
  const nameWithoutExt = parts.join('.')

  // 使用 URL 编码处理非 ASCII 字符（如中文），避免 S3 Key 编码问题
  const sanitizedName = encodeURIComponent(nameWithoutExt)

  const uniqueId = Math.random().toString(36).substring(6)
  return extension ? `${sanitizedName}_${uniqueId}.${extension}` : `${sanitizedName}_${uniqueId}`
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

// ==================== SHA-256 计算 ====================

/** 将 ArrayBuffer 转为小写 hex 字符串 */
function toHex(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  let hex = ''
  for (let i = 0; i < bytes.length; i++) {
    hex += bytes[i].toString(16).padStart(2, '0')
  }
  return hex
}

/**
 * 计算 ArrayBuffer 的 SHA-256（hex）。
 * 优先使用 Web Crypto（crypto.subtle，仅 secure context：https / localhost 可用）；
 * 非 secure context（http 非 localhost）或不可用时回退到纯 JS 实现 js-sha256，
 * 保证 sha256 始终可得，避免 media ref 无法构造。
 */
export async function computeSha256FromBuffer(buffer: ArrayBuffer): Promise<string> {
  if (typeof crypto !== 'undefined' && crypto.subtle && typeof crypto.subtle.digest === 'function') {
    try {
      const digest = await crypto.subtle.digest('SHA-256', buffer)
      return toHex(digest)
    } catch {
      // 非 secure context 等情况下 crypto.subtle 会抛错，回退到纯 JS 实现
    }
  }
  return jsSha256(new Uint8Array(buffer))
}

/** 计算 File 的 SHA-256（hex） */
export async function computeSha256(file: File): Promise<string> {
  return computeSha256FromBuffer(await file.arrayBuffer())
}

// ==================== 统一上传（双通道） ====================

/**
 * 上传单个文件。
 * - 配置了云存储 → S3 直传（浏览器直连，url 为公网地址，返回 storage_key）
 * - 未配置云存储 → POST /files/upload 后端本地落盘（返回 local_path）
 * 两种通道均返回 sha256，供后续构造 media ref 使用。
 * @param file 要上传的文件
 * @param customPath 自定义存储路径（可选，仅云存储通道使用，默认自动生成）
 * @returns 上传结果
 */
export async function uploadFile(file: File, customPath?: string): Promise<UploadResult> {
  const cfg = await getStorageConfig()
  if (cfg) {
    return uploadToS3(file, cfg, customPath)
  }
  return uploadToBackend(file)
}

/** S3 直传通道 */
async function uploadToS3(file: File, cfg: S3Config, customPath?: string): Promise<UploadResult> {
  const client = getClient(cfg)
  const path = customPath || generateStoragePath(file.name)

  // 将 File 转为 Uint8Array，避免 S3 SDK 对 Blob 误调用 getReader()
  const arrayBuffer = await file.arrayBuffer()
  const body = new Uint8Array(arrayBuffer)
  const sha256 = await computeSha256FromBuffer(arrayBuffer)

  const command = new PutObjectCommand({
    Bucket: cfg.bucket,
    Key: path,
    Body: body,
    ContentType: file.type,
  })

  await client.send(command)

  return {
    name: file.name,
    url: `${cfg.publicUrlBase}/${path}`,
    path,
    size: file.size,
    type: file.type,
    storage_key: path,
    sha256,
  }
}

/** 后端本地落盘通道（无云存储） */
async function uploadToBackend(file: File): Promise<UploadResult> {
  const formData = new FormData()
  formData.append('file', file, file.name)

  const data = await filesApi.uploadFile(formData)

  return {
    name: data.name,
    url: data.url,
    path: data.path,
    size: data.size,
    type: data.type,
    local_path: data.local_path,
    sha256: data.sha256,
  }
}

/**
 * 获取当前存储配置类型（异步）
 */
export async function getStorageType(): Promise<StorageType> {
  const cfg = await getStorageConfig()
  return cfg?.type ?? 'none'
}

/**
 * 检查存储是否已配置（异步）
 */
export async function isStorageConfigured(): Promise<boolean> {
  const cfg = await getStorageConfig()
  return cfg !== null
}


