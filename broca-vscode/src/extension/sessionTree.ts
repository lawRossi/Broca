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
    super(session.description || session.session_id, collapsibleState)

    this.id = session.session_id
    this.contextValue = 'session'
    this.tooltip = this.buildTooltip(session)
    // Show workspace as secondary text in tree view
    if (session.workspace) {
      this.description = session.workspace
    }

    // Set icon based on runner status and category
    if (session.category === 'agent-orchestration') {
      this.iconPath = new vscode.ThemeIcon('organization')
    } else {
      this.iconPath = this.getStatusIcon(session.runner_status)
    }

    // Command when clicking the item
    if (session.category === 'agent-orchestration') {
      // Orchestration sessions open crew management panel
      this.command = {
        command: 'broca.openCrewList',
        title: 'View Orchestration Executions',
        arguments: [session.session_id],
      }
    } else {
      this.command = {
        command: 'broca.openChat',
        title: 'Open Chat',
        arguments: [session.session_id],
      }
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
    if (session.category === 'agent-orchestration') {
      tooltip.appendMarkdown(`**Category**: Agent Orchestration\n\n`)
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

/**
 * A special tree item displayed at the top of the session list to indicate
 * the current filter state. Clicking it toggles between workspace-only and all sessions.
 */
class FilterStatusItem extends SessionTreeItem {
  constructor(showAll: boolean, onClickCommand: string) {
    const label = showAll
      ? 'Showing: all sessions  (click to filter by workspace)'
      : 'Filtering: current workspace  (click to show all)'
    // Pass minimal session data — this is a fake item, not a real session
    super({
      session_id: '__filter_status__',
      description: label,
      workspace: '',
      category: 'normal',
      created_at: '',
      runner_status: '',
    } as Session, vscode.TreeItemCollapsibleState.None)

    this.id = '__filter_status__'
    this.contextValue = 'filterStatus'
    this.iconPath = new vscode.ThemeIcon(showAll ? 'globe' : 'filter')
    this.description = ''
    this.tooltip = showAll
      ? 'Currently showing all sessions. Click to filter by current workspace.'
      : 'Currently filtering by current workspace. Click to show all sessions.'
    this.command = {
      command: onClickCommand,
      title: 'Toggle Session Filter',
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
  private _showAllSessions: boolean = false

  constructor(
    private authManager: AuthManager,
    private configManager: ConfigManager,
    onAuthError?: () => void
  ) {
    this.apiClient = new ApiClient(configManager, () => authManager.token)
    this.apiClient.onAuthError = onAuthError ?? null

    // Initialize context: filtering by workspace by default
    vscode.commands.executeCommand('setContext', 'broca:showAllSessions', false)

    // Auto-refresh every 30 seconds
    this.refreshInterval = setInterval(() => this.refresh(), 30000)
  }

  get showAllSessions(): boolean {
    return this._showAllSessions
  }

  toggleShowAll(): void {
    // No-op if no workspace folder is open (already showing all sessions)
    const workspacePath = vscode.workspace.workspaceFolders?.[0]?.uri?.fsPath
    if (!workspacePath) return

    this._showAllSessions = !this._showAllSessions
    vscode.commands.executeCommand('setContext', 'broca:showAllSessions', this._showAllSessions)
    this.refresh()
  }

  getTreeItem(element: SessionTreeItem): vscode.TreeItem {
    return element
  }

  async getChildren(element?: SessionTreeItem): Promise<SessionTreeItem[]> {
    if (element) {
      // Leaf nodes have no children
      return []
    }

    // Root level: return sessions with filter status at top
    const workspacePath = vscode.workspace.workspaceFolders?.[0]?.uri?.fsPath
    const items = this.sessions.map((s) => new SessionTreeItem(s, vscode.TreeItemCollapsibleState.None))
    if (workspacePath) {
      items.unshift(new FilterStatusItem(this._showAllSessions, 'broca.toggleSessionFilter'))
    }
    return items
  }

  async refresh(): Promise<void> {
    if (!this.authManager.isLoggedIn) {
      this.sessions = []
      this._onDidChangeTreeData.fire()
      // 未登录时给用户明确的提示，引导登录
      vscode.window.showInformationMessage('请先登录以查看会话列表', '登录').then((action) => {
        if (action === '登录') {
          vscode.commands.executeCommand('broca.login')
        }
      })
      return
    }

    try {
      const response = await this.apiClient.getSessions({ limit: 50 })
      let sessions = response.sessions || []

      // Filter by current workspace path if available (unless showing all)
      const workspacePath = vscode.workspace.workspaceFolders?.[0]?.uri?.fsPath
      if (workspacePath && !this._showAllSessions) {
        sessions = sessions.filter((s) =>
          // Only include sessions whose workspace matches the current project directory
          !!s.workspace && s.workspace.startsWith(workspacePath)
        )
      }

      console.log(`[SessionTree] Fetched ${response.sessions?.length || 0} sessions, showing ${sessions.length} after filter`)
      this.sessions = sessions
    } catch (error: any) {
      console.error('Failed to fetch sessions:', error)
      // 未登录时不显示错误提示（静默处理）
      if (!this.authManager.isLoggedIn) {
        this.sessions = []
        this._onDidChangeTreeData.fire()
        return
      }
      // Show error notification to user
      let message: string
      if (!error?.response) {
        // No HTTP response received — server unreachable or network issue
        message = error.code === 'ECONNABORTED' ? 'Request timed out' : 'Cannot connect to server, please check if the service is running'
      } else {
        const respData = error?.response?.data
        message = respData?.detail || respData?.msg || respData?.message || (typeof respData === 'string' ? respData : null) || error.message || 'Unknown error'
      }
      vscode.window.showErrorMessage(`Failed to fetch sessions: ${message}`)
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
