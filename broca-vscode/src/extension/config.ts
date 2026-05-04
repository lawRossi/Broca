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

  get defaultProvider(): string {
    return this.get('defaultProvider')
  }

  get defaultModel(): string {
    return this.get('defaultModel')
  }

  getAll(): Record<string, string> {
    return {
      serverUrl: this.serverUrl,
      wsUrl: this.wsUrl,
      supabaseUrl: this.supabaseUrl,
      supabaseKey: this.supabaseKey,
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
