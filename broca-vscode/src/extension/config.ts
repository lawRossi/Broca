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

  getAll(): Record<string, string> {
    return {
      serverUrl: this.serverUrl,
      wsUrl: this.wsUrl,
    }
  }

  async setAll(config: Record<string, string>): Promise<void> {
    const promises = Object.entries(config).map(([key, value]) => this.set(key, value))
    await Promise.all(promises)
  }
}
