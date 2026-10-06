/**
 * Extension Host 麦克风音频采集
 *
 * 由于 VSCode webview CSP 限制，无法在 webview 中使用 getUserMedia。
 * 在 Extension Host (Node.js) 中通过系统音频工具（sox/ffmpeg/arecord）采集麦克风音频。
 *
 * 输出格式：16kHz / 16-bit / mono PCM（原始字节流）
 */

import { spawn, ChildProcess, execFileSync } from 'child_process'
import * as os from 'os'
import * as fs from 'fs'
import * as path from 'path'

/**
 * VSCode from Dock/Finder doesn't inherit shell PATH (e.g. /opt/homebrew/bin).
 * Resolve binary by checking PATH + common install locations.
 */
const EXTRA_PATHS: Record<string, string[]> = {
  darwin: ['/opt/homebrew/bin', '/usr/local/bin', '/usr/local/homebrew/bin'],
  linux: ['/usr/local/bin'],
  win32: [],
}

function resolveBinary(name: string): string | null {
  // 1. Try PATH via `command -v`
  try {
    const sh = os.platform() === 'win32' ? 'cmd' : '/bin/sh'
    const cmd = os.platform() === 'win32' ? `where ${name}` : `command -v ${name}`
    const out = execFileSync(sh, ['/c', cmd], {
      stdio: ['ignore', 'pipe', 'ignore'],
      timeout: 5000,
    }).toString().trim()
    if (out) return out.split('\n')[0].trim()
  } catch {
    // not in PATH
  }
  // 2. Fallback: check common locations
  const extra = EXTRA_PATHS[os.platform()] || []
  for (const dir of extra) {
    const candidate = path.join(dir, name)
    if (fs.existsSync(candidate)) return candidate
  }
  return null
}

export interface AudioCaptureOptions {
  onAudioFrame: (data: Buffer) => void
  onError: (error: string) => void
}

/**
 * 128ms 帧大小：16000 Hz × 2 bytes/sample × 0.128s = 4096 samples × 2 = 8192 bytes
 * 与 Web 版 AudioWorklet 的 ACCUMULATE_TARGET_MS=128 保持一致。
 */
const FRAME_SIZE = 8192

class AudioCapture {
  private process: ChildProcess | null = null
  private _isCapturing = false
  private _frameBuffer: Buffer = Buffer.alloc(0)

  get isCapturing(): boolean {
    return this._isCapturing
  }

  /**
   * 检测系统是否安装了可用的音频采集工具。
   * 按平台优先级检测：
   *   macOS:   sox → ffmpeg
   *   Linux:   arecord → sox → ffmpeg
   *   Windows: ffmpeg
   */
  static async isSupported(): Promise<boolean> {
    const platform = os.platform()

    const tools =
      platform === 'darwin'
        ? ['sox', 'ffmpeg']
        : platform === 'win32'
          ? ['ffmpeg']
          : ['arecord', 'sox', 'ffmpeg'] // linux

    for (const tool of tools) {
      if (resolveBinary(tool)) return true
    }
    return false
  }

  /**
   * 启动系统音频采集。
   * 根据平台选择最佳命令，spawn 后 pipe stdout 作为 PCM 数据流。
   */
  async start(options: AudioCaptureOptions): Promise<void> {
    if (this._isCapturing) {
      this.stop()
    }

    const platform = os.platform()
    const built = this._buildCommand(platform)

    if (!built) {
      throw new Error('未找到可用的音频采集工具（sox/ffmpeg/arecord），请安装后重试')
    }
    const { command, args } = built

    try {
      this.process = spawn(command, args, {
        stdio: ['ignore', 'pipe', 'pipe'],
      })

      this._frameBuffer = Buffer.alloc(0)

      // 分帧：将不规则的 stdout chunk 切分为固定 128ms 帧再发送
      // 与 Web 版 AudioWorklet 行为一致，确保 ASR 流式解码 + endpoint 检测正常工作
      this.process.stdout!.on('data', (data: Buffer) => {
        if (!this._isCapturing) return
        this._frameBuffer = Buffer.concat([this._frameBuffer, data])
        while (this._frameBuffer.length >= FRAME_SIZE) {
          const frame = this._frameBuffer.subarray(0, FRAME_SIZE)
          this._frameBuffer = this._frameBuffer.subarray(FRAME_SIZE)
          options.onAudioFrame(Buffer.from(frame))
        }
      })

      let stderrBuffer = ''
      this.process.stderr!.on('data', (data: Buffer) => {
        stderrBuffer += data.toString()
        // 保留最近 1KB 用于错误报告
        if (stderrBuffer.length > 1024) {
          stderrBuffer = stderrBuffer.slice(-1024)
        }
      })

      this.process.on('error', (err: Error) => {
        this._isCapturing = false
        options.onError(`音频采集启动失败: ${err.message}`)
      })

      this.process.on('exit', (code) => {
        if (this._isCapturing && code !== null && code !== 0) {
          options.onError(`音频采集进程异常退出 (code=${code}): ${stderrBuffer.trim()}`)
        }
        this._isCapturing = false
        this.process = null
      })

      this._isCapturing = true
      console.log(`[AudioCapture] Started: ${command} ${args.join(' ')}`)
    } catch (err: any) {
      this._isCapturing = false
      this.process = null
      throw new Error(`音频采集启动失败: ${err.message}`)
    }
  }

