/**
 * ASR WebSocket 客户端
 *
 * 封装与后端 /api/asr/stream WebSocket 端点的通信逻辑。
 * 协议：客户端发送 binary frame (16kHz Int16 PCM)，服务端推送 JSON 消息。
 *
 * 消息格式（服务端 → 客户端）:
 *   { type: 'status',  state: 'loading' | 'ready' }
 *   { type: 'partial', text: '...' }
 *   { type: 'final',   text: '...' }
 *   { type: 'error',   message: '...' }
 */

// ==================== 类型定义 ====================

export type AsrEvent =
  | { type: 'status'; state: 'loading' | 'ready' }
  | { type: 'partial'; text: string }
  | { type: 'final'; text: string }
  | { type: 'error'; message: string }

// ==================== URL 构建 ====================

/**
 * 构建 ASR WebSocket URL。
 *
 * 优先级：
 *   1. VITE_ASR_WS_URL（完整 WebSocket 基础地址，如 ws://localhost:9000）
 *   2. 从 VITE_API_BASE_URL 推导
 *   3. 默认使用当前页面 origin
 */
function getAsrWsUrl(): string {
  const explicit = import.meta.env.VITE_ASR_WS_URL as string | undefined
  if (explicit) {
    return `${explicit.replace(/\/+$/, '')}/api/asr/stream`
  }

  const apiBase = (import.meta.env.VITE_API_BASE_URL as string | undefined) || '/api'

  if (apiBase.startsWith('http://') || apiBase.startsWith('https://')) {
    // 绝对 URL：http→ws, https→wss
    const wsBase = apiBase.replace(/^http/, 'ws')
    // 去掉末尾的 /api 后缀
    const base = wsBase.endsWith('/api') ? wsBase.slice(0, -4) : wsBase
    return `${base.replace(/\/+$/, '')}/api/asr/stream`
  }

  // 相对路径：使用当前页面 origin
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}/api/asr/stream`
}

// ==================== 客户端实现 ====================

const RECONNECT_DELAY_MS = 3000
const MAX_RECONNECT_ATTEMPTS = 3

export class AsrClient {
  private ws: WebSocket | null = null
  private _isConnected = false
  private _isReady = false // 模型加载完成
  private _onEvent: ((e: AsrEvent) => void) | null = null
  private _reconnectAttempts = 0
  private _shouldReconnect = false
  private _reconnectTimer: ReturnType<typeof setTimeout> | null = null

  get isConnected(): boolean {
    return this._isConnected
  }

  get isReady(): boolean {
    return this._isReady
  }

  /**
   * 连接到 ASR 服务。
   *
   * @param onEvent 事件回调（status / partial / final / error）
   */
  async connect(onEvent: (e: AsrEvent) => void): Promise<void> {
    // 如果已连接，先断开
    if (this.ws) {
      this.disconnect()
    }

    this._onEvent = onEvent
    this._reconnectAttempts = 0
    this._shouldReconnect = true

    await this._openSocket()
  }

  /**
   * 发送音频帧（16kHz Int16 PCM 的 ArrayBuffer）。
   * 连接未建立或模型未就绪时静默忽略。
   */
  sendAudioFrame(data: ArrayBuffer): void {
    if (this.ws?.readyState === WebSocket.OPEN && this._isReady) {
      this.ws.send(data)
    }
  }

  /** 断开连接并清理所有状态 */
  disconnect(): void {
    this._shouldReconnect = false

    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer)
      this._reconnectTimer = null
    }

    if (this.ws) {
      this.ws.onopen = null
      this.ws.onmessage = null
      this.ws.onclose = null
      this.ws.onerror = null
      if (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING) {
        this.ws.close()
      }
      this.ws = null
    }

    this._isConnected = false
    this._isReady = false
    this._onEvent = null
  }

  // ==================== 内部方法 ====================

  private _openSocket(): Promise<void> {
    return new Promise((resolve, reject) => {
      const token = localStorage.getItem('token') || ''
      const url = getAsrWsUrl()
      const wsUrl = token ? `${url}?token=${encodeURIComponent(token)}` : url

      const ws = new WebSocket(wsUrl)
      this.ws = ws

      const timeout = setTimeout(() => {
        if (ws.readyState !== WebSocket.OPEN) {
          ws.close()
          reject(new Error('ASR 连接超时 (10s)'))
        }
      }, 10000)

      ws.onopen = () => {
        clearTimeout(timeout)
        this._isConnected = true
        this._reconnectAttempts = 0
        console.debug('[AsrClient] WebSocket connected')
        resolve()
      }

      ws.onmessage = (event: MessageEvent) => {
        if (typeof event.data !== 'string') return // 忽略非 JSON 消息
        try {
          const msg = JSON.parse(event.data) as AsrEvent
          this._handleMessage(msg)
        } catch (e) {
          console.warn('[AsrClient] Failed to parse message:', event.data, e)
        }
      }

      ws.onclose = () => {
        clearTimeout(timeout)
        const wasConnected = this._isConnected
        this._isConnected = false
        this._isReady = false

        // 仅在曾成功连接且应重连时触发重连
        if (wasConnected && this._shouldReconnect && this._reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
          this._reconnectAttempts++
          console.debug(`[AsrClient] Disconnected, reconnecting (${this._reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})...`)
          this._reconnectTimer = setTimeout(() => {
            this._reconnectTimer = null
            if (this._shouldReconnect) {
              this._openSocket().catch((e) => {
                console.warn('[AsrClient] Reconnect failed:', e.message)
              })
            }
          }, RECONNECT_DELAY_MS)
        } else if (wasConnected) {
          // 不再重连（超限或主动断开），通知错误
          this._emit({ type: 'error', message: 'ASR 连接已断开' })
        }
      }

      ws.onerror = () => {
        // onclose 会紧随 onerror 触发，这里不重复处理
        console.debug('[AsrClient] WebSocket error')
      }
    })
  }

  private _handleMessage(msg: AsrEvent): void {
    if (msg.type === 'status') {
      this._isReady = msg.state === 'ready'
    }
    this._emit(msg)
  }

  private _emit(e: AsrEvent): void {
    this._onEvent?.(e)
  }
}

/** 单例导出 */
export const asrClient = new AsrClient()
