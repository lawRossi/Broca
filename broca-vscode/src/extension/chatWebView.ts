import * as vscode from 'vscode'
import { AuthManager } from './auth'
import { ConfigManager } from './config'
import { ApiClient } from './api'
import { SocketClient } from './socket'
import { extractErrorMessage, showErrorNotification } from './errors'
import type { WebViewMessage, ExtensionToWebView } from './types'

export class ChatWebViewManager {
  private panels = new Map<string, vscode.WebviewPanel>()
  private crewPanels = new Map<string, vscode.WebviewPanel>()
  private socketClients = new Map<string, SocketClient>()
  private socketUnsubs = new Map<string, () => Promise<void>>()
  private runnerPollTimers = new Map<string, NodeJS.Timeout>()
  private sessionExecutionIds = new Map<string, string>()
  private apiClient: ApiClient
  private createSessionPanel: vscode.WebviewPanel | null = null

  constructor(
    private context: vscode.ExtensionContext,
    private authManager: AuthManager,
    private configManager: ConfigManager,
    onAuthError?: () => void
  ) {
    this.apiClient = new ApiClient(configManager, () => authManager.token)
    this.apiClient.onAuthError = onAuthError ?? null
    this._onAuthError = onAuthError ?? null

    // 监听 VS Code 窗口焦点变化（Alt+Tab 切出/切回），作为"离开/回到页面"的信号之一
    this._windowStateDisposable = vscode.window.onDidChangeWindowState((e) => {
      if (e.focused) {
        this._onWindowFocus()
      } else {
        this._onWindowBlur()
      }
    })
  }

  private _windowStateDisposable: vscode.Disposable | null = null
  private _onAuthError: (() => void) | null = null

