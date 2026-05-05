import * as vscode from 'vscode'
import { SessionTreeProvider } from './sessionTree'
import { ChatWebViewManager } from './chatWebView'
import { AuthManager } from './auth'
import { ConfigManager } from './config'

import { ApiClient } from './api'
import type { CreateSessionParams } from './types'

let authManager: AuthManager
let configManager: ConfigManager
let sessionTreeProvider: SessionTreeProvider
let chatWebViewManager: ChatWebViewManager
let apiClient: ApiClient

export async function activate(context: vscode.ExtensionContext) {
  console.log('Broca extension activating...')

  // Initialize managers (config first, auth depends on it)
  configManager = new ConfigManager()
  authManager = new AuthManager(context, configManager)

  // Initialize session tree provider
  sessionTreeProvider = new SessionTreeProvider(authManager, configManager)
  const treeView = vscode.window.createTreeView('broca.sessionManager', {
    treeDataProvider: sessionTreeProvider,
    showCollapseAll: false,
  })

  // Initialize Chat WebView manager
  chatWebViewManager = new ChatWebViewManager(context, authManager, configManager)
  apiClient = new ApiClient(configManager, () => authManager.token)

  // Register commands
  context.subscriptions.push(
    vscode.commands.registerCommand('broca.login', async () => {
      await authManager.login()
      sessionTreeProvider.refresh()
    })
  )

  context.subscriptions.push(
    vscode.commands.registerCommand('broca.logout', async () => {
      await authManager.logout()
      sessionTreeProvider.refresh()
    })
  )

  context.subscriptions.push(
    vscode.commands.registerCommand('broca.createSession', async () => {
      await handleCreateSession()
    })
  )

  context.subscriptions.push(
    vscode.commands.registerCommand('broca.openChat', (sessionId?: string) => {
      if (sessionId) {
        chatWebViewManager.openChat(sessionId)
      }
    })
  )

  context.subscriptions.push(
    vscode.commands.registerCommand('broca.deleteSession', async (sessionId: string) => {
      await handleDeleteSession(sessionId)
    })
  )

  context.subscriptions.push(
    vscode.commands.registerCommand('broca.refreshSessions', () => {
      sessionTreeProvider.refresh()
    })
  )

  context.subscriptions.push(
    vscode.commands.registerCommand('broca.configure', () => {
      chatWebViewManager.openConfigPage()
    })
  )

  // Additional context menu commands
  context.subscriptions.push(
    vscode.commands.registerCommand('broca.copySessionId', async (item: any) => {
      const sessionId = typeof item === 'string' ? item : item?.id
      if (sessionId) {
        await vscode.env.clipboard.writeText(sessionId)
        vscode.window.showInformationMessage('Session ID copied to clipboard')
      }
    })
  )

  context.subscriptions.push(
    vscode.commands.registerCommand('broca.copySessionWorkspace', async (item: any) => {
      const sessionId = typeof item === 'string' ? item : item?.id
      const session = sessionId ? await sessionTreeProvider.getSessionById(sessionId) : undefined
      if (session?.workspace) {
        await vscode.env.clipboard.writeText(session.workspace)
        vscode.window.showInformationMessage('Workspace path copied to clipboard')
      } else {
        vscode.window.showWarningMessage('Session has no workspace')
      }
    })
  )

  context.subscriptions.push(
    vscode.commands.registerCommand('broca.restartRunner', async (item: any) => {
      const sessionId = typeof item === 'string' ? item : item?.id
      if (!sessionId) return
      try {
        await apiClient.restartRunner(sessionId)
        vscode.window.showInformationMessage('Runner restarting...')
      } catch (error: any) {
        vscode.window.showErrorMessage(`Failed to restart runner: ${error.message}`)
      }
    })
  )

  context.subscriptions.push(
    vscode.commands.registerCommand('broca.stopRunner', async (item: any) => {
      const sessionId = typeof item === 'string' ? item : item?.id
      if (!sessionId) return
      try {
        await apiClient.stopRunner(sessionId)
        vscode.window.showInformationMessage('Runner stopped')
      } catch (error: any) {
        vscode.window.showErrorMessage(`Failed to stop runner: ${error.message}`)
      }
    })
  )

  context.subscriptions.push(
    vscode.commands.registerCommand('broca.signUp', async () => {
      await authManager.signUp()
    })
  )

  // Auth state change listener
  context.subscriptions.push(
    authManager.onDidChange(() => {
      sessionTreeProvider.refresh()
    })
  )

  // Initial login check
  if (!authManager.isLoggedIn) {
    // Try silent login from stored session
    try {
      await authManager.tryRestoreSession()
    } catch {
      // Not logged in, show info
      vscode.window.showInformationMessage(
        'Welcome to Broca! Please login to get started.',
        'Login'
      ).then((selection) => {
        if (selection === 'Login') {
          vscode.commands.executeCommand('broca.login')
        }
      })
    }
  }

  // Initial load
  sessionTreeProvider.refresh()

  console.log('Broca extension activated')
}

async function handleCreateSession() {
  if (!authManager.isLoggedIn) {
    vscode.window.showErrorMessage('Please login first')
    return
  }

  // Get current workspace path
  const workspacePath = vscode.workspace.workspaceFolders?.[0]?.uri?.fsPath || ''

  // Ask for description
  const description = await vscode.window.showInputBox({
    prompt: 'Session description (optional)',
    placeHolder: 'e.g., Debug the login issue',
    ignoreFocusOut: true,
  })

  if (description === undefined) return // User cancelled

  // Get default config
  const defaultProvider = configManager.get('defaultProvider')
  const defaultModel = configManager.get('defaultModel')

  try {
    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: 'Creating session...',
        cancellable: false,
      },
      async () => {
        await apiClient.createSession({
          description: description || undefined,
          workspace: workspacePath || undefined,
          provider: defaultProvider || undefined,
          model: defaultModel || undefined,
        })
      }
    )

    vscode.window.showInformationMessage('Session created successfully')
    sessionTreeProvider.refresh()
  } catch (error: any) {
    vscode.window.showErrorMessage(`Failed to create session: ${error.message || 'Unknown error'}`)
  }
}

async function handleDeleteSession(item: any) {
  // When triggered from inline button, VSCode passes the TreeItem object
  // Extract session ID from TreeItem.id or use directly if it's a string
  const sessionId = typeof item === 'string' ? item : item?.id || item?.sessionId
  if (!sessionId) {
    vscode.window.showErrorMessage('Could not determine session ID')
    return
  }

  const confirmed = await vscode.window.showWarningMessage(
    'Are you sure you want to delete this session? This action cannot be undone.',
    { modal: true },
    'Delete'
  )

  if (confirmed !== 'Delete') return

  try {
    await apiClient.deleteSession(sessionId)
    sessionTreeProvider.refresh()
  } catch (error: any) {
    vscode.window.showErrorMessage(`Failed to delete session: ${error.message || 'Unknown error'}`)
  }
}

export function deactivate() {
  console.log('Broca extension deactivating...')
  authManager?.dispose()
  sessionTreeProvider?.dispose()
  chatWebViewManager?.dispose()
}
