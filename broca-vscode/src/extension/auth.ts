import * as vscode from 'vscode'
import { createClient, type SupabaseClient, type AuthChangeEvent, type Session } from '@supabase/supabase-js'
import { ConfigManager } from './config'

export type AuthStateChangeHandler = (loggedIn: boolean) => void

export class AuthManager {
  private supabase: SupabaseClient | null = null
  private _isLoggedIn = false
  private _userId: string | null = null
  private _token: string | null = null
  private context: vscode.ExtensionContext
  private configManager: ConfigManager
  private onDidChangeEvent = new vscode.EventEmitter<void>()

  readonly onDidChange: vscode.Event<void> = this.onDidChangeEvent.event

  constructor(context: vscode.ExtensionContext, configManager: ConfigManager) {
    this.context = context
    this.configManager = configManager
    this.initSupabase()
  }

  private initSupabase() {
    const supabaseUrl = this.configManager.supabaseUrl
    const supabaseKey = this.configManager.supabaseKey

    if (!supabaseUrl || !supabaseKey) {
      console.warn('Supabase not configured. Please set broca.supabaseUrl and broca.supabaseKey in settings.')
      this.supabase = null
      return
    }

    this.supabase = createClient(supabaseUrl, supabaseKey, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        storage: {
          getItem: (key: string) => {
            return this.context.globalState.get<string>(key) || null
          },
          setItem: (key: string, value: string) => {
            this.context.globalState.update(key, value)
          },
          removeItem: (key: string) => {
            this.context.globalState.update(key, undefined)
          },
        },
      },
    })

    // Listen for auth state changes
    this.supabase.auth.onAuthStateChange((event: AuthChangeEvent, session: Session | null) => {
      if (session) {
        this._isLoggedIn = true
        this._userId = session.user.id
        this._token = session.access_token
      } else {
        this._isLoggedIn = false
        this._userId = null
        this._token = null
      }
      this.onDidChangeEvent.fire()
    })
  }

  /**
   * Re-initialize Supabase client after config changes (e.g. user sets URL/key via settings page)
   */
  reconfigure(): void {
    const wasLoggedIn = this._isLoggedIn
    // Dispose old client
    this.supabase = null
    this._isLoggedIn = false
    this._userId = null
    this._token = null
    // Re-init with new config
    this.initSupabase()
    // Try to restore session after reconfig
    if (!wasLoggedIn) {
      this.tryRestoreSession()
    }
    this.onDidChangeEvent.fire()
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

  get supabaseClient(): SupabaseClient | null {
    return this.supabase
  }

  async tryRestoreSession(): Promise<boolean> {
    if (!this.supabase) return false

    try {
      const { data: { session } } = await this.supabase.auth.getSession()
      if (session) {
        this._isLoggedIn = true
        this._userId = session.user.id
        this._token = session.access_token
        return true
      }
    } catch (error) {
      console.error('Failed to restore session:', error)
    }
    return false
  }

  async login(): Promise<boolean> {
    if (!this.supabase) {
      vscode.window.showErrorMessage(
        'Supabase is not configured. Please set broca.supabaseUrl and broca.supabaseKey in settings.'
      )
      return false
    }

    // Show login dialog
    const email = await vscode.window.showInputBox({
      prompt: 'Email',
      placeHolder: 'your@email.com',
      ignoreFocusOut: true,
      validateInput: (value) => {
        if (!value.includes('@')) return 'Please enter a valid email'
        return null
      },
    })

    if (!email) return false

    const password = await vscode.window.showInputBox({
      prompt: 'Password',
      password: true,
      ignoreFocusOut: true,
      validateInput: (value) => {
        if (!value || value.length < 6) return 'Password must be at least 6 characters'
        return null
      },
    })

    if (!password) return false

    try {
      await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: 'Logging in...' },
        async () => {
          const { data, error } = await this.supabase!.auth.signInWithPassword({ email, password })
          if (error) throw error
        }
      )
      vscode.window.showInformationMessage('Login successful!')
      return true
    } catch (error: any) {
      vscode.window.showErrorMessage(`Login failed: ${error.message || 'Unknown error'}`)
      return false
    }
  }

  async signUp(): Promise<boolean> {
    if (!this.supabase) {
      vscode.window.showErrorMessage('Supabase is not configured.')
      return false
    }

    const email = await vscode.window.showInputBox({
      prompt: 'Email',
      placeHolder: 'your@email.com',
      ignoreFocusOut: true,
    })

    if (!email) return false

    const password = await vscode.window.showInputBox({
      prompt: 'Password (min 6 characters)',
      password: true,
      ignoreFocusOut: true,
    })

    if (!password) return false

    try {
      const { data, error } = await this.supabase.auth.signUp({
        email,
        password,
        options: {
          emailRedirectTo: undefined, // No need for VSCode
        },
      })

      if (error) throw error

      if (data.user && !data.session) {
        vscode.window.showInformationMessage(
          'Registration successful! Please check your email to confirm your account.',
          'OK'
        )
      } else {
        vscode.window.showInformationMessage('Registration successful!')
      }
      return true
    } catch (error: any) {
      vscode.window.showErrorMessage(`Registration failed: ${error.message || 'Unknown error'}`)
      return false
    }
  }

  async logout(): Promise<void> {
    if (!this.supabase) return

    try {
      await this.supabase.auth.signOut()
      this._isLoggedIn = false
      this._userId = null
      this._token = null
      vscode.window.showInformationMessage('Logged out successfully')
    } catch (error: any) {
      console.error('Logout error:', error)
      // Force clear local state
      this._isLoggedIn = false
      this._userId = null
      this._token = null
    }
    this.onDidChangeEvent.fire()
  }

  dispose() {
    this.onDidChangeEvent.dispose()
  }
}
