/**
 * AudioWorklet processor — 在音频线程中累积 PCM 采样并发送到主线程。
 *
 * 由主线程通过 `audioContext.audioWorklet.addModule(url)` 加载。
 * 注意：此文件运行在 AudioWorklet 全局作用域中，不可使用 DOM API。
 *
 * @param {object} processorOptions
 * @param {number} [processorOptions.targetMs=128] 累积多少毫秒的音频后再发送
 */
class PcmCollectorProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super()
    const targetMs =
      (options.processorOptions && options.processorOptions.targetMs) || 128
    // sampleRate 是 AudioWorklet 全局变量
    this._targetSize = Math.round((sampleRate * targetMs) / 1000)
    this._chunks = []
    this._chunkCount = 0
  }

  process(inputs) {
    const input = inputs[0]
    if (input && input.length > 0 && input[0].length > 0) {
      // 拷贝一份，避免音频线程 buffer 被复用
      this._chunks.push(new Float32Array(input[0]))
      this._chunkCount += input[0].length
    }

    if (this._chunkCount >= this._targetSize) {
      const output = new Float32Array(this._chunkCount)
      let offset = 0
      for (const chunk of this._chunks) {
        output.set(chunk, offset)
        offset += chunk.length
      }
      this._chunks = []
      this._chunkCount = 0
      this.port.postMessage(output)
    }

    return true
  }
}

registerProcessor('pcm-collector', PcmCollectorProcessor)