  /**
   * Close all panels (chat + crew) associated with a session.
   * Panel disposal triggers onDidDispose which handles cleanup automatically.
   */
  closeSessionPanel(sessionId: string) {
    const panel = this.panels.get(sessionId)
    if (panel) {
      try {
        panel.dispose()
      } catch {
        /* already disposed */
      }
    }
    const crewPanel = this.crewPanels.get(sessionId)
    if (crewPanel) {
      try {
        crewPanel.dispose()
      } catch {
        /* already disposed */
      }
    }
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

  // 离开页面检测：只有"确实离开 + 确实回来"且离开超过 1 分钟才自动刷新。
  // 离开信号：panel 隐藏（切换 VS Code 内标签页）或窗口失焦（Alt+Tab 切到其他应用）
  // 回来信号：panel 重新可见，或窗口恢复焦点且该 panel 当前可见
  private static readonly LEAVE_TIMEOUT_MS = 60 * 1000 // 1 分钟
  // 记录每个 session 的"离开开始时间"（离开期间保留最早时间戳，回到页面时检查并清除）
  private webviewAwayTimestamps = new Map<string, number>()

  async openChat(sessionId: string, executionId?: string) {
    try {
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

      // Get session info for title and category
      const sessionInfo = await this.apiClient.getSession(sessionId)
      const title = sessionInfo?.description || sessionId
      const category = sessionInfo?.category || 'normal'

      // Create new WebView panel
      const panel = vscode.window.createWebviewPanel('broca.chat', `Broca: ${title}`, vscode.ViewColumn.One, {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [vscode.Uri.joinPath(this.context.extensionUri, 'dist', 'webview')],
      })

      // Set HTML content with category and executionId
      panel.webview.html = this.getWebviewContent(panel.webview, sessionId, category, executionId)

      // Store executionId for this session (used by initializeSession for filtered history load)
      if (executionId) {
        this.sessionExecutionIds.set(sessionId, executionId)
      }

      // Store panel reference
      this.panels.set(sessionId, panel)

      // Handle panel disposal
      panel.onDidDispose(() => {
        // Only fully dispose the socket if crew panel is not open
        if (!this.crewPanels.has(sessionId)) {
          this.disposeSession(sessionId)
        } else {
          // Just remove chat panel handlers from the existing socket
          const socketClient = this.socketClients.get(sessionId)
          if (socketClient) {
            socketClient.off('onConnect', 'chat')
            socketClient.off('onDisconnect', 'chat')
            socketClient.off('onMessage', 'chat')
            socketClient.off('onError', 'chat')
          }
        }
        this.sessionExecutionIds.delete(sessionId)
        this.panels.delete(sessionId)
        this.webviewAwayTimestamps.delete(sessionId)
      })

      // Handle messages from WebView
      panel.webview.onDidReceiveMessage(async (message: WebViewMessage) => {
        console.log(
          '[ChatWebView] received from WebView:',
          message.type,
          message.payload ? Object.keys(message.payload) : ''
        )
        await this.handleWebViewMessage(sessionId, panel, message)
      })

      // Handle view state changes (pause/resume polling, auto-refresh on long absence)
      // 只有"确实离开 + 确实回来"才可能刷新：回来（可见）时检查离开时长，
      // 避免"留在页面没离开"（无离开记录）或"离开页面未返回"（仍隐藏）时误刷新。
      panel.onDidChangeViewState((e) => {
        if (e.webviewPanel.visible) {
          this.startRunnerPolling(sessionId, panel)
          // 回到页面：若曾离开且离开超过 1 分钟则刷新
          const awaySince = this.webviewAwayTimestamps.get(sessionId)
          if (awaySince !== undefined && Date.now() - awaySince >= ChatWebViewManager.LEAVE_TIMEOUT_MS) {
            this.postToPanel(panel, { type: 'refreshSession' } as ExtensionToWebView)
          }
          this.webviewAwayTimestamps.delete(sessionId)
        } else {
          this.stopRunnerPolling(sessionId)
          // 页面隐藏：记录离开时间（若尚未记录则保留最早离开时间）
          if (!this.webviewAwayTimestamps.has(sessionId)) {
            this.webviewAwayTimestamps.set(sessionId, Date.now())
          }
        }
      })
    } catch (error: any) {
      showErrorNotification(error, '打开聊天失败')
    }
  }

  // 窗口失去焦点（Alt+Tab 切到其他应用）：对每个 panel 记录"离开开始时间"。
  // 若已处于离开状态则保留最早时间戳，避免被更晚的 blur 覆盖而缩短离开时长。
  private _onWindowBlur(): void {
    const now = Date.now()
    for (const [sessionId] of this.panels) {
      if (!this.webviewAwayTimestamps.has(sessionId)) {
        this.webviewAwayTimestamps.set(sessionId, now)
      }
    }
  }

  // 窗口恢复焦点（切回 VS Code）：仅当用户确实回到该页面（panel 当前可见）时才检查是否刷新。
  // 若 panel 仍隐藏（用户切走页面后还没回来），只保留离开记录，不刷新、不清除。
  private _onWindowFocus(): void {
    const now = Date.now()
    for (const [sessionId, panel] of this.panels) {
      if (!panel.visible) continue // 页面仍隐藏：用户还没回到该页面，不刷新
      const awaySince = this.webviewAwayTimestamps.get(sessionId)
      if (awaySince !== undefined && now - awaySince >= ChatWebViewManager.LEAVE_TIMEOUT_MS) {
        this.postToPanel(panel, { type: 'refreshSession' } as ExtensionToWebView)
      }
      this.webviewAwayTimestamps.delete(sessionId)
    }
  }

  async openConfigPage() {
    const panel = vscode.window.createWebviewPanel('broca.config', 'Broca Settings', vscode.ViewColumn.One, {
      enableScripts: true,
      retainContextWhenHidden: true,
      localResourceRoots: [vscode.Uri.joinPath(this.context.extensionUri, 'dist', 'webview')],
    })

    panel.webview.html = this.getConfigWebviewContent(panel.webview)

    panel.webview.onDidReceiveMessage(async (message: WebViewMessage) => {
      if (message.type === 'getConfig') {
        this.postToPanel(panel, {
          type: 'config',
          payload: this.configManager.getAll(),
        } as ExtensionToWebView)
      } else if (message.type === 'saveConfig') {
        console.log('[ChatWebView] Received saveConfig:', JSON.stringify(message.payload))
        try {
          await this.configManager.setAll(message.payload)
          console.log('[ChatWebView] Config saved, reconfiguring auth')
          this.authManager.reconfigure()
          vscode.window.showInformationMessage('Configuration saved')
          this.postToPanel(panel, { type: 'saved' } as ExtensionToWebView)
        } catch (error: any) {
          console.error('[ChatWebView] Failed to save config:', error)
          showErrorNotification(error, 'Failed to save configuration')
          this.postToPanel(panel, {
            type: 'error',
            payload: { message: extractErrorMessage(error) },
          } as ExtensionToWebView)
        }
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
            payload: { message: extractErrorMessage(error) },
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
            payload: { message: extractErrorMessage(error) },
          } as ExtensionToWebView)
        }
      }
    })
  }

  async openCrewPanel(sessionId: string) {
    try {
      const sessionInfo = await this.apiClient.getSession(sessionId)
      const title = sessionInfo?.description || sessionId

      const panel = vscode.window.createWebviewPanel(
        'broca.crews',
        `Broca: 编排管理 - ${title}`,
        vscode.ViewColumn.One,
        {
          enableScripts: true,
          retainContextWhenHidden: true,
          localResourceRoots: [vscode.Uri.joinPath(this.context.extensionUri, 'dist', 'webview')],
        }
      )

      panel.webview.html = this.getCrewWebviewContent(panel.webview, sessionId)

      // Store crew panel reference
      this.crewPanels.set(sessionId, panel)

      panel.onDidDispose(() => {
        this.crewPanels.delete(sessionId)
        // If no chat panel is open either, fully dispose the socket
        if (!this.panels.has(sessionId)) {
          this.disposeSession(sessionId)
        }
      })

      panel.webview.onDidReceiveMessage(async (message: WebViewMessage) => {
        console.log('[CrewPanel] received:', message.type)
        await this.handleWebViewMessage(sessionId, panel, message)
      })

      // Ensure Socket connection exists for real-time crew events
      // (chat panel's initializeSession also creates one, but crew panel may open standalone)
      if (!this.socketClients.has(sessionId)) {
        this.initializeCrewSocket(sessionId, panel)
      }
    } catch (error: any) {
      showErrorNotification(error, '打开编排管理失败')
    }
  }

  private async initializeCrewSocket(sessionId: string, panel: vscode.WebviewPanel) {
    try {
      const socketClient = new SocketClient(this.configManager, () => this.authManager.token)
      socketClient.onAuthError = this._onAuthError
      this.socketClients.set(sessionId, socketClient)

      socketClient.setEventHandlers({
        onConnect: () => {
          console.log('[CrewSocket] connected for', sessionId)
        },
        onDisconnect: () => {
          console.log('[CrewSocket] disconnected for', sessionId)
        },
        onMessage: (msg) => {
          // Only forward crew events to the crew panel
          if (msg.message_type === 'system_message' && msg.data?.crew_event) {
            this.postToPanel(panel, { type: 'crewEvent', payload: msg.data.payload } as ExtensionToWebView)
          }
        },
        onError: (error) => {
          console.error('[CrewSocket] error:', error.message)
        },
      })

      await socketClient.connect()
      // Subscribe only to crew channel (not chat)
      const unsub = await socketClient.subscribe(sessionId)
      this.socketUnsubs.set(sessionId, unsub)
      console.log('[CrewSocket] subscribed to crew:', sessionId)
    } catch (error: any) {
      console.warn('[CrewSocket] initialization failed:', error)
    }
  }

  async openCreateSessionDialog(onSessionCreated?: () => void) {
    // Close existing panel if any
    if (this.createSessionPanel) {
      try {
        this.createSessionPanel.dispose()
      } catch {}
      this.createSessionPanel = null
    }

    const panel = vscode.window.createWebviewPanel(
      'broca.createSession',
      '创建会话',
      { viewColumn: vscode.ViewColumn.Active, preserveFocus: true },
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [vscode.Uri.joinPath(this.context.extensionUri, 'dist', 'webview')],
      }
    )

    this.createSessionPanel = panel
    panel.onDidDispose(() => {
      this.createSessionPanel = null
    })

    // Get workspace path for pre-fill
    const workspacePath = vscode.workspace.workspaceFolders?.[0]?.uri?.fsPath || ''

    // Get defaults from config
    const defaultProvider = this.configManager.get('defaultProvider') || ''
    const defaultModel = this.configManager.get('defaultModel') || ''

    panel.webview.html = this.getCreateSessionHtml(workspacePath, defaultProvider, defaultModel)

    panel.webview.onDidReceiveMessage(async (message: WebViewMessage) => {
      switch (message.type) {
        case 'getProviders':
          try {
            const providers = await this.apiClient.getLLMProviders()
            this.postToPanel(panel, { type: 'providers', payload: providers } as ExtensionToWebView)
          } catch (error: any) {
            this.postToPanel(panel, {
              type: 'error',
              payload: { message: extractErrorMessage(error) },
            } as ExtensionToWebView)
          }
          break

        case 'getModels':
          try {
            const models = await this.apiClient.getLLMModels(message.payload.provider)
            this.postToPanel(panel, { type: 'models', payload: models } as ExtensionToWebView)
          } catch (error: any) {
            this.postToPanel(panel, {
              type: 'error',
              payload: { message: extractErrorMessage(error) },
            } as ExtensionToWebView)
          }
          break

        case 'createSession':
          try {
            const result = await this.apiClient.createSession(message.payload)
            this.postToPanel(panel, { type: 'sessionCreated', payload: result } as ExtensionToWebView)
            vscode.window.showInformationMessage('会话创建成功')
            panel.dispose()
            if (onSessionCreated) onSessionCreated()
          } catch (error: any) {
            this.postToPanel(panel, {
              type: 'error',
              payload: { message: extractErrorMessage(error, '创建会话失败') },
            } as ExtensionToWebView)
          }
          break

        case 'cancel':
          panel.dispose()
          break

        case 'browseWorkspace':
          try {
            const defaultUri = workspacePath ? vscode.Uri.file(workspacePath) : undefined
            const uris = await vscode.window.showOpenDialog({
              canSelectFolders: true,
              canSelectFiles: false,
              canSelectMany: false,
              defaultUri,
              title: '选择工作空间目录',
            })
            if (uris && uris.length > 0) {
              this.postToPanel(panel, { type: 'workspacePath', payload: uris[0].fsPath } as ExtensionToWebView)
            }
          } catch (error: any) {
            this.postToPanel(panel, {
              type: 'error',
              payload: { message: extractErrorMessage(error) },
            } as ExtensionToWebView)
          }
          break
      }
    })
  }

  private getCreateSessionHtml(workspacePath: string, defaultProvider: string, defaultModel: string): string {
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Create Session</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 13px;
      background: var(--vscode-editor-background, #1e1e1e);
      color: var(--vscode-editor-foreground, #cccccc);
      padding: 20px;
    }
    .container { max-width: 480px; margin: 0 auto; }
    h1 { font-size: 18px; font-weight: 600; margin-bottom: 20px; }
    .field { margin-bottom: 16px; }
    label {
      display: block;
      font-size: 12px;
      font-weight: 500;
      margin-bottom: 4px;
      color: var(--vscode-descriptionForeground, #888);
    }
    input, select {
      width: 100%;
      padding: 8px 10px;
      background: var(--vscode-input-background, #3c3c3c);
      color: var(--vscode-input-foreground, #cccccc);
      border: 1px solid var(--vscode-input-border, #555);
      border-radius: 4px;
      font-size: 13px;
      outline: none;
    }
    input:focus, select:focus {
      border-color: var(--vscode-focusBorder, #007fd4);
    }
    input::placeholder { color: var(--vscode-input-placeholderForeground, #888); }
    .hint { font-size: 11px; color: var(--vscode-descriptionForeground, #888); margin-top: 3px; }
    .buttons {
      display: flex;
      gap: 8px;
      margin-top: 24px;
      justify-content: flex-end;
    }
    button {
      padding: 8px 20px;
      border: none;
      border-radius: 4px;
      font-size: 13px;
      cursor: pointer;
      font-weight: 500;
    }
    .btn-primary {
      background: var(--vscode-button-background, #007acc);
      color: var(--vscode-button-foreground, #fff);
    }
    .btn-primary:hover { background: var(--vscode-button-hoverBackground, #005a9e); }
    .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
    .btn-secondary {
      background: var(--vscode-button-secondaryBackground, #3a3d41);
      color: var(--vscode-button-secondaryForeground, #ccc);
    }
    .btn-secondary:hover { background: var(--vscode-button-secondaryHoverBackground, #45494e); }
    .error {
      color: var(--vscode-errorForeground, #f48771);
      font-size: 12px;
      margin-top: 8px;
      display: none;
    }
    .category-group { margin-bottom: 20px; }
    .category-option {
      display: flex;
      align-items: flex-start;
      gap: 10px;
      padding: 10px 12px;
      margin-bottom: 8px;
      border: 1px solid var(--vscode-input-border, #555);
      border-radius: 6px;
      cursor: pointer;
      transition: border-color 0.2s, background 0.2s;
    }
    .category-option:hover {
      border-color: var(--vscode-focusBorder, #007fd4);
      background: var(--vscode-list-hoverBackground, #2a2d2e);
    }
    .category-option.selected {
      border-color: var(--vscode-focusBorder, #007fd4);
      background: var(--vscode-list-activeSelectionBackground, #04395e);
    }
    .category-option input[type="radio"] {
      margin-top: 2px;
      accent-color: var(--vscode-focusBorder, #007fd4);
      width: auto;
      flex-shrink: 0;
    }
    .category-label { font-weight: 500; font-size: 13px; }
    .category-desc { font-size: 11px; color: var(--vscode-descriptionForeground, #888); margin-top: 2px; }
  </style>
</head>
<body>
  <div class="container">
    <h1>创建会话</h1>

    <div class="field">
      <label>会话类型</label>
      <div class="category-group">
        <div class="category-option selected" data-category="normal" onclick="selectCategory(this)">
          <input type="radio" name="category" value="normal" checked>
          <div>
            <div class="category-label">普通会话</div>
            <div class="category-desc">创建内置Agent，适合日常对话和任务</div>
          </div>
        </div>
        <div class="category-option" data-category="agent-orchestration" onclick="selectCategory(this)">
          <input type="radio" name="category" value="agent-orchestration">
          <div>
            <div class="category-label">Agent编排会话</div>
            <div class="category-desc">从工作空间加载自定义Agent，适合多Agent编排工作流</div>
          </div>
        </div>
      </div>
    </div>

    <div class="field">
      <label for="description">描述</label>
      <input id="description" type="text" placeholder="例如：调试登录问题（可选）" />
      <div class="hint">可选，留空则跳过</div>
    </div>

    <div class="field">
      <label for="provider">LLM 提供商</label>
      <select id="provider">
        <option value="">-- 使用默认${defaultProvider ? ' (' + defaultProvider + ')' : ''} --</option>
      </select>
      <div class="hint">选择提供商，留空则使用默认配置</div>
    </div>

    <div class="field">
      <label for="model">LLM 模型</label>
      <select id="model" disabled>
        <option value="">-- 请先选择提供商 --</option>
      </select>
      <div class="hint">选择模型，留空则使用提供商默认模型</div>
    </div>

    <div class="field">
      <label for="workspace">工作空间</label>
      <div style="display:flex;gap:6px;">
        <input id="workspace" type="text" value="${workspacePath}" placeholder="工作空间路径" style="flex:1;" />
        <button id="browseBtn" class="btn-secondary" style="white-space:nowrap;padding:8px 12px;flex-shrink:0;">浏览...</button>
      </div>
      <div class="hint">会话的工作目录，可直接输入或点击「浏览」选择文件夹</div>
    </div>

    <div class="error" id="errorMsg"></div>

    <div class="buttons">
      <button class="btn-secondary" id="cancelBtn">取消</button>
      <button class="btn-primary" id="createBtn">创建会话</button>
    </div>
  </div>

  <script>
    (function() {
      const vscode = acquireVsCodeApi();
      const providerSelect = document.getElementById('provider');
      const modelSelect = document.getElementById('model');
      const createBtn = document.getElementById('createBtn');
      const cancelBtn = document.getElementById('cancelBtn');
      const errorMsg = document.getElementById('errorMsg');
      const descriptionInput = document.getElementById('description');
      const workspaceInput = document.getElementById('workspace');
      const browseBtn = document.getElementById('browseBtn');
      const categoryInputs = document.querySelectorAll('input[name="category"]');

      let providers = [];
      let models = [];

      const defaultProviderVal = ${JSON.stringify(defaultProvider)};
      const defaultModelVal = ${JSON.stringify(defaultModel)};

      function selectCategory(el) {
        document.querySelectorAll('.category-option').forEach(opt => opt.classList.remove('selected'));
        el.classList.add('selected');
        el.querySelector('input[type="radio"]').checked = true;
      }

      // Request providers on load
      vscode.postMessage({ type: 'getProviders' });

      // Listen for messages
      window.addEventListener('message', (event) => {
        const msg = event.data;
        switch (msg.type) {
          case 'providers':
            providers = msg.payload || [];
            renderProviders();
            break;
          case 'models':
            models = msg.payload || [];
            renderModels();
            break;
          case 'sessionCreated':
            createBtn.disabled = false;
            createBtn.textContent = '创建会话';
            break;
          case 'workspacePath':
            workspaceInput.value = msg.payload;
            break;
          case 'error':
            createBtn.disabled = false;
            createBtn.textContent = '创建会话';
            errorMsg.textContent = msg.payload?.message || 'Unknown error';
            errorMsg.style.display = 'block';
            break;
        }
      });

      function renderProviders() {
        providerSelect.innerHTML = '<option value="">-- 使用默认' + (defaultProviderVal ? ' (' + defaultProviderVal + ')' : '') + ' --</option>';
        providers.forEach(p => {
          const opt = document.createElement('option');
          opt.value = p.id;
          opt.textContent = p.name || p.id;
          providerSelect.appendChild(opt);
        });
      }

      function renderModels() {
        modelSelect.innerHTML = '<option value="">-- 使用默认' + (defaultModelVal ? ' (' + defaultModelVal + ')' : '') + ' --</option>';
        models.forEach(m => {
          const opt = document.createElement('option');
          opt.value = m.id;
          opt.textContent = m.name || m.id;
          modelSelect.appendChild(opt);
        });
        modelSelect.disabled = false;
      }

      // When provider changes, fetch models
      providerSelect.addEventListener('change', () => {
        const provider = providerSelect.value;
        modelSelect.disabled = true;
          modelSelect.innerHTML = '<option value="">加载中...</option>';
        models = [];
        if (provider) {
          vscode.postMessage({ type: 'getModels', payload: { provider } });
        } else {
          modelSelect.innerHTML = '<option value="">-- 请先选择提供商 --</option>';
        }
      });

      // Browse button — open VS Code directory picker
      browseBtn.addEventListener('click', () => {
        vscode.postMessage({ type: 'browseWorkspace' });
      });

      createBtn.addEventListener('click', () => {
        createBtn.disabled = true;
        createBtn.textContent = '创建中...';
        errorMsg.style.display = 'none';

        const description = descriptionInput.value.trim() || undefined;
        const provider = providerSelect.value || defaultProviderVal || undefined;
        const model = modelSelect.value || defaultModelVal || undefined;
        const workspace = workspaceInput.value.trim() || undefined;
        const category = document.querySelector('input[name="category"]:checked')?.value || 'normal';

        vscode.postMessage({
          type: 'createSession',
          payload: { description, workspace, provider, model, category }
        });
      });

      cancelBtn.addEventListener('click', () => {
        vscode.postMessage({ type: 'cancel' });
      });
    })();
  </script>
</body>
</html>`
  }

  private async handleWebViewMessage(sessionId: string, panel: vscode.WebviewPanel, message: WebViewMessage) {
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

      case 'openCrewPanel':
        this.openCrewPanel(sessionId)
        break

      case 'openChat':
        this.openChat(message.payload.sessionId, message.payload.executionId)
        break

      case 'runnerAction':
        await this.handleRunnerAction(sessionId, panel, message.payload)
        break

      case 'fetchRunnerStatus':
        await this.handleFetchRunnerStatus(sessionId, panel)
        break

      case 'fetchSessionStats':
        await this.handleFetchSessionStats(sessionId, panel)
        break

      case 'getSession':
        await this.handleGetSession(sessionId, panel)
        break

      case 'fetchAgents':
        await this.handleFetchAgents(sessionId, panel)
        break

      case 'openFile':
        this.handleOpenFile(message.payload)
        break

      case 'uploadFile':
        await this.handleUploadFile(panel, message.payload)
        break

      case 'refreshChat':
        await this.handleRefreshChat(sessionId, panel)
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

      // ==================== Crew (Orchestration) handlers ====================
      case 'fetchCrewExecutions':
        await this.handleFetchCrewExecutions(panel, message.payload)
        break

      case 'fetchCrewDetail':
        await this.handleFetchCrewDetail(panel, message.payload)
        break

      case 'submitCrew':
        await this.handleSubmitCrew(panel, message.payload)
        break

      case 'abortCrew':
        await this.handleAbortCrew(panel, message.payload)
        break

      case 'deleteCrew':
        await this.handleDeleteCrew(panel, message.payload)
        break

      case 'fetchCrewConfigs':
        await this.handleFetchCrewConfigs(panel, message.payload)
        break

      case 'fetchCrewConfigDetail':
        await this.handleFetchCrewConfigDetail(panel, message.payload)
        break

      case 'saveCrewConfig':
        await this.handleSaveCrewConfig(panel, message.payload)
        break

      case 'openCrewConfigFile':
        await this.handleOpenCrewConfigFile(message.payload)
        break

      case 'confirmAction':
        await this.handleConfirmAction(panel, message.payload)
        break

      // ==================== Agent Config handlers ====================
      case 'fetchAgentConfig':
        await this.handleFetchAgentConfig(sessionId, panel, message.payload)
        break

      case 'updateAgentConfig':
        await this.handleUpdateAgentConfig(sessionId, panel, message.payload)
        break

      case 'fetchLLMProviders':
        await this.handleFetchLLMProviders(panel)
        break

      case 'fetchLLMModels':
        await this.handleFetchLLMModels(panel, message.payload)
        break

      // ==================== Commands handlers ====================
      case 'fetchCommands':
        await this.handleFetchCommands(panel)
        break

      // ==================== Turn summary (concise mode) handlers ====================
      case 'fetchTurns':
        await this.handleFetchTurns(panel, message.payload)
        break

      // ==================== Search handlers ====================
      case 'searchMessages':
        await this.handleSearchMessages(panel, sessionId, message.payload)
        break

      case 'getSearchFilters':
        await this.handleGetSearchFilters(panel, sessionId)
        break

      // ==================== File diff handlers ====================
      case 'viewDiff':
        await this.handleViewFileDiff(panel, sessionId, message.payload)
        break
    }
  }

  private async initializeSession(sessionId: string, panel: vscode.WebviewPanel) {
    try {
      // If socket already exists (e.g., created by crew panel), skip reconnection
      if (this.socketClients.has(sessionId)) {
        // Register chat panel handlers on the existing socket
        const existingClient = this.socketClients.get(sessionId)!
        existingClient.on('onConnect', 'chat', () => {
          this.postToPanel(panel, { type: 'connected', payload: { connected: true } } as ExtensionToWebView)
        })
        existingClient.on('onDisconnect', 'chat', () => {
          this.postToPanel(panel, { type: 'connected', payload: { connected: false } } as ExtensionToWebView)
        })
        existingClient.on('onMessage', 'chat', (msg) => {
          // Don't forward crew events to chat panel
          if (msg.message_type === 'system_message' && msg.data?.crew_event) return
          this.postToPanel(panel, { type: 'message', payload: msg } as ExtensionToWebView)
        })
        existingClient.on('onError', 'chat', (error) => {
          const errorInfo = (error as any)?.data || {}
          this.postToPanel(panel, {
            type: 'error',
            payload: {
              message: errorInfo.content || errorInfo.message || extractErrorMessage(error),
              severity: errorInfo.severity || 'error',
              recovery_hint: errorInfo.recovery_hint,
            },
          } as ExtensionToWebView)
        })
        // Still need to fetch agents and history for the chat panel
        await this.fetchAgentsAndHistory(sessionId, panel)
        return
      }

      // Create socket client
      const socketClient = new SocketClient(this.configManager, () => this.authManager.token)
      socketClient.onAuthError = this._onAuthError
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
          // Route crew events to crew panel if it exists
          if (msg.message_type === 'system_message' && msg.data?.crew_event) {
            const crewPanel = this.crewPanels.get(sessionId)
            if (crewPanel) {
              this.postToPanel(crewPanel, { type: 'crewEvent', payload: msg.data.payload } as ExtensionToWebView)
              return // Don't forward crew events to chat panel
            }
          }
          this.postToPanel(panel, { type: 'message', payload: msg } as ExtensionToWebView)
        },
        onError: (error) => {
          const errorInfo = (error as any)?.data || {}
          this.postToPanel(panel, {
            type: 'error',
            payload: {
              message: errorInfo.content || errorInfo.message || extractErrorMessage(error),
              severity: errorInfo.severity || 'error',
              recovery_hint: errorInfo.recovery_hint,
            },
          } as ExtensionToWebView)
        },
      })

      // Connect and subscribe
      console.log('[ChatWebView] Connecting socket...')
      await socketClient.connect()
      console.log('[ChatWebView] Socket connected, subscribing...')
      const unsub = await socketClient.subscribe(sessionId)
      this.socketUnsubs.set(sessionId, unsub)
      console.log('[ChatWebView] Subscribed to', sessionId)

      // Fetch session agents, history, and start polling
      await this.fetchAgentsAndHistory(sessionId, panel)
    } catch (error: any) {
      this.postToPanel(panel, {
        type: 'error',
        payload: { message: extractErrorMessage(error, 'Failed to initialize') },
      } as ExtensionToWebView)
    }
  }

  private async fetchAgentsAndHistory(sessionId: string, panel: vscode.WebviewPanel) {
    // Fetch session agents and send default agent ID to WebView
    try {
      console.log('[ChatWebView] Fetching agents for', sessionId)
      const agents = await this.apiClient.getSessionAgents(sessionId)
      console.log(
        '[ChatWebView] Agents:',
        JSON.stringify(agents.map((a: any) => ({ id: a.agent_id, role: a.role, name: a.name })))
      )
      const defaultAgentId =
        agents.find((a: any) => a.role === 'main_agent' || a.role === 'main-agent')?.agent_id || agents[0]?.agent_id
      console.log('[ChatWebView] defaultAgentId:', defaultAgentId)
      if (defaultAgentId) {
        this.postToPanel(panel, {
          type: 'agents',
          payload: { agents, defaultAgentId },
        } as ExtensionToWebView)
      }
    } catch (e) {
      console.error('[ChatWebView] Failed to fetch agents:', e)
    }

    // Load initial history (with executionId filter if set)
    const execId = this.sessionExecutionIds.get(sessionId)
    await this.handleLoadHistory(sessionId, panel, { skip: 0, limit: 50, executionId: execId })

    // Start runner polling
    this.startRunnerPolling(sessionId, panel)
  }

  private async handleSendMessage(
    sessionId: string,
    panel: vscode.WebviewPanel,
    payload: { content: string; receiverId?: string; subscription?: string; files?: any[]; messageId?: string }
  ) {
    const socketClient = this.socketClients.get(sessionId)
    console.log('[ChatWebView] handleSendMessage:', {
      sessionId,
      hasSocket: !!socketClient,
      receiverId: payload.receiverId,
      subscription: payload.subscription,
      content: payload.content?.substring(0, 50),
    })

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
        subscription: payload.subscription,
        files: payload.files,
      })
      console.log('[ChatWebView] socket.sendUserMessage completed successfully')
    } catch (error: any) {
      console.log('[ChatWebView] socket.sendUserMessage FAILED:', error.message)
      this.postToPanel(panel, {
        type: 'error',
        payload: { message: extractErrorMessage(error, 'Send failed') },
      } as ExtensionToWebView)
    }
  }

  private async handleLoadHistory(
    sessionId: string,
    panel: vscode.WebviewPanel,
    payload: { skip: number; limit: number; executionId?: string }
  ) {
    try {
      const response = await this.apiClient.getSessionMessages(
        sessionId,
        payload.skip,
        payload.limit,
        payload.executionId
      )
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
        payload: { message: extractErrorMessage(error, 'Failed to load history') },
      } as ExtensionToWebView)
    }
  }

  private async handlePermissionResponse(
    sessionId: string,
    payload: { granted: boolean; session_action?: string; requestId?: string; receiverId?: string }
  ) {
    const socketClient = this.socketClients.get(sessionId)
    if (!socketClient) return

    try {
      await socketClient.sendPermissionResponse({
        granted: payload.granted,
        session_action: payload.session_action,
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
        // 延迟刷新状态
        setTimeout(async () => {
          try {
            const status = await this.apiClient.getRunnerStatus(sessionId)
            if (status) {
              this.postToPanel(panel, { type: 'runnerStatus', payload: status } as ExtensionToWebView)
            }
          } catch {}
        }, 3000)
      } else {
        await this.apiClient.restartRunner(sessionId)
        vscode.window.showInformationMessage('Runner starting...')
        // 轮询等待 runner 真正变为 alive（最多等 30 秒，每 2 秒检查一次）
        // 避免立即 getRunnerStatus() 时 runner 尚在 'starting' 状态，
        // 导致 WebView 中 runnerAlive computed 未变为 true，AgentSidebar 的自动轮询无法启动
        for (let i = 0; i < 15; i++) {
          try {
            const status = await this.apiClient.getRunnerStatus(sessionId)
            if (status) {
              this.postToPanel(panel, { type: 'runnerStatus', payload: status } as ExtensionToWebView)
              if (status.status === 'alive') {
                break
              }
            }
          } catch {}
          await new Promise((r) => setTimeout(r, 2000))
        }
      }
      this.postToPanel(panel, { type: 'runnerActionResult', payload: { success: true } } as ExtensionToWebView)
    } catch (error: any) {
      showErrorNotification(error, 'Runner action failed')
      this.postToPanel(panel, {
        type: 'runnerActionResult',
        payload: { success: false, error: extractErrorMessage(error) },
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

  private async handleFetchSessionStats(sessionId: string, panel: vscode.WebviewPanel) {
    try {
      const stats = await this.apiClient.getSessionStats(sessionId)
      this.postToPanel(panel, { type: 'sessionStats', payload: stats } as ExtensionToWebView)
    } catch (error: any) {
      console.error('Failed to fetch session stats:', error)
    }
  }

  private async handleGetSession(sessionId: string, panel: vscode.WebviewPanel) {
    try {
      const session = await this.apiClient.getSession(sessionId)
      this.postToPanel(panel, { type: 'session', payload: session } as ExtensionToWebView)
    } catch (error: any) {
      console.error('Failed to fetch session:', error)
    }
  }

  private async handleFetchAgents(sessionId: string, panel: vscode.WebviewPanel) {
    try {
      const agents = await this.apiClient.getSessionAgents(sessionId)
      const defaultAgentId =
        agents.find((a: any) => a.role === 'main_agent' || a.role === 'main-agent')?.agent_id || agents[0]?.agent_id
      this.postToPanel(panel, {
        type: 'agents',
        payload: { agents, defaultAgentId },
      } as ExtensionToWebView)
    } catch (error: any) {
      console.error('Failed to fetch agents:', error)
    }
  }

  private async handleFetchTurns(
    panel: vscode.WebviewPanel,
    payload: { sessionId: string; skip: number; limit: number; executionId?: string }
  ) {
    try {
      const { sessionId, skip, limit, executionId } = payload
      const execId = executionId || this.sessionExecutionIds.get(sessionId)
      const response = await this.apiClient.getSessionTurns(sessionId, skip, limit, execId)
      this.postToPanel(panel, { type: 'turnsData', payload: response } as ExtensionToWebView)
    } catch (error: any) {
      console.error('Failed to fetch turns:', error)
      this.postToPanel(panel, {
        type: 'error',
        payload: { message: error.message || 'Failed to fetch turns' },
      } as ExtensionToWebView)
    }
  }

  private handleOpenFile(payload: { path: string }) {
    if (payload.path) {
      const fileUri = vscode.Uri.file(payload.path)
      vscode.commands.executeCommand('vscode.open', fileUri)
    }
  }

  private async handleUploadFile(
    panel: vscode.WebviewPanel,
    payload: { fileName: string; fileType: string; base64Data: string; fileSize: number }
  ) {
    try {
      // 生成唯一文件名和路径（不依赖 userId，使用 uploads/日期 路径）
      const parts = payload.fileName.split('.')
      const extension = parts.length > 1 ? parts.pop() : ''
      const nameWithoutExt = parts.join('.')
      const uniqueId = Math.random().toString(36).substring(6)
      // 使用 encodeURIComponent 编码非 ASCII 字符（如中文），避免 S3 Key 编码问题
      const sanitizedName = encodeURIComponent(nameWithoutExt)
      const safeFilename = extension ? `${sanitizedName}_${uniqueId}.${extension}` : `${sanitizedName}_${uniqueId}`

      const now = new Date()
      const year = now.getFullYear()
      const month = String(now.getMonth() + 1).padStart(2, '0')
      const day = String(now.getDate()).padStart(2, '0')
      const path = `uploads/${year}${month}${day}/${safeFilename}`

      // 将 base64 转为 Buffer
      const buffer = Buffer.from(payload.base64Data, 'base64')

      const storageType = this.configManager.storageType
      let s3Endpoint: string
      let s3Bucket: string
      let s3Credentials: { accessKeyId: string; secretAccessKey: string }
      let publicUrlBase: string

      if (storageType === 'cloudflare') {
        // Cloudflare R2
        s3Endpoint = `https://${this.configManager.cloudflareAccountId}.r2.cloudflarestorage.com`
        s3Bucket = this.configManager.cloudflareBucket || 'upload'
        s3Credentials = {
          accessKeyId: this.configManager.cloudflareAccessKeyId,
          secretAccessKey: this.configManager.cloudflareSecretAccessKey,
        }
        const cfPublicUrl = this.configManager.cloudflarePublicUrl
        publicUrlBase = cfPublicUrl
          ? cfPublicUrl
          : `https://${s3Bucket}.${this.configManager.cloudflareAccountId}.r2.dev`
      } else if (storageType === 'supabase') {
        // Supabase Storage (S3 兼容端点)
        const supabaseUrl = this.configManager.supabaseUrl
        const s3AccessKey = this.configManager.supabaseS3AccessKeyId
        const s3SecretKey = this.configManager.supabaseS3SecretAccessKey
        if (!supabaseUrl || !s3AccessKey || !s3SecretKey) {
          throw new Error(
            'Supabase S3 configuration incomplete. Set supabaseUrl, supabaseS3AccessKeyId and supabaseS3SecretAccessKey.'
          )
        }
        s3Endpoint = `${supabaseUrl}/storage/v1/s3`
        s3Bucket = 'upload'
        s3Credentials = { accessKeyId: s3AccessKey, secretAccessKey: s3SecretKey }
        publicUrlBase = `${supabaseUrl}/storage/v1/object/public/${s3Bucket}`
      } else {
        throw new Error('No storage backend configured. Please set Supabase or Cloudflare R2 settings.')
      }

      // 统一使用 S3 兼容 API 上传
      const { S3Client, PutObjectCommand } = await import('@aws-sdk/client-s3')
      const s3Client = new S3Client({
        region: 'auto',
        endpoint: s3Endpoint,
        credentials: s3Credentials,
        forcePathStyle: true,
      })

      await s3Client.send(
        new PutObjectCommand({
          Bucket: s3Bucket,
          Key: path,
          Body: buffer,
          ContentType: payload.fileType,
        })
      )

      const url = `${publicUrlBase}/${path}`

      this.postToPanel(panel, {
        type: 'fileUploaded',
        payload: {
          name: payload.fileName,
          url,
          path,
          size: payload.fileSize,
          type: payload.fileType,
        },
      } as ExtensionToWebView)
    } catch (error: any) {
      console.error('[UploadFile] Failed:', error.message)
      this.postToPanel(panel, {
        type: 'error',
        payload: { message: extractErrorMessage(error, 'Upload failed'), fileName: payload.fileName },
      } as ExtensionToWebView)
    }
  }

  private async handleRefreshChat(sessionId: string, panel: vscode.WebviewPanel) {
    console.log('[ChatWebView] Refreshing chat session:', sessionId)
    // Close current panel — onDidDispose cleans up socket + poll timers
    panel.dispose()
    // Open a brand new chat panel from scratch
    await this.openChat(sessionId)
  }

  private async handleFetchTasks(
    panel: vscode.WebviewPanel,
    payload: {
      skip?: number
      limit?: number
      status?: string
      priority?: string
      keyword?: string
      session_id?: string
    }
  ) {
    try {
      const response = await this.apiClient.client.get('/task/tasks', {
        params: {
          skip: payload.skip ?? 0,
          limit: payload.limit ?? 50,
          status: payload.status,
          priority: payload.priority,
          keyword: payload.keyword,
          session_id: payload.session_id,
          order_by: 'created_at desc',
        },
      })
      this.postToPanel(panel, { type: 'tasks', payload: response.data } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: extractErrorMessage(error) } } as ExtensionToWebView)
    }
  }

  private async handleFetchTaskDetail(panel: vscode.WebviewPanel, payload: { taskId: string }) {
    try {
      const response = await this.apiClient.client.get(`/task/${payload.taskId}`, {
        params: { include_comments: true },
      })
      this.postToPanel(panel, { type: 'taskDetail', payload: response.data } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: extractErrorMessage(error) } } as ExtensionToWebView)
    }
  }

  private async handleCreateTask(panel: vscode.WebviewPanel, payload: any) {
    try {
      const response = await this.apiClient.client.post('/task/', payload)
      this.postToPanel(panel, { type: 'taskCreated', payload: response.data } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: extractErrorMessage(error) } } as ExtensionToWebView)
    }
  }

  private async handleUpdateTask(panel: vscode.WebviewPanel, payload: { taskId: string; data: any }) {
    try {
      await this.apiClient.client.put(`/task/${payload.taskId}`, payload.data)
      this.postToPanel(panel, { type: 'taskUpdated', payload: { taskId: payload.taskId } } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: extractErrorMessage(error) } } as ExtensionToWebView)
    }
  }

  private async handleDeleteTask(panel: vscode.WebviewPanel, payload: { taskId: string }) {
    try {
      await this.apiClient.client.delete(`/task/${payload.taskId}`)
      this.postToPanel(panel, { type: 'taskDeleted', payload: { taskId: payload.taskId } } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: extractErrorMessage(error) } } as ExtensionToWebView)
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
      this.postToPanel(panel, { type: 'error', payload: { message: extractErrorMessage(error) } } as ExtensionToWebView)
    }
  }

  private async handleFetchJobs(
    panel: vscode.WebviewPanel,
    payload: {
      skip?: number
      limit?: number
      status?: string
      job_type?: string
      keyword?: string
      session_id?: string
    }
  ) {
    try {
      const response = await this.apiClient.client.get('/job/jobs', {
        params: {
          skip: payload.skip ?? 0,
          limit: payload.limit ?? 50,
          status: payload.status,
          job_type: payload.job_type,
          keyword: payload.keyword,
          session_id: payload.session_id,
          order_by: 'created_at desc',
        },
      })
      this.postToPanel(panel, { type: 'jobs', payload: response.data } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: extractErrorMessage(error) } } as ExtensionToWebView)
    }
  }

  private async handleFetchJobDetail(panel: vscode.WebviewPanel, payload: { jobId: string }) {
    try {
      const response = await this.apiClient.client.get(`/job/${payload.jobId}`, {
        params: { execution_limit: 50 },
      })
      this.postToPanel(panel, { type: 'jobDetail', payload: response.data } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: extractErrorMessage(error) } } as ExtensionToWebView)
    }
  }

  private async handleExecuteJob(panel: vscode.WebviewPanel, payload: { jobId: string }) {
    try {
      await this.apiClient.client.post(`/job/${payload.jobId}/execute`)
      this.postToPanel(panel, { type: 'jobExecuted', payload: { jobId: payload.jobId } } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: extractErrorMessage(error) } } as ExtensionToWebView)
    }
  }

  private async handlePauseJob(panel: vscode.WebviewPanel, payload: { jobId: string }) {
    try {
      await this.apiClient.client.post(`/job/${payload.jobId}/pause`)
      this.postToPanel(panel, { type: 'jobPaused', payload: { jobId: payload.jobId } } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: extractErrorMessage(error) } } as ExtensionToWebView)
    }
  }

  private async handleResumeJob(panel: vscode.WebviewPanel, payload: { jobId: string }) {
    try {
      await this.apiClient.client.post(`/job/${payload.jobId}/resume`)
      this.postToPanel(panel, { type: 'jobResumed', payload: { jobId: payload.jobId } } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: extractErrorMessage(error) } } as ExtensionToWebView)
    }
  }

  private async handleDeleteJob(panel: vscode.WebviewPanel, payload: { jobId: string }) {
    try {
      await this.apiClient.client.delete(`/job/${payload.jobId}`)
      this.postToPanel(panel, { type: 'jobDeleted', payload: { jobId: payload.jobId } } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: extractErrorMessage(error) } } as ExtensionToWebView)
    }
  }

  // ==================== Crew Handler Methods ====================

  private async handleFetchCrewExecutions(
    panel: vscode.WebviewPanel,
    payload?: { session_id?: string; status?: string }
  ) {
    try {
      const result = await this.apiClient.getCrews(payload)
      this.postToPanel(panel, { type: 'crewExecutions', payload: result } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: extractErrorMessage(error) } } as ExtensionToWebView)
    }
  }

  private async handleFetchCrewDetail(panel: vscode.WebviewPanel, payload: { executionId: string }) {
    try {
      const result = await this.apiClient.getCrewDetail(payload.executionId)
      this.postToPanel(panel, { type: 'crewDetail', payload: result } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: extractErrorMessage(error) } } as ExtensionToWebView)
    }
  }

  private async handleSubmitCrew(
    panel: vscode.WebviewPanel,
    payload: { yaml_content?: string; yaml_path?: string; session_id: string }
  ) {
    try {
      await this.apiClient.submitCrew(payload)
      // Fetch full execution list to get all records (including previous ones)
      const listResult = await this.apiClient.getCrews({ session_id: payload.session_id })
      this.postToPanel(panel, { type: 'crewExecutions', payload: listResult } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: extractErrorMessage(error) } } as ExtensionToWebView)
    }
  }

  private async handleAbortCrew(panel: vscode.WebviewPanel, payload: { executionId: string }) {
    try {
      await this.apiClient.abortCrew(payload.executionId)
      this.postToPanel(panel, {
        type: 'crewEvent',
        payload: { event: 'aborted', execution_id: payload.executionId, status: 'aborted' },
      } as ExtensionToWebView)
      vscode.window.showInformationMessage('编排已中止')
    } catch (error: any) {
      showErrorNotification(error, '中止失败')
      this.postToPanel(panel, { type: 'error', payload: { message: extractErrorMessage(error) } } as ExtensionToWebView)
    }
  }

  private async handleDeleteCrew(panel: vscode.WebviewPanel, payload: { executionId: string }) {
    try {
      await this.apiClient.deleteCrew(payload.executionId)
      this.postToPanel(panel, {
        type: 'crewEvent',
        payload: { event: 'deleted', execution_id: payload.executionId },
      } as ExtensionToWebView)
      vscode.window.showInformationMessage('编排已删除')
    } catch (error: any) {
      showErrorNotification(error, '删除失败')
      this.postToPanel(panel, { type: 'error', payload: { message: extractErrorMessage(error) } } as ExtensionToWebView)
    }
  }

  private async handleFetchCrewConfigs(
    panel: vscode.WebviewPanel,
    payload: { workspace?: string; session_id?: string }
  ) {
    try {
      // Resolve workspace from session_id if not provided directly
      let workspace = payload.workspace
      if (!workspace && payload.session_id) {
        const session = await this.apiClient.getSession(payload.session_id)
        workspace = session.workspace || ''
      }
      if (!workspace) {
        this.postToPanel(panel, { type: 'crewConfigs', payload: { configs: [], total: 0 } } as ExtensionToWebView)
        return
      }
      const result = await this.apiClient.listCrewConfigs(workspace)
      this.postToPanel(panel, { type: 'crewConfigs', payload: result } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: extractErrorMessage(error) } } as ExtensionToWebView)
    }
  }

  private async handleFetchCrewConfigDetail(
    panel: vscode.WebviewPanel,
    payload: { filename: string; workspace: string }
  ) {
    try {
      const result = await this.apiClient.getCrewConfig(payload.filename, payload.workspace)
      this.postToPanel(panel, { type: 'crewConfigDetail', payload: result } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: extractErrorMessage(error) } } as ExtensionToWebView)
    }
  }

  private async handleSaveCrewConfig(
    panel: vscode.WebviewPanel,
    payload: { filename: string; workspace: string; content: string }
  ) {
    try {
      const result = await this.apiClient.saveCrewConfig(payload.filename, payload.workspace, payload.content)
      this.postToPanel(panel, { type: 'crewConfigDetail', payload: result } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, { type: 'error', payload: { message: extractErrorMessage(error) } } as ExtensionToWebView)
    }
  }

  private async handleOpenCrewConfigFile(payload: { sessionId: string; crewName: string }) {
    try {
      // Get session workspace
      const session = await this.apiClient.getSession(payload.sessionId)
      const workspace = session?.workspace
      if (!workspace) {
        vscode.window.showErrorMessage('该会话没有关联的工作空间')
        return
      }

      // List crew configs and find matching file
      const result = await this.apiClient.listCrewConfigs(workspace)
      const matching = result.configs.find((cfg) => cfg.name === payload.crewName)
      if (!matching) {
        vscode.window.showErrorMessage(`未找到编排 '${payload.crewName}' 对应的配置文件`)
        return
      }

      // Open file in VS Code
      const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(matching.path))
      vscode.window.showTextDocument(doc)
    } catch (error: any) {
      showErrorNotification(error, '打开配置文件失败')
    }
  }

  private async handleConfirmAction(
    panel: vscode.WebviewPanel,
    payload: { action: string; executionId: string; message: string }
  ) {
    const confirmed = await vscode.window.showWarningMessage(payload.message, { modal: true }, '确定')
    if (confirmed !== '确定') return

    // Dispatch to the actual handler
    switch (payload.action) {
      case 'abortCrew':
        await this.handleAbortCrew(panel, { executionId: payload.executionId })
        break
      case 'deleteCrew':
        await this.handleDeleteCrew(panel, { executionId: payload.executionId })
        break
    }
  }

  private async startRunnerPolling(sessionId: string, panel: vscode.WebviewPanel) {
    this.stopRunnerPolling(sessionId)

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

    // 先取消订阅（引用计数归零），再断开连接
    const unsub = this.socketUnsubs.get(sessionId)
    if (unsub) {
      unsub().catch(() => {})
      this.socketUnsubs.delete(sessionId)
    }

    const socketClient = this.socketClients.get(sessionId)
    if (socketClient) {
      socketClient.disconnect()
      this.socketClients.delete(sessionId)
    }
  }

  private getWebviewContent(
    webview: vscode.Webview,
    sessionId: string,
    category?: string,
    executionId?: string
  ): string {
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
    const token = this.authManager.token
    const serverUrl = this.configManager.get('serverUrl')
    const wsUrl = this.configManager.get('wsUrl')

    const initData: Record<string, any> = {
      sessionId,
      token: token || '',
      serverUrl: serverUrl || 'http://localhost:8000',
      wsUrl: wsUrl || 'http://localhost:8000',
    }
    if (category) {
      initData.category = category
    }
    if (executionId) {
      initData.executionId = executionId
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

  private getCrewWebviewContent(webview: vscode.Webview, sessionId: string): string {
    const webviewDist = vscode.Uri.joinPath(this.context.extensionUri, 'dist', 'webview')
    const htmlPath = vscode.Uri.joinPath(webviewDist, 'crew.html')

    let html: string
    try {
      html = require('fs').readFileSync(htmlPath.fsPath, 'utf-8')
    } catch {
      return this.getFallbackHtml('Crew Management', 'Failed to load crew UI')
    }

    html = this.transformResourcePaths(webview, webviewDist, html)

    const token = this.authManager.token
    const serverUrl = this.configManager.get('serverUrl')
    const wsUrl = this.configManager.get('wsUrl')

    const initData = {
      sessionId,
      token: token || '',
      serverUrl: serverUrl || 'http://localhost:8000',
      wsUrl: wsUrl || 'http://localhost:8000',
    }
    const initTag = `<script type="application/json" id="init-data">${JSON.stringify(initData)}</script>`
    html = html.replace('</head>', initTag + '</head>')
    html = this.addCSP(webview, html)

    return html
  }

  private transformResourcePaths(webview: vscode.Webview, distPath: vscode.Uri, html: string): string {
    // Replace relative asset paths with webview URIs
    // Match: src="./assets/..." or href="./assets/..."
    return html.replace(/(src|href)=(["'])(\.\/assets\/[^"']+)\2/g, (_, attr, quote, relativePath) => {
      const uri = webview.asWebviewUri(vscode.Uri.joinPath(distPath, relativePath.replace(/^\.\//, '')))
      return `${attr}=${quote}${uri}${quote}`
    })
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

  // ==================== Agent Config Handler Methods ====================

  private async handleFetchAgentConfig(sessionId: string, panel: vscode.WebviewPanel, payload: { agentId: string }) {
    try {
      const config = await this.apiClient.getAgentConfig(sessionId, payload.agentId)
      this.postToPanel(panel, {
        type: 'agentConfig',
        payload: config,
      } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, {
        type: 'error',
        payload: { message: extractErrorMessage(error) },
      } as ExtensionToWebView)
    }
  }

  private async handleUpdateAgentConfig(
    sessionId: string,
    panel: vscode.WebviewPanel,
    payload: { agentId: string; config_content: Record<string, any> }
  ) {
    try {
      const config = await this.apiClient.updateAgentConfig(sessionId, payload.agentId, payload.config_content)
      this.postToPanel(panel, {
        type: 'agentConfigSaved',
        payload: config,
      } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, {
        type: 'error',
        payload: { message: extractErrorMessage(error) },
      } as ExtensionToWebView)
    }
  }

  private async handleFetchLLMProviders(panel: vscode.WebviewPanel) {
    try {
      const providers = await this.apiClient.getLLMProviders()
      this.postToPanel(panel, {
        type: 'providers',
        payload: providers,
      } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, {
        type: 'error',
        payload: { message: extractErrorMessage(error) },
      } as ExtensionToWebView)
    }
  }

  private async handleFetchLLMModels(panel: vscode.WebviewPanel, payload: { provider: string }) {
    try {
      const models = await this.apiClient.getLLMModels(payload.provider)
      this.postToPanel(panel, {
        type: 'models',
        payload: models,
      } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, {
        type: 'error',
        payload: { message: extractErrorMessage(error) },
      } as ExtensionToWebView)
    }
  }

  private async handleFetchCommands(panel: vscode.WebviewPanel) {
    try {
      const commands = await this.apiClient.getCommands()
      this.postToPanel(panel, {
        type: 'commands',
        payload: { commands },
      } as ExtensionToWebView)
    } catch {
      // Silently fail — webview has a fallback
      this.postToPanel(panel, {
        type: 'commands',
        payload: { commands: [] },
      } as ExtensionToWebView)
    }
  }

  // ==================== Search handlers ====================

  private async handleSearchMessages(
    panel: vscode.WebviewPanel,
    sessionId: string,
    payload: {
      keyword?: string
      message_type?: string
      sender_id?: string
      tool_name?: string
      order?: string
      skip?: number
      limit?: number
    }
  ) {
    try {
      const result = await this.apiClient.searchSessionMessages(sessionId, {
        keyword: payload.keyword,
        message_type: payload.message_type,
        sender_id: payload.sender_id,
        tool_name: payload.tool_name,
        order: (payload.order as 'desc' | 'asc') || 'desc',
        skip: payload.skip ?? 0,
        limit: payload.limit ?? 20,
      })
      this.postToPanel(panel, {
        type: 'searchMessages',
        payload: result,
      } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, {
        type: 'error',
        payload: { message: extractErrorMessage(error, '搜索消息失败') },
      } as ExtensionToWebView)
    }
  }

  private async handleGetSearchFilters(panel: vscode.WebviewPanel, sessionId: string) {
    try {
      const result = await this.apiClient.getSearchFilters(sessionId)
      this.postToPanel(panel, {
        type: 'searchFilters',
        payload: result,
      } as ExtensionToWebView)
    } catch (error: any) {
      this.postToPanel(panel, {
        type: 'error',
        payload: { message: extractErrorMessage(error, '获取搜索筛选选项失败') },
      } as ExtensionToWebView)
    }
  }

  private async handleViewFileDiff(
    panel: vscode.WebviewPanel,
    sessionId: string,
    payload: { turnId: string; filePath: string }
  ) {
    const { turnId, filePath } = payload
    try {
      if (!sessionId) {
        this.postToPanel(panel, {
          type: 'fileDiffResult',
          payload: { filePath, diff: '' },
        } as ExtensionToWebView)
        return
      }
      const result = await this.apiClient.getFileDiff(sessionId, turnId, filePath)
      this.postToPanel(panel, {
        type: 'fileDiffResult',
        payload: { filePath, diff: result.diff || '' },
      } as ExtensionToWebView)
    } catch {
      this.postToPanel(panel, {
        type: 'fileDiffResult',
        payload: { filePath, diff: '' },
      } as ExtensionToWebView)
    }
  }

  dispose() {
    // Dispose all panels and resources
    for (const [sessionId] of this.panels) {
      this.disposeSession(sessionId)
    }
    this.panels.clear()
    this.webviewAwayTimestamps.clear()
    // Cleanup window state listener
    if (this._windowStateDisposable) {
      this._windowStateDisposable.dispose()
      this._windowStateDisposable = null
    }
  }
}
