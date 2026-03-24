import { createClient, SupabaseClient } from '@supabase/supabase-js'
import { S3Client, PutObjectCommand } from '@aws-sdk/client-s3'

// Supabase 配置
const supabaseUrl = import.meta.env.VITE_SUPABASE_URL as string
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_KEY as string

if (!supabaseUrl || !supabaseAnonKey) {
  throw new Error('Supabase URL and Anon Key must be provided in environment variables')
}

// AWS S3 配置 (使用 Supabase S3 兼容端点)
const s3Client = new S3Client({
  region: 'auto', // Supabase 使用 'auto' 区域
  endpoint: `${supabaseUrl}/storage/v1/s3`,
  credentials: {
    accessKeyId: supabaseAnonKey, // 使用 Supabase anon key 作为 access key
    secretAccessKey: supabaseAnonKey, // Supabase storage 使用相同的 key
  },
  forcePathStyle: true, // 强制使用路径样式 URL
})

// 创建 Supabase 客户端
const supabase: SupabaseClient = createClient(supabaseUrl, supabaseAnonKey, {
  auth: {
    autoRefreshToken: true,
    persistSession: true,
    detectSessionInUrl: true,
  },
})

// 认证工具类
class SupabaseAuth {
  // 用户注册
  static async signUp(email: string, password: string, redirectTo?: string) {
    console.log(redirectTo)
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        emailRedirectTo: redirectTo || `${window.location.origin}/auth/callback`,
      },
    })
    if (error) throw error
    return data
  }

  // 重新发送确认邮件
  static async resendConfirmation(email: string, redirectTo?: string) {
    const { error } = await supabase.auth.resend({
      type: 'signup',
      email,
      options: {
        emailRedirectTo: redirectTo || `${window.location.origin}/auth/callback`,
      },
    })
    if (error) throw error
  }

  // 用户登录
  static async signIn(email: string, password: string) {
    const { data, error } = await supabase.auth.signInWithPassword({
      email,
      password,
    })
    if (error) throw error
    return data
  }

  // 登出
  static async signOut() {
    const { error } = await supabase.auth.signOut()
    if (error) throw error
  }

  // 获取当前用户
  static async getCurrentUser() {
    const {
      data: { user },
      error,
    } = await supabase.auth.getUser()
    if (error) throw error
    return user
  }

  // 获取当前会话
  static async getSession() {
    const {
      data: { session },
      error,
    } = await supabase.auth.getSession()
    if (error) throw error
    return session
  }

  // 监听认证状态变化
  static onAuthStateChange(callback: (event: string, session: any) => void) {
    return supabase.auth.onAuthStateChange(callback)
  }

  // 重置密码
  static async resetPassword(email: string, redirectTo?: string) {
    const { error } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: redirectTo || `${window.location.origin}/reset-password`,
    })
    if (error) throw error
  }
}

// 数据库工具类
class SupabaseDB {
  // 查询数据
  static async select(table: string, columns = '*', filters?: Record<string, any>) {
    let query = supabase.from(table).select(columns)

    if (filters) {
      Object.entries(filters).forEach(([key, value]) => {
        query = query.eq(key, value)
      })
    }

    const { data, error } = await query
    if (error) throw error
    return data
  }

  // 插入数据
  static async insert(table: string, data: Record<string, any> | Record<string, any>[]) {
    const { data: insertedData, error } = await supabase.from(table).insert(data).select()

    if (error) throw error
    return insertedData
  }

  // 更新数据
  static async update(table: string, data: Record<string, any>, filters: Record<string, any>) {
    let query = supabase.from(table).update(data)

    Object.entries(filters).forEach(([key, value]) => {
      query = query.eq(key, value)
    })

    const { data: updatedData, error } = await query.select()
    if (error) throw error
    return updatedData
  }

  // 删除数据
  static async delete(table: string, filters: Record<string, any>) {
    let query = supabase.from(table).delete()

    Object.entries(filters).forEach(([key, value]) => {
      query = query.eq(key, value)
    })

    const { error } = await query
    if (error) throw error
  }

  // 实时订阅
  static subscribe(table: string, callback: (payload: any) => void, filters?: Record<string, any>) {
    let channel = supabase
      .channel(`${table}_changes`)
      .on(
        'postgres_changes',
        {
          event: '*',
          schema: 'public',
          table: table,
          filter: filters
            ? Object.entries(filters)
                .map(([key, value]) => `${key}=eq.${value}`)
                .join(',')
            : undefined,
        },
        callback
      )
      .subscribe()

    return channel
  }
}

// 存储工具类
class SupabaseStorage {
  // 上传文件
  static async upload(bucket: string, path: string, file: File) {
    const { data, error } = await supabase.storage.from(bucket).upload(path, file)

    if (error) throw error
    return data
  }

  // 下载文件
  static async download(bucket: string, path: string) {
    const { data, error } = await supabase.storage.from(bucket).download(path)

    if (error) throw error
    return data
  }

  // 获取公开URL
  static getPublicUrl(bucket: string, path: string) {
    const { data } = supabase.storage.from(bucket).getPublicUrl(path)

    return data.publicUrl
  }

  // 删除文件
  static async remove(bucket: string, paths: string[]) {
    const { error } = await supabase.storage.from(bucket).remove(paths)

    if (error) throw error
  }

  // 列出文件
  static async list(bucket: string, path?: string, options?: { limit?: number; offset?: number }) {
    const { data, error } = await supabase.storage.from(bucket).list(path, options)

    if (error) throw error
    return data
  }
  // 生成唯一文件名
  static generateUniqueFilename(originalName: string): string {
    const parts = originalName.split('.')
    const extension = parts.length > 1 ? parts.pop() : ''
    const nameWithoutExt = parts.join('.')
    const uniqueId = Math.random().toString(36).substr(6)
    return extension ? `${nameWithoutExt}_${uniqueId}.${extension}` : `${nameWithoutExt}_${uniqueId}`
  }

  // 上传文件到 S3 (通过 Supabase Storage)
  static async uploadToS3(bucket: string, key: string, file: File) {
    const command = new PutObjectCommand({
      Bucket: bucket,
      Key: key,
      Body: file,
      ContentType: file.type,
    })

    const result = await s3Client.send(command)
    return result
  }
}

// 导出工具类和客户端
export { supabase, SupabaseAuth, SupabaseDB, SupabaseStorage }
export default supabase
