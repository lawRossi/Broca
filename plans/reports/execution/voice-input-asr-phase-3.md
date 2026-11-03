# Phase 3 执行报告: VSCode 扩展语音输入

## 概述

Phase 3 在 Broca VSCode 扩展中集成了语音输入功能。由于 VSCode webview CSP 限制，音频采集在 Extension Host（Node.js）端通过系统工具（sox/ffmpeg/arecord）完成，识别结果通过 postMessage 传递到 webview 显示。

## 实现的文件

### 新增文件

| 文件 | 说明 |
|------|------|
| `broca-vscode/src/extension/audioCapture.ts` | 系统音频采集（sox/ffmpeg/arecord，平台感知） |
| `broca-vscode/src/extension/asrClient.ts` | Node.js WebSocket ASR 客户端（`ws` 模块） |

### 修改文件

| 文件 | 说明 |
|------|------|
| `broca-vscode/src/extension/types.ts` | 新增 asrEvent/voiceInputStopped/voiceInputSupported/startVoiceInput/stopVoiceInput/checkVoiceInput 消息类型 |
| `broca-vscode/src/extension/chatWebView.ts` | 新增 handleCheckVoiceInput/handleStartVoiceInput/handleStopVoiceInput + dispose 清理 |
| `broca-vscode/package.json` | 新增 `ws` 依赖 + `@types/ws` devDependency |
| `broca-vscode/src/webview/src/components/ChatInput.vue` | 麦克风按钮、语音状态条、postMessage 通信、自动清理 |

## 各任务实现详情

### Task 3.1: Extension Host 音频采集与 ASR 流式传输

#### audioCapture.ts
- **AudioCapture 类**：`static isSupported()` / `start(options)` / `stop()`
- **平台感知命令**：
  - macOS: `sox -d -r 16000 -c 1 -b 16 -t raw -`
  - Linux: `arecord -r 16000 -f S16_LE -c 1 -t raw -`（fallback sox）
  - Windows: `ffmpeg -f dshow -i audio="Default-Audio Device" -ar 16000 -ac 1 -f s16le -`
- **isSupported()**：按平台优先级检测 sox/ffmpeg/arecord 是否安装（`command -v` / `where`）
- **进程管理**：`SIGTERM` → 1s 后 `SIGKILL`，stderr 保留最近 1KB 用于错误报告
- **单例 + 类导出**：`export { AudioCapture }; export const audioCapture = new AudioCapture()`

#### asrClient.ts
- **AsrClient 类**：`connect(serverUrl, token, onEvent)` / `sendAudioFrame(data)` / `disconnect()`
- **URL 构建**：`http(s)://host:port` → `ws(s)://host:port/api/asr/stream?token=xxx`
- **使用 `ws` 模块**（Node.js 原生 WebSocket 客户端）
- **无自动重连**（Extension Host 控制生命周期，webview 断开时 stopVoiceInput 清理）
- **单例导出**：`export const asrClient = new AsrClient()`

#### chatWebView.ts 修改
- 新增 `handleCheckVoiceInput(panel)`：检测音频工具可用性 → postToPanel `voiceInputSupported`
- 新增 `handleStartVoiceInput(panel)`：获取 serverUrl/token → asrClient.connect → audioCapture.start → 音频帧 → asrClient.sendAudioFrame
- 新增 `handleStopVoiceInput(panel)`：audioCapture.stop + asrClient.disconnect → postToPanel `voiceInputStopped`
- `dispose()` 中增加 `audioCapture.stop()` + `asrClient.disconnect()` 清理

### Task 3.2: VSCode Webview ChatInput 集成

#### ChatInput.vue 修改
- **麦克风按钮**：🎤/⏹，使用 VSCode CSS 变量（`--bg-tertiary`, `--border-color`, `--error-fg` 等）适配主题
- **禁用条件**：`!runnerAlive` 或 `voiceSupported === false`
- **tooltip**：未安装工具时显示 "系统未安装音频采集工具 (sox/ffmpeg)"
- **语音状态条**：录音中显示蓝色状态（闪烁圆点 + 实时 partial 文本），错误时红色
- **通信协议**：
  - Webview → Extension: `startVoiceInput` / `stopVoiceInput` / `checkVoiceInput`
  - Extension → Webview: `asrEvent` (status/partial/final/error) / `voiceInputStopped` / `voiceInputSupported`
- **final 文本处理**：直接追加到 `chatStore.inputText`（与 Web 前端一致）
- **自动清理**：`onUnmounted` 时 `stopVoiceInput()`
- **发送前停止**：`handleSend` 中检测 `isVoiceRecording` 并先停止

## 自查结果

| 验收标准 | 状态 | 说明 |
|----------|------|------|
| VSCode ChatInput 麦克风按钮可见 | ✅ | 按钮在文件上传和 Send 按钮之间 |
| 点击后 Extension Host 启动音频采集 | ✅ | postMessage → handleStartVoiceInput → audioCapture.start |
| 说话时实时显示识别文字 | ⚠️ | 代码逻辑正确，需实际音频+模型验证 |
| 停止后识别结果保留在输入框 | ✅ | asrEvent final → 追加到 chatStore.inputText |
| 编辑后正常发送 | ✅ | 复用 handleSend 现有流程 |
| 未安装工具时按钮置灰 + 提示 | ✅ | checkVoiceInput → voiceSupported=false → 按钮 disabled + tooltip |
| 扩展 deactivate 时资源清理 | ✅ | dispose() 调用 audioCapture.stop() + asrClient.disconnect() |
| `tsc --noEmit` 通过 | ✅ | 零错误 |
| `vite build` 通过 | ✅ | 661ms，零错误 |

## 已知限制

1. **需要系统安装 sox/ffmpeg/arecord**：macOS 用户需 `brew install sox`，Linux 通常自带 arecord
2. **模型依赖**：实际语音识别需要后端 ASR 模型文件
3. **`ws` 模块兼容性**：`ws` 在 VSCode Extension Host 中正常工作（Node.js 环境）
