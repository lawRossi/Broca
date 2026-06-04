import * as vscode from 'vscode'
import { ApiClient } from './api'
import { ConfigManager } from './config'

export type AuthStateChangeHandler = (loggedIn: boolean) => void

export class AuthManager {
  private _isLoggedIn = false
  private _userId: string | null = null
  private _token: string | null = null
  private _username: string | null = null
  private context: vscode.ExtensionContext
  private configManager: ConfigManager
  private apiClient: ApiClient
  private onDidChangeEvent = new vscode.EventEmitter<void>()

  readonly onDidChange: vscode.Event<void> = this.onDidChangeEvent.event

  constructor(context: vscode.ExtensionContext, configManager: ConfigManager) {
    this.context = context
    this.configManager = configManager
    this.apiClient = new ApiClient(configManager, () => this._token)

    // 从持久化存储恢复会话
    this.restoreSession()
  }

  private restoreSession(): void {
    const token = this.context.globalState.get<string>('token')
    const userId = this.context.globalState.get<string>('userId')
    const username = this.context.globalState.get<string>('username')

    if (token && userId) {
      this._token = token
      this._userId = userId
      this._username = username || null
      this._isLoggedIn = true
      console.log('[Auth] Session restored for user:', username || userId)
    }
  }

  private persistSession(): void {
    if (this._token && this._userId) {
      this.context.globalState.update('token', this._token)
      this.context.globalState.update('userId', this._userId)
      this.context.globalState.update('username', this._username)
    }
  }

  private clearSession(): void {
    this.context.globalState.update('token', undefined)
    this.context.globalState.update('userId', undefined)
    this.context.globalState.update('username', undefined)
  }

  get isLoggedIn(): boolean {
    return this._isLoggedIn
  }

  get userId(): string | null {
    return this._userId
  }

  get token(): string | null {
    return this._token
  }

  get username(): string | null {
    return this._username
  }

  /**
   * 重新配置（配置变更后调用）
   */
  reconfigure(): void {
    // 不改变登录状态，仅重新初始化 API client
    this.apiClient = new ApiClient(this.configManager, () => this._token)
  }

  async login(): Promise<boolean> {
    const username = await vscode.window.showInputBox({
      prompt: '用户名',
      placeHolder: '请输入用户名',
      ignoreFocusOut: true,
      validateInput: (value) => {
        if (!value || value.length < 2) return '用户名至少需要2个字符'
        return null
      },
    })
    if (!username) return false

    const password = await vscode.window.showInputBox({
      prompt: '密码',
      password: true,
      ignoreFocusOut: true,
      validateInput: (value) => {
        if (!value || value.length < 6) return '密码至少需要6个字符'
        return null
      },
    })
    if (!password) return false

    try {
      await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: '登录中...' },
        async () => {
          const response = await this.apiClient.login(username, password)
          this._token = response.token
          this._userId = response.user_id
          this._username = response.username
          this._isLoggedIn = true
          this.persistSession()
        }
      )
      vscode.window.showInformationMessage(`登录成功！欢迎 ${this._username}`)
      this.onDidChangeEvent.fire()
      return true
    } catch (error: any) {
      // Extract meaningful error message from various response formats
      const respData = error?.response?.data
      const msg =
        respData?.detail ||
        respData?.msg ||
        respData?.message ||
        (typeof respData === 'string' ? respData : null) ||
        error.message ||
        '登录失败'
      vscode.window.showErrorMessage(`登录失败: ${msg}`)
      return false
    }
  }

  // 注册功能已移除：请在安装时通过 scripts/setup_admin.py 创建账户

  async logout(): Promise<void> {
    this._isLoggedIn = false
    this._token = null
    this._userId = null
    this._username = null
    this.clearSession()
    vscode.window.showInformationMessage('已登出')
    this.onDidChangeEvent.fire()
  }

  /**
   * Handle 401 (Unauthorized) error — automatically log out and prompt re-login.
   *
   * This is called by ApiClient/SocketClient when a 401 response is received,
   * indicating the token has expired or is invalid. The method:
   * 1. Clears the stored session
   * 2. Fires auth state change event (so UI refreshes)
   * 3. Shows an error notification with a "Login" action for quick re-authentication
   */
  async handleAuthError(): Promise<void> {
    // 1. Clear session silently (no "已登出" toast — confusing in error scenario)
    const wasLoggedIn = this._isLoggedIn
    this._isLoggedIn = false
    this._token = null
    this._userId = null
    this._username = null
    this.clearSession()

    // Fire state change so UI knows we're logged out (regardless of whether we were logged in before)
    this.onDidChangeEvent.fire()

    // 2. Show error notification with "Login" action button for quick re-auth
    //    Always show the prompt — even if wasLoggedIn was false (edge case where token is invalid)
    const action = await vscode.window.showErrorMessage(
      '登录已过期或未经授权，请重新登录',
      { modal: false },
      '登录'
    )

    if (action === '登录') {
      await this.login()
    }
  }

  dispose() {
    this.onDidChangeEvent.dispose()
  }
}
