import * as vscode from 'vscode'
import { AuthManager } from './auth'
import { ConfigManager } from './config'
import { ApiClient } from './api'
import type { Session } from './types'

class SessionTreeItem extends vscode.TreeItem {
  constructor(
    public readonly session: Session,
    public readonly collapsibleState: vscode.TreeItemCollapsibleState
  ) {
    super(session.description || session.session_id.slice(0, 8), collapsibleState)

    this.id = session.session_id
    this.contextValue = 'session'
    this.tooltip = this.buildTooltip(session)

    // Description shows truncated session ID
    this.description = session.session_id.length > 16
      ? `${session.session_id.slice(0, 8)}...${session.session_id.slice(-8)}`
      : session.session_id

    // Set icon based on runner status
    this.iconPath = this.getStatusIcon(session.runner_status)

    // Command when clicking the item
    this.command = {
      command: 'broca.openChat',
      title: 'Open Chat',
      arguments: [session.session_id],
    }
  }

  private buildTooltip(session: Session): vscode.MarkdownString {
    const tooltip = new vscode.MarkdownString(undefined, true)
    tooltip.appendMarkdown(`**Session**: \`${session.session_id}\`\n\n`)
    if (session.description) {
      tooltip.appendMarkdown(`**Description**: ${session.description}\n\n`)
    }
    if (session.workspace) {
      tooltip.appendMarkdown(`**Workspace**: \`${session.workspace}\`\n\n`)
    }
    tooltip.appendMarkdown(`**Created**: ${new Date(session.created_at).toLocaleString()}\n\n`)
    tooltip.appendMarkdown(`**Runner**: ${session.runner_status || 'unknown'}`)
    return tooltip
  }

  private getStatusIcon(status?: string): vscode.ThemeIcon {
    switch (status) {
      case 'alive':
        return new vscode.ThemeIcon('debug-start', new vscode.ThemeColor('testing.iconPassed'))
      case 'starting':
        return new vscode.ThemeIcon('debug-stopped', new vscode.ThemeColor('testing.iconQueued'))
      case 'error':
        return new vscode.ThemeIcon('warning', new vscode.ThemeColor('testing.iconFailed'))
      case 'dead':
      case 'none':
      default:
        return new vscode.ThemeIcon('circle-outline')
    }
  }
}

export class SessionTreeProvider implements vscode.TreeDataProvider<SessionTreeItem> {
  private _onDidChangeTreeData = new vscode.EventEmitter<SessionTreeItem | undefined | null | void>()
  readonly onDidChangeTreeData: vscode.Event<SessionTreeItem | undefined | null | void> =
    this._onDidChangeTreeData.event

  private apiClient: ApiClient
  private sessions: Session[] = []
  private refreshInterval: NodeJS.Timeout | null = null

  constructor(
    private authManager: AuthManager,
    private configManager: ConfigManager
  ) {
    this.apiClient = new ApiClient(configManager, () => authManager.token)

    // Auto-refresh every 30 seconds
    this.refreshInterval = setInterval(() => this.refresh(), 30000)
  }

  getTreeItem(element: SessionTreeItem): vscode.TreeItem {
    return element
  }

  async getChildren(element?: SessionTreeItem): Promise<SessionTreeItem[]> {
    if (element) {
      // Leaf nodes have no children
      return []
    }

    // Root level: return sessions
    return this.sessions.map((s) => new SessionTreeItem(s, vscode.TreeItemCollapsibleState.None))
  }

  async refresh(): Promise<void> {
    if (!this.authManager.isLoggedIn) {
      this.sessions = []
      this._onDidChangeTreeData.fire()
      return
    }

    try {
      const response = await this.apiClient.getSessions({ limit: 50 })
      let sessions = response.sessions || []

      // Filter by current workspace path if available
      const workspacePath = vscode.workspace.workspaceFolders?.[0]?.uri?.fsPath
      if (workspacePath) {
        sessions = sessions.filter((s) => {
          // Include sessions that match the current workspace, OR have no workspace
          if (!s.workspace) return true
          return s.workspace.startsWith(workspacePath)
        })
      }

      console.log(`[SessionTree] Fetched ${response.sessions?.length || 0} sessions, showing ${sessions.length} after filter`)
      this.sessions = sessions
    } catch (error: any) {
      console.error('Failed to fetch sessions:', error)
      // Don't clear existing sessions on error to avoid flickering
    }

    this._onDidChangeTreeData.fire()
  }

  async getSessionById(sessionId: string): Promise<Session | undefined> {
    return this.sessions.find((s) => s.session_id === sessionId)
  }

  dispose() {
    if (this.refreshInterval) {
      clearInterval(this.refreshInterval)
    }
    this._onDidChangeTreeData.dispose()
  }
}
