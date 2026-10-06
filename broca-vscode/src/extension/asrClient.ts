/**
 * Extension Host ASR WebSocket 客户端（Node.js）
 *
 * 连接后端 /api/asr/stream WebSocket 端点，发送音频帧，接收识别结果。
 * 与 Web 前端的 asrClient 协议一致，但使用 Node.js `ws` 模块。
 */

import WebSocket from 'ws'

export type AsrEvent =
  | { type: 'status'; state: 'loading' | 'ready' }
  | { type: 'partial'; text: string }
  | { type: 'final'; text: string }
  | { type: 'error'; message: string }

class AsrClient {
  private ws: WebSocket | null = null
  private _isConnected = false
  private _isReady = false

  get isConnected(): boolean {
    return this._isConnected
  }

  get isReady(): boolean {
    return this._isReady
  }

  /**
   * 连接到 ASR 服务。
   *
   * @param serverUrl 后端基础 URL，如 http://localhost:9000
   * @param token JWT token
   * @param onEvent 事件回调
   */
  async connect(serverUrl: string, token: string, onEvent: (e: AsrEvent) => void): Promise<void> {
    // 断开已有连接
    if (this.ws) {
      this.disconnect()
    }

    // 构建 WS URL: http(s) → ws(s)
    let wsBase = serverUrl.replace(/^http/, 'ws')
    if (wsBase.endsWith('/')) {
      wsBase = wsBase.slice(0, -1)
    }
    const tokenParam = token ? `?token=${encodeURIComponent(token)}` : ''
    const wsUrl = `${wsBase}/api/asr/stream${tokenParam}`

    return new Promise<void>((resolve, reject) => {
      const ws = new WebSocket(wsUrl)
      this.ws = ws

      const timeout = setTimeout(() => {
        if (ws.readyState !== WebSocket.OPEN) {
          ws.close()
          reject(new Error('ASR 连接超时 (10s)'))
        }
      }, 10000)

      ws.on('open', () => {
        clearTimeout(timeout)
        this._isConnected = true
        console.log('[AsrClient] WebSocket connected')
        resolve()
      })

      ws.on('message', (data: WebSocket.RawData) => {
        const str = typeof data === 'string' ? data : data.toString('utf-8')
        try {
          const msg = JSON.parse(str) as AsrEvent
          switch (msg.type) {
            case 'status':
              this._isReady = msg.state === 'ready'
              break
            case 'partial':
              break
            case 'final':
              break
            case 'error':
              break
          }
          onEvent(msg)
        } catch (e) {
          console.warn('[AsrClient] Failed to parse message:', str, e)
        }
      })

      ws.on('close', () => {
        clearTimeout(timeout)
        this._isConnected = false
        this._isReady = false
        this.ws = null
        console.log('[AsrClient] WebSocket closed')
      })

      ws.on('error', (err: Error) => {
        clearTimeout(timeout)
        if (!this._isConnected) {
          // 连接失败
          reject(new Error(`ASR 连接失败: ${err.message}`))
        } else {
          onEvent({ type: 'error', message: `ASR 连接错误: ${err.message}` })
        }
      })
    })
  }

  /**
   * 发送音频帧（16kHz Int16 PCM Buffer）。
   * 连接未建立或模型未就绪时静默忽略。
   */
  sendAudioFrame(data: Buffer): void {
    if (this.ws?.readyState === WebSocket.OPEN && this._isReady) {
      this.ws.send(data)
    }
  }

  /** 断开连接 */
  disconnect(): void {
    if (this.ws) {
      this.ws.removeAllListeners()
      if (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING) {
        this.ws.close()
      }
      this.ws = null
    }
    this._isConnected = false
    this._isReady = false
  }
}

export const asrClient = new AsrClient()
