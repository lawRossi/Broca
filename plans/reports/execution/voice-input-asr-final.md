# 语音输入 (ASR) 功能 — 完整实施报告

**计划文档**: `plans/voice-input-asr-plan.md`
**实施日期**: 2026-10-05
**状态**: ✅ 全部 3 个阶段完成

---

## 功能概述

为 Broca 的 Web 前端和 VSCode 扩展添加语音输入功能。用户点击麦克风按钮说话，后端使用 Sherpa-ONNX 流式 Zipformer 中英双语模型实时识别，识别结果实时显示并填入输入框，用户可编辑后发送。

**技术栈**: Sherpa-ONNX (ONNX Runtime) + FastAPI WebSocket + Vue 3 + VSCode Extension Host

---

## 实施总览

| 阶段 | 目标 | 状态 | 报告 |
|------|------|------|------|
| Phase 1 | 后端 ASR 服务 | ✅ | `voice-input-asr-phase-1.md` |
| Phase 2 | Web 前端语音输入 | ✅ | `voice-input-asr-phase-2.md` |
| Phase 3 | VSCode 扩展语音输入 | ✅ | `voice-input-asr-phase-3.md` |

---

## 文件清单

### 新增文件 (7)

| 文件 | 阶段 | 说明 |
|------|------|------|
| `broca-web/backend/app/asr/__init__.py` | P1 | ASR 模块包初始化 |
| `broca-web/backend/app/asr/config.py` | P1 | ASRConfig 数据类 + get_asr_config() |
| `broca-web/backend/app/asr/service.py` | P1 | ASRService 单例（懒加载、流式解码、会话管理） |
| `broca-web/backend/app/api/asr.py` | P1 | WebSocket `/api/asr/stream` 端点 |
| `broca-web/backend/scripts/download_asr_model.py` | P1 | 模型下载脚本（GitHub/HuggingFace） |
| `broca-web/frontend/src/services/audioRecorder.ts` | P2 | 浏览器麦克风音频采集（Web Audio API） |
| `broca-web/frontend/src/services/asrClient.ts` | P2 | ASR WebSocket 客户端（自动重连） |
| `broca-vscode/src/extension/audioCapture.ts` | P3 | 系统音频采集（sox/ffmpeg/arecord） |
| `broca-vscode/src/extension/asrClient.ts` | P3 | Node.js WebSocket ASR 客户端 |

### 修改文件 (7)

| 文件 | 阶段 | 变更 |
|------|------|------|
| `broca-web/backend/pyproject.toml` | P1 | + sherpa-onnx, onnxruntime 依赖 |
| `broca-web/backend/app/main.py` | P1 | 认证改为 router-level，ASR router 独立注册 |
| `broca-web/backend/start.sh` | P1 | macOS dylib symlink 修复 + 模型预下载 |
| `broca-web/frontend/src/components/ChatInput.vue` | P2 | 麦克风按钮 + 语音状态条 + 录音集成 |
| `broca-vscode/src/extension/types.ts` | P3 | + voice/ASR 消息类型 |
| `broca-vscode/src/extension/chatWebView.ts` | P3 | + voice input handlers + dispose 清理 |
| `broca-vscode/package.json` | P3 | + ws, @types/ws 依赖 |
| `broca-vscode/src/webview/src/components/ChatInput.vue` | P3 | 麦克风按钮 + 语音状态条 + postMessage 集成 |

---

## 架构

```
┌─────────────────────────────────────────────────────────────────────┐
│  Web 前端 (Vue 3)              VSCode 扩展                          │
│                                                                     │
│  ChatInput.vue                ChatInput.vue (webview)               │
│    ├── audioRecorder.ts        │                                     │
│    │   (getUserMedia)          │  postMessage                       │
│    └── asrClient.ts            ▼                                     │
│        (browser WS)         Extension Host                          │
│              │                   ├── audioCapture.ts                 │
│              │                   │   (sox/ffmpeg/arecord)            │
│              │                   └── asrClient.ts                    │
│              │                       (Node.js ws)                    │
│              │                         │                             │
│              ▼                         ▼                             │
│  ┌──────────────────────────────────────────┐                       │
│  │  FastAPI WebSocket /api/asr/stream       │                       │
│  │  ┌────────────────────────────────────┐  │                       │
│  │  │  ASRService (singleton)            │  │                       │
│  │  │  ├── sherpa-onnx OnlineRecognizer  │  │                       │
│  │  │  ├── lazy loading (first connect)  │  │                       │
│  │  │  ├── per-connection OnlineStream   │  │                       │
│  │  │  └── endpoint detection + reset    │  │                       │
│  │  └────────────────────────────────────┘  │                       │
│  └──────────────────────────────────────────┘                       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 关键设计决策

1. **认证隔离**: FastAPI 的 `HTTPBearer` 与 WebSocket 路由不兼容。将 `verify_token` 从 app-level 移至 router-level（`include_router(..., dependencies=[...])`），ASR router 独立注册并通过 query param 认证
2. **懒加载**: ASR 模型不随服务启动加载，首次 WebSocket 连接时加载（1-5s），之后复用
3. **VSCode 音频采集**: Webview CSP 禁止 `getUserMedia`，在 Extension Host 通过 `child_process.spawn` 调用系统工具
4. **文本累积**: 多次 `final` 消息的文本拼接（用户连续说多句话），`takeFinalText()` 获取并清空
5. **自动重连** (Web): WebSocket 断开后 3s 重连，最多 3 次。VSCode 版无自动重连（Extension Host 控制生命周期）

---

## 验证结果

| 检查项 | Phase 1 | Phase 2 | Phase 3 |
|--------|---------|---------|---------|
| TypeScript/Python 编译 | ✅ | ✅ vue-tsc | ✅ tsc + vite |
| WebSocket 端点可达 | ✅ | — | — |
| 并发连接 | ✅ (2 连接) | — | — |
| 认证 (loopback + token) | ✅ | — | — |
| 健康检查不受影响 | ✅ | — | — |
| 音频采集逻辑 | — | ✅ (代码) | ✅ (代码) |
| 组件集成 | — | ✅ | ✅ |
| 资源清理 | ✅ | ✅ | ✅ |
| 实际语音识别 | ⚠️ 需模型 | ⚠️ 需模型 | ⚠️ 需模型 |

---

## 使用前准备

1. **下载 ASR 模型**（首次）:
   ```bash
   python broca-web/backend/scripts/download_asr_model.py
   # 或设置 BROCA_ASR_MODEL 环境变量指定自定义模型
   ```

2. **VSCode 扩展需要系统音频工具**:
   ```bash
   # macOS
   brew install sox
   # Ubuntu
   sudo apt install sox   # 或 alsa-utils (arecord)
   # Windows
   # 安装 ffmpeg: https://ffmpeg.org/download.html
   ```

3. **Web 前端可选配置**:
   ```bash
   # .env.development / .env.production
   VITE_ASR_WS_URL=ws://localhost:9000  # 可选，默认从 VITE_API_BASE_URL 推导
   ```

---

## 已知限制

1. **模型下载**: 本环境网络受限（GitHub SSL / HuggingFace 401），模型文件需在有网络的环境下载
2. **ScriptProcessorNode 已废弃**: Web 前端使用 `ScriptProcessorNode`（所有主流浏览器仍支持），未来可迁移到 `AudioWorklet`
3. **单一 ASR 模型**: 当前仅支持 Zipformer transducer 模型，未实现多模型切换
4. **空闲超时未实现**: ASR 模型加载后不会自动卸载（计划中的 5 分钟空闲超时未实现）
