import * as vscode from 'vscode'
import { SessionTreeProvider } from './sessionTree'
import { ChatWebViewManager } from './chatWebView'
import { AuthManager } from './auth'
import { ConfigManager } from './config'

import { ApiClient } from './api'

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
      if (!authManager.isLoggedIn) {
        vscode.window.showErrorMessage('请先登录')
        return
      }
      chatWebViewManager.openCreateSessionDialog(() => {
        sessionTreeProvider.refresh()
      })
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

  // ==================== Crew Commands ====================

  context.subscriptions.push(
    vscode.commands.registerCommand('broca.submitCrew', async (item: any) => {
      const sessionId = typeof item === 'string' ? item : item?.id
      if (!sessionId) {
        vscode.window.showErrorMessage('请先选择一个会话')
        return
      }

      // Let user pick a YAML file from workspace crew_configs/
      const workspacePath = vscode.workspace.workspaceFolders?.[0]?.uri?.fsPath
      if (!workspacePath) {
        vscode.window.showErrorMessage('没有打开的工作目录')
        return
      }

      const uris = await vscode.window.showOpenDialog({
        canSelectFiles: true,
        canSelectFolders: false,
        canSelectMany: false,
        openLabel: '提交编排',
        filters: { 'YAML files': ['yaml', 'yml'] },
        defaultUri: vscode.Uri.file(workspacePath + '/crew_configs'),
      })

      if (!uris || uris.length === 0) return

      try {
        const result = await apiClient.submitCrew({ yaml_path: uris[0].fsPath, session_id: sessionId })
        vscode.window.showInformationMessage(`编排 '${result.crew_name}' 提交成功`)
        // Refresh crew panel if open
        vscode.commands.executeCommand('broca.openCrewList', sessionId)
      } catch (error: any) {
        vscode.window.showErrorMessage(`提交编排失败: ${error.message}`)
      }
    })
  )

  context.subscriptions.push(
    vscode.commands.registerCommand('broca.openCrewList', (sessionId?: string) => {
      if (!sessionId) {
        vscode.window.showErrorMessage('请先选择一个会话')
        return
      }
      chatWebViewManager.openCrewPanel(sessionId)
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
    if (authManager.isLoggedIn) {
      // Session restored
    } else {
      // Not logged in, show login popup directly
      authManager.login().then((success) => {
        if (success) {
          sessionTreeProvider.refresh()
        }
      })
    }
  }

  // Show login button in status bar when not logged in
  const loginStatusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100)
  loginStatusItem.text = '$(sign-in) Broca: Not Logged In'
  loginStatusItem.tooltip = 'Click to login to Broca'
  loginStatusItem.command = 'broca.login'
  loginStatusItem.show()

  // Update status bar when auth state changes
  const updateLoginStatus = () => {
    if (authManager.isLoggedIn) {
      loginStatusItem.text = '$(sign-in) Broca: Logged In'
      loginStatusItem.tooltip = `Logged in as ${authManager.username || authManager.userId}`
      loginStatusItem.command = 'broca.logout'
    } else {
      loginStatusItem.text = '$(sign-in) Broca: Not Logged In'
      loginStatusItem.tooltip = 'Click to login to Broca'
      loginStatusItem.command = 'broca.login'
    }
  }

  context.subscriptions.push(
    authManager.onDidChange(() => {
      updateLoginStatus()
      sessionTreeProvider.refresh()
    })
  )

  updateLoginStatus()

  // Initial load
  sessionTreeProvider.refresh()

  console.log('Broca extension activated')
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
    // Close any open chat/crew panels for this session
    chatWebViewManager.closeSessionPanel(sessionId)
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
