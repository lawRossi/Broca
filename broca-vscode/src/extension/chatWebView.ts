import * as vscode from 'vscode'
import { AuthManager } from './auth'
import { ConfigManager } from './config'
import { ApiClient } from './api'
import { SocketClient } from './socket'
import type { WebViewMessage, ExtensionToWebView } from './types'

export class ChatWebViewManager {
  private panels = new Map<string, vscode.WebviewPanel>()
  private socketClients = new Map<string, SocketClient>()
  private runnerPollTimers = new Map<string, NodeJS.Timeout>()
  private apiClient: ApiClient

  constructor(
    private context: vscode.ExtensionContext,
    private authManager: AuthManager,
    private configManager: ConfigManager
  ) {
    this.apiClient = new ApiClient(configManager, () => authManager.token)
  }

  /**
   * Safely post a message to a WebView panel. Silently ignore if panel is disposed.
   */
  private postToPanel(panel: vscode.WebviewPanel, message: ExtensionToWebView): void {
    try {
      panel.webview.postMessage(message)
    } catch {
      // Panel was disposed, ignore
    }
  }

  async openChat(sessionId: string) {
    // Check if panel already exists and is not disposed
    const existingPanel = this.panels.get(sessionId)
    if (existingPanel) {
      try {
        existingPanel.reveal()
        return
      } catch {
        // Panel was disposed, remove it and create a new one
        this.panels.delete(sessionId)
      }
    }

    // Get session info for title
    const session = await this.apiClient.getSessions({ limit: 1, keyword: sessionId })
    const sessionInfo = session.sessions?.[0]
    const title = sessionInfo?.description || sessionId.slice(0, 8) + '...'

    // Create new WebView panel
    const panel = vscode.window.createWebviewPanel(
      'broca.chat',
      `Broca: ${title}`,
      vscode.ViewColumn.One,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [
          vscode.Uri.joinPath(this.context.extensionUri, 'dist', 'webview'),
        ],
      }
    )

    // Set HTML content
    panel.webview.html = this.getWebviewContent(panel.webview, sessionId)

    // Store panel reference
    this.panels.set(sessionId, panel)

    // Handle panel disposal
    panel.onDidDispose(() => {
      this.disposeSession(sessionId)
      this.panels.delete(sessionId)
    })

    // Handle messages from WebView
    panel.webview.onDidReceiveMessage(async (message: WebViewMessage) => {
      console.log('[ChatWebView] received from WebView:', message.type, message.payload ? Object.keys(message.payload) : '')
      await this.handleWebViewMessage(sessionId, panel, message)
    })

