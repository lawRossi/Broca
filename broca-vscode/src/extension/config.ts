import * as vscode from 'vscode'

export class ConfigManager {
  get(key: string): string {
    return vscode.workspace.getConfiguration('broca').get<string>(key) || ''
  }

  set(key: string, value: string): void {
    vscode.workspace.getConfiguration('broca').update(key, value, vscode.ConfigurationTarget.Global)
  }

  get serverUrl(): string {
    return this.get('serverUrl') || 'http://localhost:8000'
  }

  get wsUrl(): string {
    return this.get('wsUrl') || 'http://localhost:8000'
  }

  get supabaseUrl(): string {
    return this.get('supabaseUrl') || ''
  }

  get supabaseKey(): string {
    return this.get('supabaseKey') || ''
  }

  // Supabase S3 独立凭证（可选，默认用 anon key）
  get supabaseS3AccessKeyId(): string {
    return this.get('supabaseS3AccessKeyId') || ''
  }

  get supabaseS3SecretAccessKey(): string {
    return this.get('supabaseS3SecretAccessKey') || ''
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

  get defaultProvider(): string {
    return this.get('defaultProvider')
  }

  get defaultModel(): string {
    return this.get('defaultModel')
  }

  /**
   * 检测可用的存储后端类型
   */
  get storageType(): 'supabase' | 'cloudflare' | 'none' {
    if (this.cloudflareAccountId && this.cloudflareAccessKeyId && this.cloudflareSecretAccessKey && this.cloudflareBucket) {
      return 'cloudflare'
    }
    if (this.supabaseUrl && this.supabaseKey) {
      return 'supabase'
    }
    return 'none'
  }

  getAll(): Record<string, string> {
    return {
      serverUrl: this.serverUrl,
      wsUrl: this.wsUrl,
      supabaseUrl: this.supabaseUrl,
      supabaseKey: this.supabaseKey,
      supabaseS3AccessKeyId: this.supabaseS3AccessKeyId,
      supabaseS3SecretAccessKey: this.supabaseS3SecretAccessKey,
      cloudflareAccountId: this.cloudflareAccountId,
      cloudflareAccessKeyId: this.cloudflareAccessKeyId,
      cloudflareSecretAccessKey: this.cloudflareSecretAccessKey,
      cloudflareBucket: this.cloudflareBucket,
      cloudflarePublicUrl: this.cloudflarePublicUrl,
      defaultProvider: this.defaultProvider,
      defaultModel: this.defaultModel,
    }
  }

  setAll(config: Record<string, string>): void {
    for (const [key, value] of Object.entries(config)) {
      this.set(key, value)
    }
  }
}
