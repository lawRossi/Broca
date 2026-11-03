# Phase 2 执行报告: Web 前端语音输入

## 概述

Phase 2 在 Broca Web 前端（Vue 3）的 ChatInput 组件中集成了语音输入功能。用户可点击麦克风按钮进行语音输入，输入框实时显示识别结果。

## 实现的文件

### 新增文件

| 文件 | 说明 |
|------|------|
| `broca-web/frontend/src/services/audioRecorder.ts` | 浏览器麦克风音频采集服务（Web Audio API） |
| `broca-web/frontend/src/services/asrClient.ts` | ASR WebSocket 客户端（连接/发送/重连/事件处理） |

### 修改文件

| 文件 | 说明 |
|------|------|
| `broca-web/frontend/src/components/ChatInput.vue` | 集成麦克风按钮、语音状态条、录音/停止逻辑、自动清理 |

## 各任务实现详情

### Task 2.1: 音频采集服务 (`audioRecorder.ts`)

- **AudioRecorder 类**：`start(onAudioFrame)` / `stop()` / `static checkPermission()`
- **采样率**：优先 16kHz AudioContext，不支持时自动用默认采样率 + 线性插值重采样
- **格式转换**：Float32Array → Int16Array（`float32To16Bit`）
- **帧大小**：ScriptProcessorNode(2048) ≈ 128ms @ 16kHz
- **单例导出**：`export const audioRecorder = new AudioRecorder()`
- **防护**：重复 `start()` 先 `stop()` 清理，`stop()` 清理所有资源（scriptNode/source/mediaStream/audioContext）

### Task 2.2: ASR WebSocket 客户端 (`asrClient.ts`)

- **AsrClient 类**：`connect(onEvent)` / `sendAudioFrame(data)` / `disconnect()` / `takeFinalText()`
- **URL 构建**：优先 `VITE_ASR_WS_URL`，否则从 `VITE_API_BASE_URL` 推导（http→ws, https→wss）
- **鉴权**：`localStorage.getItem('token')` → query param `?token=xxx`
- **自动重连**：断开后 3s 重连，最多 3 次，超限触发 error 事件
- **文本累积**：`finalText` 累积多次 final（用户连续说多句话），`partialText` 实时更新
- **静默忽略**：`sendAudioFrame` 在连接未建立或模型未就绪时不抛异常
- **单例导出**：`export const asrClient = new AsrClient()`

### Task 2.3: ChatInput 组件集成

- **麦克风按钮**：🎤（待录）/ ⏹（录音中，红色 + 脉冲动画），位于文件上传按钮和发送按钮之间
- **禁用条件**：runner 未运行 或 无麦克风权限 → 按钮置灰 + tooltip 提示
- **语音状态条**：录音中显示蓝色状态条（闪烁圆点 + 实时 partial 文本），错误时显示红色提示
- **流程**：
  1. 点击 🎤 → `asrClient.connect()` → `audioRecorder.start()` → 音频帧通过 WS 发送
  2. 说话中 → partial 文本实时显示在状态条
  3. 点击 ⏹ → 停止录音 → `takeFinalText()` 追加到输入框 → 用户可编辑
  4. 发送消息 → 复用现有 `handleSendMessage` 流程（录音中发送会先停止录音）
- **自动清理**：`onUnmounted` 时停止录音 + 断开 WS + 释放麦克风
- **权限检测**：`onMounted` 时调用 `AudioRecorder.checkPermission()` 预检

## 自查结果

| 验收标准 | 状态 | 说明 |
|----------|------|------|
| 麦克风按钮可见，位于发送按钮左侧 | ✅ | 按钮在文件上传和发送按钮之间 |
| runner 未运行时按钮置灰 | ✅ | `micDisabled` computed 包含 `!runnerAlive` |
| 点击后弹出权限请求，授权后红色/脉冲状态 | ✅ | `getUserMedia` 触发权限弹窗，`.voice-mic-btn--recording` 脉冲动画 |
| 说话时实时显示识别文字 | ⚠️ | 代码逻辑正确，需实际音频+模型验证 |
| 停止后识别文字保留在输入框，可编辑 | ✅ | `takeFinalText()` 追加到 `chatStore.input` |
| 编辑后正常发送 | ✅ | 复用 `handleSendMessage` 现有流程 |
| 无麦克风时按钮置灰 + tooltip | ✅ | `micAvailable=false` → `micDisabled=true` + `el-tooltip` |
| 组件卸载后麦克风释放 | ✅ | `onUnmounted` 调用 `stopVoiceRecording(false)` |
| WS 断开时显示错误并停止录音 | ✅ | `AsrClient` 重连超限后触发 error → `stopVoiceRecording` |
| `vue-tsc --noEmit` 通过 | ✅ | 零错误 |

## 已知限制

1. **ScriptProcessorNode 已废弃**：Web Audio API 推荐 `AudioWorklet`，但 `ScriptProcessorNode` 在所有主流浏览器仍可用且更简单
2. **模型依赖**：实际语音识别需要后端 ASR 模型文件（Phase 1 的 download 脚本），本环境网络受限无法下载
3. **未添加 `VITE_ASR_WS_URL` 到 .env 文件**：代码有 fallback 逻辑（从 `VITE_API_BASE_URL` 推导），开发环境默认用当前页面 origin