    // Handle view state changes (pause/resume polling)
    panel.onDidChangeViewState((e) => {
      if (e.webviewPanel.visible) {
        this.startRunnerPolling(sessionId, panel)
      } else {
        this.stopRunnerPolling(sessionId)
      }
    })
  }

  async openConfigPage() {
    const panel = vscode.window.createWebviewPanel(
      'broca.config',
      'Broca Settings',
      vscode.ViewColumn.One,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [
          vscode.Uri.joinPath(this.context.extensionUri, 'dist', 'webview'),
        ],
      }
    )

    panel.webview.html = this.getConfigWebviewContent(panel.webview)

    panel.webview.onDidReceiveMessage(async (message: WebViewMessage) => {
      if (message.type === 'getConfig') {
        this.postToPanel(panel, {
          type: 'config',
          payload: this.configManager.getAll(),
        } as ExtensionToWebView)
      } else if (message.type === 'saveConfig') {
        console.log('[ChatWebView] Received saveConfig:', JSON.stringify(message.payload))
        this.configManager.setAll(message.payload)
        console.log('[ChatWebView] Config saved, reconfiguring auth')
        this.authManager.reconfigure()
        console.log('[ChatWebView] Auth reconfigured, sending response')
        vscode.window.showInformationMessage('Configuration saved')
        this.postToPanel(panel, { type: 'saved' } as ExtensionToWebView)
        console.log('[ChatWebView] saved response sent')
      } else if (message.type === 'getProviders') {
        try {
          const providers = await this.apiClient.getLLMProviders()
          this.postToPanel(panel, {
            type: 'providers',
            payload: providers,
          } as ExtensionToWebView)
        } catch (error: any) {
          this.postToPanel(panel, {
            type: 'error',
            payload: { message: error.message },
          } as ExtensionToWebView)
        }
      } else if (message.type === 'getModels') {
        try {
          const models = await this.apiClient.getLLMModels(message.payload.provider)
          this.postToPanel(panel, {
            type: 'models',
            payload: models,
          } as ExtensionToWebView)
        } catch (error: any) {
          this.postToPanel(panel, {
            type: 'error',
            payload: { message: error.message },
          } as ExtensionToWebView)
        }
      }
    })
  }

  private async handleWebViewMessage(
    sessionId: string,
    panel: vscode.WebviewPanel,
    message: WebViewMessage
  ) {
    switch (message.type) {
      case 'ready':
        await this.initializeSession(sessionId, panel)
        break

      case 'sendMessage':
        await this.handleSendMessage(sessionId, panel, message.payload)
        break

      case 'loadHistory':
        await this.handleLoadHistory(sessionId, panel, message.payload)
        break

      case 'respondPermission':
        await this.handlePermissionResponse(sessionId, message.payload)
        break

      case 'respondAgentQuery':
        await this.handleAgentQueryResponse(sessionId, message.payload)
        break

      case 'redo':
        await this.sendCommand(sessionId, 'redo', message.payload)
        break

      case 'undo':
        await this.sendCommand(sessionId, 'undo', message.payload)
        break

      case 'abort':
        await this.sendCommand(sessionId, 'abort', message.payload)
        break

      case 'runnerAction':
        await this.handleRunnerAction(sessionId, panel, message.payload)
        break

      case 'fetchRunnerStatus':
        await this.handleFetchRunnerStatus(sessionId, panel)
        break

      case 'fetchAgents':
        await this.handleFetchAgents(sessionId, panel)
        break

      case 'openFile':
        this.handleOpenFile(message.payload)
        break

      case 'fetchTasks':
        await this.handleFetchTasks(panel, message.payload)
        break

      case 'fetchTaskDetail':
        await this.handleFetchTaskDetail(panel, message.payload)
        break

      case 'createTask':
        await this.handleCreateTask(panel, message.payload)
        break

      case 'updateTask':
        await this.handleUpdateTask(panel, message.payload)
        break

      case 'deleteTask':
        await this.handleDeleteTask(panel, message.payload)
        break

      case 'addTaskComment':
        await this.handleAddTaskComment(panel, message.payload)
        break

      case 'fetchJobs':
        await this.handleFetchJobs(panel, message.payload)
        break

      case 'fetchJobDetail':
        await this.handleFetchJobDetail(panel, message.payload)
        break

      case 'executeJob':
        await this.handleExecuteJob(panel, message.payload)
        break

      case 'pauseJob':
        await this.handlePauseJob(panel, message.payload)
        break

      case 'resumeJob':
        await this.handleResumeJob(panel, message.payload)
        break

      case 'deleteJob':
        await this.handleDeleteJob(panel, message.payload)
        break
    }
  }

  private async initializeSession(sessionId: string, panel: vscode.WebviewPanel) {
    try {
      // Create socket client
      const socketClient = new SocketClient(this.configManager, () => this.authManager.token)
      this.socketClients.set(sessionId, socketClient)

      // Set up socket event handlers
      socketClient.setEventHandlers({
        onConnect: () => {
          this.postToPanel(panel, { type: 'connected', payload: { connected: true } } as ExtensionToWebView)
        },
        onDisconnect: () => {
          this.postToPanel(panel, { type: 'connected', payload: { connected: false } } as ExtensionToWebView)
        },
        onMessage: (msg) => {
          this.postToPanel(panel, { type: 'message', payload: msg } as ExtensionToWebView)
        },
        onError: (error) => {
          this.postToPanel(panel, { type: 'error', payload: { message: error.message } } as ExtensionToWebView)
        },
      })

      // Connect and subscribe
      console.log('[ChatWebView] Connecting socket...')
      await socketClient.connect()
      console.log('[ChatWebView] Socket connected, subscribing...')
      await socketClient.subscribe(sessionId)
      console.log('[ChatWebView] Subscribed to', sessionId)

      // Fetch session agents and send default agent ID to WebView
      try {
        console.log('[ChatWebView] Fetching agents for', sessionId)
        const agents = await this.apiClient.getSessionAgents(sessionId)
        console.log('[ChatWebView] Agents:', JSON.stringify(agents.map((a: any) => ({ id: a.agent_id, role: a.role, name: a.name }))))
        const defaultAgentId = agents.find((a: any) => a.role === 'main_agent' || a.role === 'main-agent')?.agent_id
                              || agents[0]?.agent_id
        console.log('[ChatWebView] defaultAgentId:', defaultAgentId)
        if (defaultAgentId) {
          this.postToPanel(panel, {
            type: 'agents',
            payload: { agents, defaultAgentId }
          } as ExtensionToWebView)
        }
      } catch (e) {
        console.error('[ChatWebView] Failed to fetch agents:', e)
      }

      // Load initial history
      await this.handleLoadHistory(sessionId, panel, { skip: 0, limit: 50 })

      // Start runner polling
      this.startRunnerPolling(sessionId, panel)

    } catch (error: any) {
      this.postToPanel(panel, {
        type: 'error',
        payload: { message: `Failed to initialize: ${error.message}` },
      } as ExtensionToWebView)
    }
  }

  private async handleSendMessage(
    sessionId: string,
    panel: vscode.WebviewPanel,
    payload: { content: string; receiverId?: string; files?: any[]; messageId?: string }
  ) {
    const socketClient = this.socketClients.get(sessionId)
    console.log('[ChatWebView] handleSendMessage:', { sessionId, hasSocket: !!socketClient, receiverId: payload.receiverId, content: payload.content?.substring(0, 50) })

    if (!socketClient) {
      console.log('[ChatWebView] No socket client for session:', sessionId)
      this.postToPanel(panel, { type: 'error', payload: { message: 'Not connected' } } as ExtensionToWebView)
      return
    }

    // Use the messageId from the WebView so echoes can be deduplicated
    const messageId = payload.messageId || `msg_${Date.now()}_${Math.random().toString(16).slice(2)}`

    try {
      console.log('[ChatWebView] Calling socket.sendUserMessage...')
      await socketClient.sendUserMessage({
        messageId,
        content: payload.content,
        receiverId: payload.receiverId,
        files: payload.files,
      })
      console.log('[ChatWebView] socket.sendUserMessage completed successfully')
    } catch (error: any) {
      console.log('[ChatWebView] socket.sendUserMessage FAILED:', error.message)
      this.postToPanel(panel, {
        type: 'error',
        payload: { message: `Send failed: ${error.message}` },
      } as ExtensionToWebView)
    }
  }

  private async handleLoadHistory(
    sessionId: string,
    panel: vscode.WebviewPanel,
    payload: { skip: number; limit: number }
  ) {
    try {
      const response = await this.apiClient.getSessionMessages(sessionId, payload.skip, payload.limit)
      this.postToPanel(panel, {
        type: 'historyLoaded',
        payload: {
          messages: response.messages,
          total: response.total,
          skip: payload.skip,
          limit: payload.limit,
        },
      } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, {
        type: 'error',
        payload: { message: `Failed to load history: ${error.message}` },
      } as ExtensionToWebView)
    }
  }

  private async handlePermissionResponse(
    sessionId: string,
    payload: { granted: boolean; requestId?: string; receiverId?: string }
  ) {
    const socketClient = this.socketClients.get(sessionId)
    if (!socketClient) return

    try {
      await socketClient.sendPermissionResponse({
        granted: payload.granted,
        requestId: payload.requestId,
        receiverId: payload.receiverId,
        subscription: sessionId,
      })
    } catch (error: any) {
      console.error('Failed to send permission response:', error)
    }
  }

  private async handleAgentQueryResponse(
    sessionId: string,
    payload: { answer: string; requestId?: string; receiverId?: string }
  ) {
    const socketClient = this.socketClients.get(sessionId)
    if (!socketClient) return

    try {
      await socketClient.sendUserAnswer({
        answer: payload.answer,
        requestId: payload.requestId,
        receiverId: payload.receiverId,
      })
    } catch (error: any) {
      console.error('Failed to send agent query response:', error)
    }
  }

  private async sendCommand(
    sessionId: string,
    command: string,
    payload?: { receiverId?: string; targetMessageId?: string; level?: string }
  ) {
    const socketClient = this.socketClients.get(sessionId)
    if (!socketClient) return

    try {
      await socketClient.sendCommand({
        command,
        arguments: payload ? { target_message_id: payload.targetMessageId, level: payload.level } : undefined,
        receiverId: payload?.receiverId,
        subscription: sessionId,
      })
    } catch (error: any) {
      console.error(`Failed to send ${command} command:`, error)
    }
  }

  private async handleRunnerAction(
    sessionId: string,
    panel: vscode.WebviewPanel,
    payload: { action: 'start' | 'stop' | 'restart'; sessionId: string }
  ) {
    try {
      if (payload.action === 'stop') {
        await this.apiClient.stopRunner(sessionId)
        vscode.window.showInformationMessage('Runner stopped')
      } else {
        await this.apiClient.restartRunner(sessionId)
        vscode.window.showInformationMessage('Runner restarting...')
      }
      // Refresh status after a short delay
      setTimeout(async () => {
        try {
          const status = await this.apiClient.getRunnerStatus(sessionId)
          this.postToPanel(panel, { type: 'runnerStatus', payload: status } as ExtensionToWebView)
        } catch {}
      }, 2000)
      this.postToPanel(panel, { type: 'runnerActionResult', payload: { success: true } } as ExtensionToWebView)
    } catch (error: any) {
      vscode.window.showErrorMessage(`Runner action failed: ${error.message}`)
      this.postToPanel(panel, {
        type: 'runnerActionResult',
        payload: { success: false, error: error.message },
      } as ExtensionToWebView)
    }
  }

  private async handleFetchRunnerStatus(sessionId: string, panel: vscode.WebviewPanel) {
    try {
      const status = await this.apiClient.getRunnerStatus(sessionId)
      this.postToPanel(panel, { type: 'runnerStatus', payload: status } as ExtensionToWebView)
    } catch (error: any) {
      console.error('Failed to fetch runner status:', error)
    }
  }

  private async handleFetchAgents(sessionId: string, panel: vscode.WebviewPanel) {
    try {
      const agents = await this.apiClient.getSessionAgents(sessionId)
      const defaultAgentId = agents.find((a: any) => a.role === 'main_agent' || a.role === 'main-agent')?.agent_id
                            || agents[0]?.agent_id
      this.postToPanel(panel, {
        type: 'agents',
        payload: { agents, defaultAgentId },
      } as ExtensionToWebView)
    } catch (error: any) {
      console.error('Failed to fetch agents:', error)
    }
  }

  private handleOpenFile(payload: { path: string }) {
    if (payload.path) {
      const fileUri = vscode.Uri.file(payload.path)
      vscode.commands.executeCommand('vscode.open', fileUri)
    }
  }

  private async handleFetchTasks(
    panel: vscode.WebviewPanel,
    payload: { skip?: number; limit?: number; status?: string; priority?: string; keyword?: string }
  ) {
    try {
      const response = await this.apiClient.client.get('/task/tasks', {
        params: {
          skip: payload.skip ?? 0,
          limit: payload.limit ?? 50,
          status: payload.status,
          priority: payload.priority,
          keyword: payload.keyword,
          order_by: 'created_at desc',
        },
      })
      this.postToPanel(panel, { type: 'tasks', payload: response.data } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: error.message } } as ExtensionToWebView)
    }
  }

  private async handleFetchTaskDetail(
    panel: vscode.WebviewPanel,
    payload: { taskId: string }
  ) {
    try {
      const response = await this.apiClient.client.get(`/task/${payload.taskId}`, {
        params: { include_comments: true },
      })
      this.postToPanel(panel, { type: 'taskDetail', payload: response.data } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: error.message } } as ExtensionToWebView)
    }
  }

  private async handleCreateTask(
    panel: vscode.WebviewPanel,
    payload: any
  ) {
    try {
      const response = await this.apiClient.client.post('/task/', payload)
      this.postToPanel(panel, { type: 'taskCreated', payload: response.data } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: error.message } } as ExtensionToWebView)
    }
  }

  private async handleUpdateTask(
    panel: vscode.WebviewPanel,
    payload: { taskId: string; data: any }
  ) {
    try {
      await this.apiClient.client.put(`/task/${payload.taskId}`, payload.data)
      this.postToPanel(panel, { type: 'taskUpdated', payload: { taskId: payload.taskId } } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: error.message } } as ExtensionToWebView)
    }
  }

  private async handleDeleteTask(
    panel: vscode.WebviewPanel,
    payload: { taskId: string }
  ) {
    try {
      await this.apiClient.client.delete(`/task/${payload.taskId}`)
      this.postToPanel(panel, { type: 'taskDeleted', payload: { taskId: payload.taskId } } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: error.message } } as ExtensionToWebView)
    }
  }

  private async handleAddTaskComment(
    panel: vscode.WebviewPanel,
    payload: { taskId: string; author: string; content: string }
  ) {
    try {
      const response = await this.apiClient.client.post(`/task/${payload.taskId}/comments`, {
        author: payload.author,
        content: payload.content,
      })
      this.postToPanel(panel, { type: 'taskCommentAdded', payload: response.data } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: error.message } } as ExtensionToWebView)
    }
  }

  private async handleFetchJobs(
    panel: vscode.WebviewPanel,
    payload: { skip?: number; limit?: number; status?: string; job_type?: string; keyword?: string }
  ) {
    try {
      const response = await this.apiClient.client.get('/job/jobs', {
        params: {
          skip: payload.skip ?? 0,
          limit: payload.limit ?? 50,
          status: payload.status,
          job_type: payload.job_type,
          keyword: payload.keyword,
          order_by: 'created_at desc',
        },
      })
      this.postToPanel(panel, { type: 'jobs', payload: response.data } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: error.message } } as ExtensionToWebView)
    }
  }

  private async handleFetchJobDetail(
    panel: vscode.WebviewPanel,
    payload: { jobId: string }
  ) {
    try {
      const response = await this.apiClient.client.get(`/job/${payload.jobId}`, {
        params: { execution_limit: 50 },
      })
      this.postToPanel(panel, { type: 'jobDetail', payload: response.data } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: error.message } } as ExtensionToWebView)
    }
  }

  private async handleExecuteJob(
    panel: vscode.WebviewPanel,
    payload: { jobId: string }
  ) {
    try {
      await this.apiClient.client.post(`/job/${payload.jobId}/execute`)
      this.postToPanel(panel, { type: 'jobExecuted', payload: { jobId: payload.jobId } } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: error.message } } as ExtensionToWebView)
    }
  }

  private async handlePauseJob(
    panel: vscode.WebviewPanel,
    payload: { jobId: string }
  ) {
    try {
      await this.apiClient.client.post(`/job/${payload.jobId}/pause`)
      this.postToPanel(panel, { type: 'jobPaused', payload: { jobId: payload.jobId } } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: error.message } } as ExtensionToWebView)
    }
  }

  private async handleResumeJob(
    panel: vscode.WebviewPanel,
    payload: { jobId: string }
  ) {
    try {
      await this.apiClient.client.post(`/job/${payload.jobId}/resume`)
      this.postToPanel(panel, { type: 'jobResumed', payload: { jobId: payload.jobId } } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: error.message } } as ExtensionToWebView)
    }
  }

  private async handleDeleteJob(
    panel: vscode.WebviewPanel,
    payload: { jobId: string }
  ) {
    try {
      await this.apiClient.client.delete(`/job/${payload.jobId}`)
      this.postToPanel(panel, { type: 'jobDeleted', payload: { jobId: payload.jobId } } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: error.message } } as ExtensionToWebView)
    }
  }

  private async startRunnerPolling(sessionId: string, panel: vscode.WebviewPanel) {
    this.stopRunnerPolling(sessionId)

    const poll = async () => {
      try {
        const status = await this.apiClient.getRunnerStatus(sessionId)
        this.postToPanel(panel, {
          type: 'runnerStatus',
          payload: status,
        } as ExtensionToWebView)
      } catch {
        // Ignore polling errors
      }
    }

    // Initial fetch
    try {
      const status = await this.apiClient.getRunnerStatus(sessionId)
      console.log('[ChatWebView] Initial runner status:', status?.status)
      if (status) {
        this.postToPanel(panel, { type: 'runnerStatus', payload: status } as ExtensionToWebView)
      }
    } catch (e: any) {
      console.log('[ChatWebView] Initial runner poll failed:', e.message)
    }

    // Poll every 10 seconds
    const timer = setInterval(async () => {
      try {
        const status = await this.apiClient.getRunnerStatus(sessionId)
        if (status) {
          this.postToPanel(panel, { type: 'runnerStatus', payload: status } as ExtensionToWebView)
        }
      } catch (e: any) {
        console.log('[ChatWebView] Runner poll failed:', e.message)
      }
    }, 10000)
    this.runnerPollTimers.set(sessionId, timer)
  }

  private stopRunnerPolling(sessionId: string) {
    const timer = this.runnerPollTimers.get(sessionId)
    if (timer) {
      clearInterval(timer)
      this.runnerPollTimers.delete(sessionId)
    }
  }

  private disposeSession(sessionId: string) {
    this.stopRunnerPolling(sessionId)

    const socketClient = this.socketClients.get(sessionId)
    if (socketClient) {
      socketClient.disconnect()
      this.socketClients.delete(sessionId)
    }
  }

  private getWebviewContent(webview: vscode.Webview, sessionId: string): string {
    const webviewDist = vscode.Uri.joinPath(this.context.extensionUri, 'dist', 'webview')
    const htmlPath = vscode.Uri.joinPath(webviewDist, 'index.html')

    // Read the built HTML file
    let html: string
    try {
      html = require('fs').readFileSync(htmlPath.fsPath, 'utf-8')
    } catch {
      return this.getFallbackHtml('Chat', 'Failed to load chat UI')
    }

    // Transform resource paths to webview URIs
    html = this.transformResourcePaths(webview, webviewDist, html)

    // Inject initial data as a JSON script tag (CSP-safe, no inline JS)
    const supabaseUrl = this.configManager.supabaseUrl
    const supabaseKey = this.configManager.supabaseKey
    const token = this.authManager.token

    const serverUrl = this.configManager.get('serverUrl')
    const wsUrl = this.configManager.get('wsUrl')

    const initData = {
      sessionId,
      token: token || '',
      supabaseUrl,
      supabaseKey,
      serverUrl: serverUrl || 'http://localhost:8000',
      wsUrl: wsUrl || 'http://localhost:8000',
    }
    const initTag = `<script type="application/json" id="init-data">${JSON.stringify(initData)}</script>`

    html = html.replace('</head>', initTag + '</head>')
    html = this.addCSP(webview, html)

    return html
  }

  private getConfigWebviewContent(webview: vscode.Webview): string {
    const webviewDist = vscode.Uri.joinPath(this.context.extensionUri, 'dist', 'webview')
    const htmlPath = vscode.Uri.joinPath(webviewDist, 'config.html')

    // Read the built HTML file
    let html: string
    try {
      html = require('fs').readFileSync(htmlPath.fsPath, 'utf-8')
    } catch {
      return this.getFallbackHtml('Broca Settings', 'Failed to load settings UI')
    }

    // Transform resource paths to webview URIs
    html = this.transformResourcePaths(webview, webviewDist, html)

    // Inject empty data for config page (no session-specific data needed)
    const initTag = `<script type="application/json" id="init-data">{}</script>`
    html = html.replace('</head>', initTag + '</head>')
    html = this.addCSP(webview, html)

    return html
  }

  private transformResourcePaths(webview: vscode.Webview, distPath: vscode.Uri, html: string): string {
    // Replace relative asset paths with webview URIs
    // Match: src="./assets/..." or href="./assets/..."
    return html.replace(
      /(src|href)=(["'])(\.\/assets\/[^"']+)\2/g,
      (_, attr, quote, relativePath) => {
        const uri = webview.asWebviewUri(vscode.Uri.joinPath(distPath, relativePath.replace(/^\.\//, '')))
        return `${attr}=${quote}${uri}${quote}`
      }
    )
  }

  private addCSP(webview: vscode.Webview, html: string): string {
    const csp = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src ${webview.cspSource} 'unsafe-eval'; img-src ${webview.cspSource} https: data:; connect-src ${webview.cspSource} https: http://localhost ws://localhost;">`
    return html.replace('<head>', `<head>${csp}`)
  }

  private getFallbackHtml(title: string, message: string): string {
    return `<!DOCTYPE html>
<html>
<head><title>${title}</title></head>
<body style="display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;color:#888;">
  <p>${message}</p>
</body>
</html>`
  }

  dispose() {
    // Dispose all panels and resources
    for (const [sessionId] of this.panels) {
      this.disposeSession(sessionId)
    }
    this.panels.clear()
  }
}
