/**
 * 浏览器麦克风音频采集服务
 *
 * 基于 AudioWorklet（替代已废弃的 ScriptProcessorNode），
 * 提供 16kHz / 16-bit / mono PCM 音频帧回调。
 * 若浏览器不支持 16kHz AudioContext，自动使用默认采样率并线性插值重采样。
 *
 * 音频链路：
 *   microphone → MediaStreamSource → AudioWorkletNode → zeroGain(0) → destination
 *   AudioWorkletNode 在音频线程累积采样 → postMessage → 主线程 Float32→Int16 → 回调
 *   zeroGain 断开实际播放，避免回声导致 ASR 重字。
 */

import workletUrl from './audioWorkletProcessor.js?url'

const TARGET_SAMPLE_RATE = 16000
const ACCUMULATE_TARGET_MS = 128 // 每 ~128ms 向主线程发送一帧

/** Float32 → Int16 转换（范围 [-1,1] → [-32768, 32767]） */
function float32To16Bit(float32: Float32Array): Int16Array {
  const int16 = new Int16Array(float32.length)
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]))
    int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff
  }
  return int16
}

/** 线性插值重采样 */
function resample(input: Float32Array, fromRate: number, toRate: number): Float32Array {
  if (fromRate === toRate) return input
  const ratio = fromRate / toRate
  const outputLength = Math.round(input.length / ratio)
  const output = new Float32Array(outputLength)
  for (let i = 0; i < outputLength; i++) {
    const srcIndex = i * ratio
    const index = Math.floor(srcIndex)
    const frac = srcIndex - index
    const a = input[index] ?? 0
    const b = input[index + 1] ?? 0
    output[i] = a + frac * (b - a)
  }
  return output
}

export class AudioRecorder {
  private audioContext: AudioContext | null = null
  private mediaStream: MediaStream | null = null
  private workletNode: AudioWorkletNode | null = null
  private source: MediaStreamAudioSourceNode | null = null
  private zeroGain: GainNode | null = null
  private _actualSampleRate = TARGET_SAMPLE_RATE
  private _isRecording = false

  get isRecording(): boolean {
    return this._isRecording
  }

  /**
   * 请求麦克风权限并开始录音。
   *
   * @param onAudioFrame 每 ~128ms 回调一次，参数为 16kHz Int16 PCM 数据的 ArrayBuffer
   * @throws DOMException (NotAllowedError) 如果用户拒绝权限
   * @throws Error 如果不是安全上下文（iPhone 通过 HTTP 访问时）
   */
  async start(onAudioFrame: (data: ArrayBuffer) => void): Promise<void> {
    // 安全上下文检查：iOS Safari / Android Chrome 要求 HTTPS 才开放 mediaDevices
    if (!window.isSecureContext) {
      throw new Error(
        '当前页面不是 HTTPS 环境，浏览器禁止使用麦克风。' +
        '请通过 https:// 地址访问（iPhone 首次访问需点击「访问此网站」信任自签证书）。'
      )
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error('浏览器不支持 getUserMedia，请使用最新版 Safari / Chrome')
    }

    // 重复调用时先清理上一次
    if (this._isRecording) {
      this.stop()
    }

    // 1. 请求麦克风权限
    this.mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        sampleRate: TARGET_SAMPLE_RATE,
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
      },
    })

    // 2. 创建 AudioContext（优先 16kHz，不支持时用默认）
    try {
      this.audioContext = new AudioContext({ sampleRate: TARGET_SAMPLE_RATE })
    } catch {
      this.audioContext = new AudioContext()
    }

    if (!this.audioContext.audioWorklet) {
      throw new Error('浏览器不支持 AudioWorklet，请使用最新版 Chrome / Firefox / Safari')
    }

    this._actualSampleRate = this.audioContext.sampleRate

    // 3. 加载 AudioWorklet 模块
    await this.audioContext.audioWorklet.addModule(workletUrl, {
      processorOptions: { targetMs: ACCUMULATE_TARGET_MS },
    })

    // 4. 创建节点并连接
    //    source → workletNode → zeroGain(0) → destination
    //    zeroGain 断开实际播放，防止麦克风音频回放到扬声器 → 回声 → ASR 重字
    this.source = this.audioContext.createMediaStreamSource(this.mediaStream)

    this.workletNode = new AudioWorkletNode(this.audioContext, 'pcm-collector', {
      numberOfInputChannels: 1,
      numberOfOutputChannels: 1,
      processorOptions: { targetMs: ACCUMULATE_TARGET_MS },
    })

    this.zeroGain = this.audioContext.createGain()
    this.zeroGain.gain.value = 0

    this.source.connect(this.workletNode)
    this.workletNode.connect(this.zeroGain)
    this.zeroGain.connect(this.audioContext.destination)

    // 5. 处理 worklet 发来的 Float32 数据 → 重采样 → Int16 → 回调
    let frameCount = 0
    this.workletNode.port.onmessage = (e: MessageEvent) => {
      if (!this._isRecording) return

      const float32 = e.data as Float32Array

      const output =
        this._actualSampleRate !== TARGET_SAMPLE_RATE
          ? resample(float32, this._actualSampleRate, TARGET_SAMPLE_RATE)
          : float32

      const int16 = float32To16Bit(output)

      // 诊断日志：每 20 帧（~2.5s）输出一次帧能量，用于排查音频质量
      if (++frameCount % 20 === 0) {
        let sumSq = 0
        for (let i = 0; i < output.length; i++) sumSq += output[i] * output[i]
        const rms = Math.sqrt(sumSq / output.length)
        console.debug(`[AudioRecorder] frame#${frameCount} samples=${output.length} rms=${rms.toFixed(5)}`)
      }

      onAudioFrame(int16.buffer)
    }

    this._isRecording = true
  }

  /** 停止录音，清理所有资源 */
  stop(): void {
    this._isRecording = false

    if (this.workletNode) {
      this.workletNode.port.onmessage = null
      this.workletNode.disconnect()
      this.workletNode = null
    }
    if (this.source) {
      this.source.disconnect()
      this.source = null
    }
    if (this.zeroGain) {
      this.zeroGain.disconnect()
      this.zeroGain = null
    }
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((t) => t.stop())
      this.mediaStream = null
    }
    if (this.audioContext) {
      this.audioContext.close().catch(() => {})
      this.audioContext = null
    }
  }

  /**
   * 检查麦克风权限和设备可用性。
   * @returns true 表示有可用麦克风且权限已授予
   */
  static async checkPermission(): Promise<boolean> {
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      return false
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      stream.getTracks().forEach((t) => t.stop())
      return true
    } catch {
      return false
    }
  }
}

/** 单例导出 */
export const audioRecorder = new AudioRecorder()