  /** 停止采集，终止子进程 */
  stop(): void {
    this._isCapturing = false
    this._frameBuffer = Buffer.alloc(0)
    if (this.process) {
      try {
        this.process.kill('SIGTERM')
        // 给进程一点时间优雅退出
        const proc = this.process
        setTimeout(() => {
          if (proc.exitCode === null && proc.signalCode === null) {
            try {
              proc.kill('SIGKILL')
            } catch {
              /* already dead */
            }
          }
        }, 1000)
      } catch {
        /* already dead */
      }
      this.process = null
    }
    console.log('[AudioCapture] Stopped')
  }

  /** 根据平台构建采集命令，按优先级选择第一个可用的工具 */
  private _buildCommand(platform: string): { command: string; args: string[] } | null {
    const candidates: Array<{ command: string; args: string[] }> = []

    // 音频滤波（必须全部使用实时/零延迟滤波器，否则流式 ASR 会有明显延迟）：
    //   sox:   highpass 100 (去直流/低频) + gain 3 (固定提升 3dB)
    //   ffmpeg: highpass=f=100,lowpass=f=8000 (语音频带) + volume=2 (固定 2 倍增益)
    // 注意：不能用 dynaudnorm（1s 窗口）或 gain -n（需全局峰值），它们会缓冲导致延迟
    if (platform === 'darwin') {
      // macOS: sox → ffmpeg
      candidates.push({
        command: 'sox',
        args: ['-d', '-r', '16000', '-c', '1', '-b', '16', '-t', 'raw', '-', 'highpass', '100', 'gain', '3'],
      })
      // ffmpeg on macOS uses avfoundation for audio input
      candidates.push({
        command: 'ffmpeg',
        args: ['-y', '-f', 'avfoundation', '-i', ':0', '-ar', '16000', '-ac', '1',
          '-af', 'highpass=f=100,lowpass=f=8000,volume=2',
          '-f', 's16le', '-'],
      })
    } else if (platform === 'linux') {
      // Linux: arecord → sox → ffmpeg
      candidates.push({
        command: 'arecord',
        args: ['-r', '16000', '-f', 'S16_LE', '-c', '1', '-t', 'raw', '-'],
      })
      candidates.push({
        command: 'sox',
        args: ['-d', '-r', '16000', '-c', '1', '-b', '16', '-t', 'raw', '-', 'highpass', '100', 'gain', '3'],
      })
      candidates.push({
        command: 'ffmpeg',
        args: ['-y', '-f', 'alsa', '-i', 'default', '-ar', '16000', '-ac', '1',
          '-af', 'highpass=f=100,lowpass=f=8000,volume=2',
          '-f', 's16le', '-'],
      })
    } else {
      // Windows: ffmpeg
      candidates.push({
        command: 'ffmpeg',
        args: ['-y', '-f', 'dshow', '-i', 'audio=Default-Audio Device', '-ar', '16000', '-ac', '1',
          '-af', 'highpass=f=100,lowpass=f=8000,volume=2',
          '-f', 's16le', '-'],
      })
    }

    // Return the first candidate whose binary is available (PATH + common locations)
    for (const c of candidates) {
      const resolved = resolveBinary(c.command)
      if (resolved) {
        return { command: resolved, args: c.args }
      }
    }
    return null
  }
}

export { AudioCapture }
export const audioCapture = new AudioCapture()
