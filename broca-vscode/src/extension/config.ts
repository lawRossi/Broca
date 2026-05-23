import * as vscode from 'vscode'

export class ConfigManager {
  get(key: string): string {
    return vscode.workspace.getConfiguration('broca').get<string>(key) || ''
  }

  set(key: string, value: string): Thenable<void> {
    return vscode.workspace.getConfiguration('broca').update(key, value, vscode.ConfigurationTarget.Global)
  }

  get serverUrl(): string {
    return this.get('serverUrl') || 'http://localhost:8000'
  }

  get wsUrl(): string {
    return this.get('wsUrl') || 'http://localhost:8000'
  }

  // Cloudflare R2 配置
  get cloudflareAccountId(): string {
    return this.get('cloudflareAccountId') || ''
  }

  get cloudflareAccessKeyId(): string {
    return this.get('cloudflareAccessKeyId') || ''
  }

  get cloudflareSecretAccessKey(): string {
    return this.get('cloudflareSecretAccessKey') || ''
  }

  get cloudflareBucket(): string {
    return this.get('cloudflareBucket') || ''
  }

  get cloudflarePublicUrl(): string {
    return this.get('cloudflarePublicUrl') || ''
  }

  // Supabase S3 兼容配置（可选存储后端）
  get supabaseUrl(): string {
    return this.get('supabaseUrl') || ''
  }

  get supabaseS3AccessKeyId(): string {
    return this.get('supabaseS3AccessKeyId') || ''
  }

  get supabaseS3SecretAccessKey(): string {
    return this.get('supabaseS3SecretAccessKey') || ''
  }

  get defaultProvider(): string {
    return this.get('defaultProvider')
  }

  get defaultModel(): string {
    return this.get('defaultModel')
  }

  /**
   * 检测可用的存储后端类型
   */
  get storageType(): 'cloudflare' | 'supabase' | 'none' {
    if (this.cloudflareAccountId && this.cloudflareAccessKeyId && this.cloudflareSecretAccessKey && this.cloudflareBucket) {
      return 'cloudflare'
    }
    if (this.supabaseUrl && this.supabaseS3AccessKeyId && this.supabaseS3SecretAccessKey) {
      return 'supabase'
    }
    return 'none'
  }

  getAll(): Record<string, string> {
    return {
      serverUrl: this.serverUrl,
      wsUrl: this.wsUrl,
      cloudflareAccountId: this.cloudflareAccountId,
      cloudflareAccessKeyId: this.cloudflareAccessKeyId,
      cloudflareSecretAccessKey: this.cloudflareSecretAccessKey,
      cloudflareBucket: this.cloudflareBucket,
      cloudflarePublicUrl: this.cloudflarePublicUrl,
      supabaseUrl: this.supabaseUrl,
      supabaseS3AccessKeyId: this.supabaseS3AccessKeyId,
      supabaseS3SecretAccessKey: this.supabaseS3SecretAccessKey,
      defaultProvider: this.defaultProvider,
      defaultModel: this.defaultModel,
    }
  }

  async setAll(config: Record<string, string>): Promise<void> {
    const promises = Object.entries(config).map(([key, value]) => this.set(key, value))
    await Promise.all(promises)
  }
}
