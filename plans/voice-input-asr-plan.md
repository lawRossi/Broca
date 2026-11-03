# 语音输入功能 — 实施计划

## 概述

- **目标**：为 Broca 的 Web 前端和 VSCode 扩展的输入模块增加语音输入能力，用户可通过麦克风语音输入替代键盘打字，ASR 在服务端完成，前端实时展示部分识别结果。
- **背景**：Broca 是一个 AI Agent 平台，支持 Web（Vue 3 + Element Plus）和 VSCode 扩展（Vue 3 webview）两种前端。当前所有用户输入均为键盘打字，项目中不存在任何语音/音频采集和 ASR 基础设施。
- **约束条件**：
  - ASR 服务部署在服务端（FastAPI 后端），不在前端运行模型
  - 采用懒加载 — ASR 模型仅在首次语音输入请求时加载到内存
  - 实时识别 — 流式传输音频，服务端实时返回部分/最终识别结果
  - 前端实时展示 — 用户说话时，输入框实时显示正在识别的文字
  - 使用轻量级模型（CPU 可运行，模型体积 < 100MB 优先）
  - 支持 Web 前端 + VSCode 扩展两端

## 相关材料

- **Sherpa-ONNX 项目**：https://github.com/k2-fsa/sherpa-onnx — 基于 ONNX Runtime 的轻量级语音识别推理引擎，支持流式/非流式 ASR，纯 CPU 即可实时推理
- **Sherpa-ONNX Python API 文档**：https://k2-fsa.github.io/sherpa/onnx/python/index.html
- **Sherpa-ONNX 预训练模型列表**：https://k2-fsa.github.io/sherpa/onnx/pretrained_models/index.html
- **Sherpa-ONNX 流式 WebSocket Server 示例**：https://k2-fsa.github.io/sherpa/onnx/python/streaming-websocket-server.html
- **参考实现 — 流式 WebSocket Server**：`python-api-examples/online-websocket-server/` (GitHub)
- **现有 Web 前端输入组件**：`broca-web/frontend/src/components/ChatInput.vue`
- **现有 VSCode 输入组件**：`broca-vscode/src/webview/src/components/ChatInput.vue`
- **FastAPI 后端入口**：`broca-web/backend/app/main.py`
- **API 路由注册**：`broca-web/backend/app/api/__init__.py`
- **Socket.IO 服务运行时**：`broca-web/backend/app/core/socketio_runtime.py`
- **Service Manager（进程管理参考）**：`broca/service_manager.py`
- **Web 前端 Socket 客户端**：`broca-web/frontend/src/api/brocaSocket.ts`
- **Web 前端聊天 Store**：`broca-web/frontend/src/stores/chat.ts`
- **VSCode Extension Host 消息处理**：`broca-vscode/src/extension/chatWebView.ts`
- **VSCode Extension Socket 客户端**：`broca-vscode/src/extension/socket.ts`
- **VSCode Webview 类型定义**：`broca-vscode/src/webview/src/types.ts`
- **VSCode Webview 聊天 Store**：`broca-vscode/src/webview/src/stores/chat.ts`
- **后端依赖配置**：`broca-web/backend/pyproject.toml`
- **VSCode 扩展依赖配置**：`broca-vscode/package.json`

## 总体方案

### 技术选型

| 层面 | 选择 | 理由 |
|------|------|------|
| **ASR 引擎** | **Sherpa-ONNX** (ONNX Runtime) | 轻量级、纯 CPU、原生支持流式推理、Python API 完善、社区活跃（15k+ Star） |
| **ASR 模型** | `sherpa-onnx-streaming-zipformer-small-bilingual-zh-en-2023-02-16` | 中英双语、流式模型、参数量小（~20M）、int8 量化后总大小 ~50MB |
| **通信协议** | **WebSocket**（FastAPI 原生支持） | 双向实时通信，天然适合音频流传输；与现有 REST API 同端口（:9000），无需额外端口 |
| **音频格式** | 16kHz / 16-bit / Mono PCM | ASR 模型标准输入格式 |
| **前端音频采集 (Web)** | `navigator.mediaDevices.getUserMedia` + `AudioContext` + `ScriptProcessorNode` | 浏览器原生 API，无需额外依赖 |
| **前端音频采集 (VSCode)** | Extension Host 端系统音频采集（`sox`/`ffmpeg`） + WebSocket | VSCode webview CSP 可能限制 `getUserMedia`，使用 extension host 更可靠 |
| **懒加载** | 首次 WebSocket 连接时初始化 `OnlineRecognizer` | 模型加载耗时 ~1-3s，仅在用户首次使用语音输入时触发 |

### 架构设计

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              客户端                                           │
│                                                                             │
│  ┌──────────────────────────┐    ┌───────────────────────────────────┐      │
│  │  Web 前端 (Vue 3)        │    │  VSCode 扩展                       │      │
│  │  ┌────────────────────┐  │    │  ┌────────────────────────────┐   │      │
│  │  │ ChatInput.vue      │  │    │  │ Webview (Vue 3)            │   │      │
│  │  │  - textarea        │  │    │  │  ChatInput.vue             │   │      │
│  │  │  - mic button      │  │    │  │  - textarea                │   │      │
│  │  │  - partial text    │  │    │  │  - mic button              │   │      │
│  │  └────────────────────┘  │    │  │  - partial text            │   │      │
│  │  ┌────────────────────┐  │    │  └────────────────────────────┘   │      │
│  │  │ AudioRecorder      │  │    │  ┌────────────────────────────┐   │      │
│  │  │ getUserMedia +     │  │    │  │ Extension Host (Node.js)   │   │      │
│  │  │ AudioContext       │  │    │  │ AudioCapture (sox/ffmpeg)  │   │      │
│  │  └────────────────────┘  │    │  │ + WebSocket Client         │   │      │
│  │  ┌────────────────────┐  │    │  └────────────────────────────┘   │      │
│  │  │ AsrWebSocketClient │  │    │                                    │      │
│  │  └────────────────────┘  │    │                                    │      │
│  └──────────┬───────────────┘    └──────────────┬─────────────────────┘      │
│             │ WebSocket (binary PCM + JSON)      │ WebSocket (binary PCM)     │
└─────────────┼─────────────────────────────────────┼───────────────────────────┘
              │                                     │
              ▼                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        FastAPI 后端 (:9000)                                  │
│                                                                             │
│  ┌─────────────────────┐  ┌─────────────────────────────────────────────┐   │
│  │  REST API           │  │  WebSocket ASR 端点                          │   │
│  │  /api/session/...   │  │  WS /api/asr/stream                         │   │
│  │  /api/auth/...      │  │                                             │   │
│  └─────────────────────┘  │  ┌───────────────────────────────────────┐  │   │
│                            │  │  ASRService (单例, 懒加载)             │  │   │
│  ┌─────────────────────┐  │  │  ┌─────────────────────────────────┐  │  │   │
│  │  Socket.IO Server   │  │  │  │  Sherpa-ONNX OnlineRecognizer  │  │  │   │
│  │  (:6868)            │  │  │  │  (Zipformer 中英双语流式模型)      │  │  │   │
│  │  消息路由            │  │  │  └─────────────────────────────────┘  │  │   │
│  │  (用户消息→Runner)   │  │  │                                       │  │   │
│  └─────────────────────┘  │  └───────────────────────────────────────┘  │   │
│                            └─────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────┘
```

**核心流程**：
1. 用户点击麦克风按钮 → 前端开始录音
2. 音频帧（16kHz PCM）通过 WebSocket 发送到后端
3. 后端 ASR 服务流式解码，实时返回部分识别结果（JSON）
4. 前端将部分识别结果实时显示在输入框中
5. 用户停止录音 → 后端返回最终识别结果
6. 用户可编辑识别文本，确认后通过现有 Socket.IO 消息流程发送

**关键设计决策**：
- ASR 识别结果**仅填充到输入框**，不直接发送消息 — 用户保留编辑权和确认权
- WebSocket 端点集成在现有 FastAPI 应用中（同端口 :9000），无需部署独立服务
- 懒加载：`ASRService` 为单例，`OnlineRecognizer` 在首次 WebSocket 连接时初始化
- 模型文件预置于 `~/.broca/models/asr/`，安装时下载，运行时仅做内存加载

### WebSocket 协议设计

```
Client → Server:
  Binary frame: 原始 PCM 音频数据 (16kHz, 16-bit, mono, little-endian)
  JSON frame:   {"type": "config", "sample_rate": 16000}  (可选，连接后首帧)
  连接关闭:     表示停止录音

Server → Client:
  {"type": "status", "state": "loading"}     — 模型加载中
  {"type": "status", "state": "ready"}       — 模型加载完成，可以接收音频
  {"type": "partial", "text": "你好世界"}     — 部分识别结果（持续更新）
  {"type": "final", "text": "你好世界"}       — 最终识别结果（endpoint 触发时）
  {"type": "error", "message": "..."}        — 错误信息
```

## 执行计划

### Phase 1: 后端 ASR 服务

**目标**：在 FastAPI 后端实现完整的 ASR WebSocket 服务，包含 Sherpa-ONNX 引擎集成、流式识别、懒加载机制。

**阶段验收标准**：
- [ ] 使用 `python websockets` 或 `wscat` 连接 `ws://localhost:9000/api/asr/stream`，发送 16kHz PCM 音频，能收到 JSON 格式的部分/最终识别结果
- [ ] 首次连接时触发模型加载，控制台输出加载日志；后续连接不再重复加载
- [ ] 发送一段中文语音（如"你好，请帮我查一下天气"），识别结果准确率达到可用水平
- [ ] 发送一段英文语音，识别结果准确
- [ ] 断开 WebSocket 连接后，对应的 stream 资源被正确清理
- [ ] 后端启动时间不因 ASR 模块增加而显著增长（< 1s 额外耗时）

#### Task 1.1: 添加 Sherpa-ONNX 依赖与模型管理

- **目标**：在 FastAPI 后端添加 `sherpa-onnx` Python 依赖，创建模型下载脚本和模型目录约定
- **步骤**：
  1. 在 `broca-web/backend/pyproject.toml` 的 `[tool.poetry.dependencies]` 中添加 `sherpa-onnx >= 1.10`（确认与 Python 版本兼容，当前使用 Python 3.12+）
  2. 创建 `broca-web/backend/app/asr/` 目录，包含 `__init__.py`
  3. 创建 `broca-web/backend/app/asr/config.py`：
     - 定义 `ASRConfig` 数据类，包含 `model_dir`（默认 `~/.broca/models/asr/`）、`model_name`（默认 `sherpa-onnx-streaming-zipformer-small-bilingual-zh-en-2023-02-16`）、`num_threads`（默认 `os.cpu_count()`）、`provider`（默认 `"cpu"`）、`sample_rate`（固定 `16000`）
     - 提供 `get_asr_config()` 函数，支持通过环境变量 `BROCA_ASR_MODEL` 覆盖默认模型
  4. 创建 `broca-web/backend/scripts/download_asr_model.py` 脚本：
     - 从 HuggingFace 或 sherpa-onnx 官方 URL 下载指定模型的 `.onnx` 文件和 `tokens.txt`
     - 下载到 `~/.broca/models/asr/{model_name}/` 目录
     - 支持 `--model` 参数指定模型名，默认使用 `ASRConfig` 中的默认模型
     - 下载前检查文件是否已存在（跳过重复下载）
     - 打印下载进度和文件校验
  5. 在 `broca-web/backend/start.sh` 中添加模型预下载步骤（非阻塞，首次运行时后台下载）
- **预期产出**：
  - 更新后的 `pyproject.toml`
  - `broca-web/backend/app/asr/__init__.py`
  - `broca-web/backend/app/asr/config.py`
  - `broca-web/backend/scripts/download_asr_model.py`
  - 更新后的 `start.sh`
- **验收标准**：
  - [ ] `poetry install` 成功后 `python -c "import sherpa_onnx; print(sherpa_onnx.__version__)"` 正常输出版本号
  - [ ] 运行 `python scripts/download_asr_model.py` 后，`~/.broca/models/asr/sherpa-onnx-streaming-zipformer-small-bilingual-zh-en-2023-02-16/` 目录下包含 `encoder-*.onnx`、`decoder-*.onnx`、`joiner-*.onnx`、`tokens.txt` 文件
  - [ ] 重复运行下载脚本不会重复下载（检测已存在文件并跳过）
  - [ ] 设置 `BROCA_ASR_MODEL` 环境变量后 `get_asr_config()` 返回对应的模型路径

#### Task 1.2: 实现 ASR 服务核心（懒加载 + 流式识别）

- **目标**：实现 `ASRService` 单例类，封装 Sherpa-ONNX `OnlineRecognizer` 的懒加载、流式解码、会话管理
- **步骤**：
  1. 创建 `broca-web/backend/app/asr/service.py`：
  2. 定义 `ASRService` 类（进程级单例）：
     ```python
     class ASRService:
         _instance: Optional["ASRService"] = None
         _lock: asyncio.Lock
         _recognizer: Optional[sherpa_onnx.OnlineRecognizer]
         _loading: bool
         _sessions: Dict[str, OnlineStream]  # session_id → stream
         _idle_timer: Optional[asyncio.Task]

         @classmethod
         def get_instance(cls) -> "ASRService": ...
         
         async def ensure_loaded(self) -> None:
             """懒加载：首次调用时初始化 OnlineRecognizer"""
             # 1. 如果 _recognizer 已存在，直接返回
             # 2. 获取 _lock（防止并发加载）
             # 3. 从 ASRConfig 获取模型路径
             # 4. 构建 sherpa_onnx.OnlineModelConfig (transducer: encoder/decoder/joiner + tokens)
             # 5. 构建 sherpa_onnx.OnlineRecognizerConfig (feat_config: sample_rate=16000)
             # 6. 调用 sherpa_onnx.OnlineRecognizer.from_file(config)
             # 7. 记录加载耗时日志
         
         def create_session(self) -> OnlineStream:
             """为每个 WebSocket 连接创建独立的 OnlineStream"""
             self._recognizer.create_stream()
         
         def process_audio(self, stream: OnlineStream, samples: List[float]) -> str:
             """处理一批音频采样，返回当前部分识别文本
             - stream.accept_waveform(samples)
             - while recognizer.is_ready(stream): recognizer.decode_stream(stream)
             - 如果 endpoint 触发（stream.is_endpoint()）：重置 stream，返回 final 文本
             - 否则返回 recognizer.get_result(stream).text 作为 partial
         
         def finish_session(self, session_id: str) -> str:
             """结束会话：stream.input_finished() → 解码剩余 → 返回 final 文本 → 清理 stream"""
         
         def is_loaded(self) -> bool: ...
     ```
  3. 实现 endpoint 处理逻辑：
     - 当 `stream.is_endpoint()` 返回 True 时，表示检测到语音结束
     - 自动调用 `stream.reset()` 重新启用，支持连续说话场景
     - 向客户端发送 `{"type": "final", "text": "..."}` 后，继续监听下一段语音
  4. 可选：实现空闲超时（默认 5 分钟无音频数据后卸载模型释放内存），使用 `asyncio.create_task` 定时检查
- **预期产出**：`broca-web/backend/app/asr/service.py` — 完整的 ASR 服务实现
- **验收标准**：
  - [ ] `ASRService.get_instance()` 返回同一单例
  - [ ] 首次调用 `ensure_loaded()` 耗时 1-5s（模型加载），后续调用 < 1ms
  - [ ] `create_session()` + `process_audio(stream, samples)` + `finish_session()` 完整流程可用
  - [ ] 并发创建 5 个 session 互不干扰（各自独立的 OnlineStream）
  - [ ] endpoint 触发后 stream 自动 reset，可继续接收下一段语音
  - [ ] 模型未加载时调用 `process_audio` 抛出明确异常或返回空字符串

#### Task 1.3: 实现 WebSocket ASR 端点

- **目标**：在 FastAPI 应用上添加 WebSocket 端点，接收音频流并返回识别结果
- **步骤**：
  1. 创建 `broca-web/backend/app/api/asr.py`：
  2. 定义 WebSocket 路由 `@router.websocket("/asr/stream")`（最终路径为 `/api/asr/stream`）：
     ```python
     @router.websocket("/asr/stream")
     async def asr_stream_endpoint(websocket: WebSocket, user = Depends(verify_token)):
         await websocket.accept()
         asr = ASRService.get_instance()
         
         # 发送 loading 状态
         await websocket.send_json({"type": "status", "state": "loading"})
         
         # 懒加载模型
         await asr.ensure_loaded()
         await websocket.send_json({"type": "status", "state": "ready"})
         
         # 创建会话
         stream = asr.create_session()
         
         try:
             while True:
                 # 接收音频数据（binary frame）
                 data = await websocket.receive_bytes()
                 
                 # 解码 PCM (16-bit signed, little-endian) → float32 [-1.0, 1.0]
                 samples = _pcm_to_float32(data)
                 
                 # 处理音频
                 text, is_final = asr.process_audio(stream, samples)
                 
                 if text:
                     msg_type = "final" if is_final else "partial"
                     await websocket.send_json({"type": msg_type, "text": text})
         except WebSocketDisconnect:
             pass
         finally:
             # 清理会话
             asr.finish_session(stream)
     ```
  3. 实现 `_pcm_to_float32(data: bytes) -> List[float]` 辅助函数：
     - 将 `bytes` (16-bit signed PCM) 转换为 `List[float]` 范围 `[-1.0, 1.0]`
     - 使用 `struct.unpack` 或 `numpy.frombuffer`
  4. 在 `broca-web/backend/app/api/__init__.py` 中注册 ASR 路由
  5. 处理边界情况：
     - 客户端发送非 binary 消息（JSON 控制消息）→ 忽略或按类型处理
     - 客户端发送的音频采样率不是 16kHz → 返回错误
     - 模型加载失败 → 发送 `{"type": "error", "message": "..."}` 并关闭连接
     - 并发多个 WebSocket 连接 → 每个连接独立的 OnlineStream
  6. 鉴权：复用现有 `verify_token` 依赖（JWT Bearer），WebSocket 连接时通过 query param 或 header 传递 token
- **预期产出**：
  - `broca-web/backend/app/api/asr.py`
  - 更新后的 `broca-web/backend/app/api/__init__.py`
- **验收标准**：
  - [ ] 使用 `wscat -c ws://localhost:9000/api/asr/stream?token=xxx` 连接后收到 `{"type":"status","state":"ready"}`
  - [ ] 发送一段 16kHz PCM 中文语音音频数据，能收到多个 `partial` 消息和一个 `final` 消息
  - [ ] 发送英文音频数据，能正确识别
  - [ ] 未携带有效 token 时连接被拒绝（返回 403 或连接关闭）
  - [ ] 同时建立 2 个 WebSocket 连接，各自独立识别互不干扰
  - [ ] 客户端断开后，服务端日志输出会话清理信息，无内存泄漏
  - [ ] 后端启动后 `GET /api/health` 仍正常（ASR 模块不影响启动）

### Phase 2: Web 前端语音输入

**目标**：在 Broca Web 前端（Vue 3）的 ChatInput 组件中集成语音输入功能，用户可点击麦克风按钮进行语音输入，输入框实时显示识别结果。

**阶段验收标准**：
- [ ] ChatInput 组件中新增麦克风按钮，点击后弹出麦克风权限请求（首次）
- [ ] 授权后开始录音，按钮变为"停止"状态（视觉反馈：红色/脉冲动画）
- [ ] 说话时输入框实时显示部分识别文字（约 200-500ms 延迟）
- [ ] 点击停止按钮后，最终识别结果保留在输入框中，用户可编辑
- [ ] 用户可编辑识别文本后正常发送消息（复用现有发送流程）
- [ ] 无麦克风权限或无麦克风设备时，按钮置灰并显示 tooltip 提示
- [ ] 录音过程中如果 ASR 服务不可用（WebSocket 断开），显示错误提示并自动停止录音
- [ ] 页面切换/组件卸载时自动停止录音并释放麦克风

#### Task 2.1: 创建音频采集服务

- **目标**：封装浏览器麦克风音频采集逻辑，提供简洁的 API 供组件使用
- **步骤**：
  1. 创建 `broca-web/frontend/src/services/audioRecorder.ts`：
  2. 定义 `AudioRecorder` 类：
     ```typescript
     class AudioRecorder {
       private audioContext: AudioContext | null = null;
       private mediaStream: MediaStream | null = null;
       private scriptNode: ScriptProcessorNode | null = null;
       private source: MediaStreamAudioSourceNode | null = null;
       private _isRecording = false;

       get isRecording(): boolean;

       /** 请求麦克风权限并初始化 AudioContext */
       async start(onAudioFrame: (data: ArrayBuffer) => void): Promise<void> {
         // 1. navigator.mediaDevices.getUserMedia({ audio: { sampleRate: 16000, channelCount: 1 } })
         // 2. 创建 AudioContext({ sampleRate: 16000 })
         //    如果浏览器不支持 16kHz AudioContext，使用默认采样率 + 重采样
         // 3. 创建 MediaStreamAudioSourceNode
         // 4. 创建 ScriptProcessorNode(bufferSize=2048, inCh=1, outCh=1)
         // 5. 连接: source → scriptNode → destination
         // 6. scriptNode.onaudioprocess: 获取 Float32Array → 转 Int16Array → 回调
         // 7. 设置 _isRecording = true
       }

       /** 停止录音，清理所有资源 */
       stop(): void {
         // 1. _isRecording = false
         // 2. scriptNode.disconnect(); source.disconnect()
         // 3. mediaStream.getTracks().forEach(t => t.stop())
         // 4. audioContext.close()
         // 5. 清空引用
       }

       /** 检查麦克风权限和设备可用性 */
       static async checkPermission(): Promise<boolean> { ... }
     }
     export const audioRecorder = new AudioRecorder(); // 单例
     ```
  3. 实现 Float32 → Int16 转换辅助函数：
     ```typescript
     function float32To16Bit(float32: Float32Array): Int16Array {
       const int16 = new Int16Array(float32.length);
       for (let i = 0; i < float32.length; i++) {
         const s = Math.max(-1, Math.min(1, float32[i]));
         int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
       }
       return int16;
     }
     ```
  4. 处理重采样：如果 `AudioContext.sampleRate !== 16000`，使用线性插值或 `AudioContext` 重采样到 16kHz
- **预期产出**：`broca-web/frontend/src/services/audioRecorder.ts`
- **验收标准**：
  - [ ] 调用 `start(callback)` 后，callback 每 ~128ms（2048/16000s）被调用一次，传入 `ArrayBuffer`（Int16 PCM 数据）
  - [ ] 浏览器控制台无 CORS 或权限错误
  - [ ] 调用 `stop()` 后，`navigator.mediaDevices.getUserMedia` 的 track 被停止（可通过 `mediaStream.active` 验证为 false）
  - [ ] 无麦克风权限时 `start()` 抛出 `NotAllowedError`，可被捕获
  - [ ] 重复调用 `start()` 不会创建多个 AudioContext（先 stop 再 start）

#### Task 2.2: 创建 ASR WebSocket 客户端

- **目标**：封装与后端 ASR WebSocket 端点的通信逻辑
- **步骤**：
  1. 创建 `broca-web/frontend/src/services/asrClient.ts`：
  2. 定义 `AsrClient` 类：
     ```typescript
     type AsrEvent =
       | { type: 'status'; state: 'loading' | 'ready' }
       | { type: 'partial'; text: string }
       | { type: 'final'; text: string }
       | { type: 'error'; message: string };

     class AsrClient {
       private ws: WebSocket | null = null;
       private _isConnected = false;
       private _isReady = false;  // 模型加载完成
       private _partialText = '';
       private _finalText = '';

       get isConnected(): boolean;
       get isReady(): boolean;
       get partialText(): string;
       get finalText(): string;

       /** 连接到 ASR 服务 */
       async connect(onEvent: (e: AsrEvent) => void): Promise<void> {
         // 1. 构建 URL: `${wsBase}/api/asr/stream?token=${jwt}`
         //    wsBase 从 VITE_BROCA_SOCKET_SERVER_URL 推导或新增 VITE_ASR_WS_URL
         //    如果 API 和 WS 同端口，使用 window.location.protocol 推导
         // 2. 创建 WebSocket 连接
         // 3. onopen: 设置 _isConnected = true
         // 4. onmessage: 解析 JSON → 分类处理:
         //    - status:loading → 设置 _isReady = false
         //    - status:ready → 设置 _isReady = true
         //    - partial → _partialText = e.text
         //    - final → _finalText += e.text (累积)
         //    - error → 触发 onEvent error
         //    每次变化都调用 onEvent
         // 5. onclose: 设置 _isConnected = false, _isReady = false
         // 6. onerror: 触发 onEvent error
       }

       /** 发送音频帧 (ArrayBuffer, 16-bit PCM) */
       sendAudioFrame(data: ArrayBuffer): void {
         if (this.ws?.readyState === WebSocket.OPEN && this._isReady) {
           this.ws.send(data);
         }
       }

       /** 断开连接并清理 */
       disconnect(): void {
         this.ws?.close();
         this.ws = null;
         this._isConnected = false;
         this._isReady = false;
         this._partialText = '';
         this._finalText = '';
       }
     }
     export const asrClient = new AsrClient(); // 单例
     ```
  3. 处理自动重连：WebSocket 断开后 3 秒内自动重连（最多 3 次），超出后触发 error 事件
  4. 处理 final 文本累积：多次 `final` 消息的文本应拼接（用户可能连续说多句话）
- **预期产出**：`broca-web/frontend/src/services/asrClient.ts`
- **验收标准**：
  - [ ] `connect(callback)` 后，后端模型加载完成时 callback 收到 `{type:'status', state:'ready'}`
  - [ ] `sendAudioFrame(data)` 在连接未建立或模型未就绪时静默忽略（不抛异常）
  - [ ] 后端返回 partial 时，`partialText` 实时更新
  - [ ] 后端返回 final 时，`finalText` 正确累积
  - [ ] `disconnect()` 后 WebSocket 连接关闭，`isConnected` 为 false
  - [ ] 网络断开后 3 秒内自动重连成功

#### Task 2.3: ChatInput 组件集成语音输入

- **目标**：在 Web 前端的 `ChatInput.vue` 中添加麦克风按钮和实时识别文字展示
- **步骤**：
  1. 修改 `broca-web/frontend/src/components/ChatInput.vue`：
  2. 模板部分 — 在发送按钮旁添加麦克风按钮：
     ```html
     <!-- 麦克风按钮 -->
     <button
       class="voice-btn"
       :class="{ 'voice-btn--active': isRecording }"
       :disabled="!canStartRecording"
       @click="toggleVoiceInput"
       :title="isRecording ? '停止录音' : '语音输入'"
     >
       <el-icon v-if="!isRecording"><Microphone /></el-icon>
       <el-icon v-else><VideoPause /></el-icon>
     </button>
     ```
     - `Microphone` 和 `VideoPause` 图标从 `@element-plus/icons-vue` 导入
  3. 在 textarea 下方添加实时识别提示区域：
     ```html
     <!-- 录音状态提示 -->
     <div v-if="isRecording" class="voice-status">
       <span class="voice-status__dot" />
       <span class="voice-status__text">正在聆听...</span>
     </div>
     ```
  4. 脚本部分 — 添加语音输入逻辑：
     ```typescript
     const isRecording = ref(false);
     const canStartRecording = computed(() => chatStore.runnerAlive && !isUploading);

     async function toggleVoiceInput() {
       if (isRecording.value) {
         stopVoiceInput();
       } else {
         await startVoiceInput();
       }
     }

     async function startVoiceInput() {
       // 1. 连接 ASR WebSocket
       await asrClient.connect(handleAsrEvent);
       
       // 2. 保存当前输入框内容（用户可能已输入了部分文字）
       const previousText = chatStore.input;
       
       // 3. 开始录音
       await audioRecorder.start((audioData) => {
         asrClient.sendAudioFrame(audioData);
       });
       isRecording.value = true;
     }

     function stopVoiceInput() {
       audioRecorder.stop();
       asrClient.disconnect();
       isRecording.value = false;
       
       // 将识别结果追加到输入框
       const finalText = asrClient.finalText;
       if (finalText) {
         const prev = chatStore.input;
         chatStore.input = prev ? prev + ' ' + finalText : finalText;
       }
     }

     function handleAsrEvent(event: AsrEvent) {
       if (event.type === 'partial') {
         // 实时显示部分识别结果
         // 策略：在输入框中用不同样式显示 partial text
         // 简单方案：直接更新 input，partial 时加标记
         chatStore.input = asrClient.partialText;
       } else if (event.type === 'final') {
         // final 文本由 stopVoiceInput 处理
       } else if (event.type === 'error') {
         stopVoiceInput();
         ElMessage.error(`语音识别错误: ${event.message}`);
       }
     }

     // 组件卸载时清理
     onUnmounted(() => {
       if (isRecording.value) stopVoiceInput();
     });
     ```
  5. 样式部分：
     - `.voice-btn`：圆形按钮，与发送按钮风格一致
     - `.voice-btn--active`：红色背景 + 脉冲动画（`@keyframes pulse`）
     - `.voice-status`：小字体灰色提示，带闪烁圆点
     - 录音时 textarea 的 placeholder 变为 "正在聆听，请说话..."
  6. 处理边界情况：
     - 录音中用户手动点击发送 → 先停止录音，再发送
     - 录音中切换 agent → 停止录音
     - WebSocket 连接中模型还在 loading → 按钮显示 loading 状态
- **预期产出**：更新后的 `broca-web/frontend/src/components/ChatInput.vue`
- **验收标准**：
  - [ ] ChatInput 组件渲染时，麦克风按钮可见且位于发送按钮左侧
  - [ ] runner 未运行时麦克风按钮置灰
  - [ ] 点击麦克风按钮后，浏览器弹出权限请求（首次），授权后按钮变为红色/脉冲状态
  - [ ] 说话时输入框实时显示识别文字（延迟 < 500ms）
  - [ ] 点击停止后，识别文字保留在输入框中，可编辑
  - [ ] 编辑后按 Enter 或点击发送，消息通过现有流程正常发送
  - [ ] 无麦克风时按钮置灰，hover 显示 "未检测到麦克风设备"
  - [ ] 组件卸载（如切换页面）后麦克风被释放（DevTools 中 MediaStreams 为空）

### Phase 3: VSCode 扩展语音输入

**目标**：在 VSCode 扩展中集成语音输入功能。由于 VSCode webview 的 CSP 限制，音频采集在 Extension Host（Node.js）端完成，识别结果通过 postMessage 传递到 webview 显示。

**阶段验收标准**：
- [ ] VSCode 扩展的 ChatInput 中新增麦克风按钮
- [ ] 点击麦克风按钮后，Extension Host 启动系统音频采集
- [ ] 说话时 webview 输入框实时显示部分识别文字
- [ ] 停止录音后，识别结果保留在输入框中
- [ ] 用户可编辑后正常发送消息
- [ ] 系统未安装音频采集工具（sox/ffmpeg）时，按钮置灰并提示

#### Task 3.1: Extension Host 音频采集与 ASR 流式传输

- **目标**：在 VSCode Extension Host 中实现麦克风音频采集和 ASR WebSocket 流式传输
- **步骤**：
  1. 创建 `broca-vscode/src/extension/audioCapture.ts`：
     ```typescript
     import { spawn } from 'child_process';
     import WebSocket from 'ws';  // 新增 Node.js 依赖

     interface AudioCaptureOptions {
       sampleRate?: number;  // 默认 16000
       onAudioFrame: (data: Buffer) => void;
       onError: (error: string) => void;
     }

     class AudioCapture {
       private process: ChildProcess | null = null;
       private _isCapturing = false;

       get isCapturing(): boolean;

       /** 检测系统音频采集工具可用性 */
       static async isSupported(): Promise<boolean> {
         // 检测 sox / ffmpeg / arecord 是否可用
         // macOS: sox 或 ffmpeg
         // Linux: arecord 或 sox
         // Windows: ffmpeg
       }

       /** 启动系统音频采集 */
       async start(options: AudioCaptureOptions): Promise<void> {
         // 1. 检测平台并选择合适的命令:
         //    macOS/Linux: sox -d -r 16000 -c 1 -b 16 -t raw -
         //    Linux fallback: arecord -r 16000 -f S16_LE -c 1 -t raw -
         //    Windows: ffmpeg -f dshow -i audio="Default-Audio Device" -ar 16000 -ac 1 -f s16le -
         // 2. spawn 命令，pipe stdout
         // 3. stdout.on('data') → options.onAudioFrame(data)
         // 4. stderr → 日志/错误处理
         // 5. 设置 _isCapturing = true
       }

       /** 停止采集，终止进程 */
       stop(): void {
         this.process?.kill();
         this.process = null;
         this._isCapturing = false;
       }
     }
     export const audioCapture = new AudioCapture();
     ```
  2. 创建 `broca-vscode/src/extension/asrClient.ts`：
     ```typescript
     import WebSocket from 'ws';

     class AsrClient {
       private ws: WebSocket | null = null;

       async connect(serverUrl: string, token: string, onEvent: (e: any) => void): Promise<void> {
         // 构建 ws URL: ws://host:9000/api/asr/stream?token=xxx
         // 创建 WebSocket 连接
         // onmessage: 解析 JSON → onEvent
         // onclose/onerror: 处理
       }

       sendAudioFrame(data: Buffer): void {
         this.ws?.send(data);
       }

       disconnect(): void {
         this.ws?.close();
         this.ws = null;
       }
     }
     export const asrClient = new AsrClient();
     ```
  3. 在 `broca-vscode/package.json` 的 `dependencies` 中添加 `ws` 和 `@types/ws`（devDependency）
  4. 修改 `broca-vscode/src/extension/chatWebView.ts`，添加语音输入消息处理：
     ```typescript
     // 在 handleWebViewMessage 中新增 case:
     case 'startVoiceInput':
       this.startVoiceInput();
       break;
     case 'stopVoiceInput':
       this.stopVoiceInput();
       break;

     async startVoiceInput() {
       // 1. 检测 AudioCapture.isSupported()
       // 2. 连接 ASR WebSocket
       //    asrClient.connect(this.wsUrl, this.token, (event) => {
       //      this.panel.webview.postMessage({ type: 'asrEvent', payload: event });
       //    });
       // 3. 启动音频采集
       //    audioCapture.start({
       //      onAudioFrame: (data) => asrClient.sendAudioFrame(data),
       //      onError: (err) => this.panel.webview.postMessage({ type: 'asrError', payload: err }),
       //    });
     }

     stopVoiceInput() {
       audioCapture.stop();
       asrClient.disconnect();
       // 通知 webview
       this.panel.webview.postMessage({ type: 'voiceInputStopped' });
     }
     ```
  5. 在扩展 dispose 时清理：`audioCapture.stop()` + `asrClient.disconnect()`
- **预期产出**：
  - `broca-vscode/src/extension/audioCapture.ts`
  - `broca-vscode/src/extension/asrClient.ts`
  - 更新后的 `broca-vscode/src/extension/chatWebView.ts`
  - 更新后的 `broca-vscode/package.json`
- **验收标准**：
  - [ ] 系统安装 `sox` 后，`AudioCapture.isSupported()` 返回 true
  - [ ] `audioCapture.start()` 后，`onAudioFrame` 每 ~128ms 被调用，传入 16kHz PCM Buffer
  - [ ] `asrClient.connect()` 连接后端 ASR WebSocket 成功
  - [ ] Webview 发送 `startVoiceInput` 后，Extension Host 开始采集并流式传输
  - [ ] Webview 发送 `stopVoiceInput` 后，采集进程被终止，WebSocket 断开
  - [ ] 系统未安装 sox/ffmpeg 时，`isSupported()` 返回 false
  - [ ] 扩展 deactivate 时，所有音频采集进程和 WebSocket 连接被清理

#### Task 3.2: VSCode Webview ChatInput 集成语音输入

- **目标**：在 VSCode 扩展的 webview `ChatInput.vue` 中添加麦克风按钮和实时识别展示
- **步骤**：
  1. 修改 `broca-vscode/src/webview/src/components/ChatInput.vue`：
  2. 模板部分 — 在发送按钮旁添加麦克风按钮：
     ```html
     <button
       class="voice-btn"
       :class="{ 'voice-btn--active': isRecording }"
       :disabled="!canStartRecording"
       @click="toggleVoiceInput"
       :title="isRecording ? '停止录音' : '语音输入'"
     >
       {{ isRecording ? '⏹' : '🎤' }}
     </button>
     ```
  3. 添加录音状态提示：
     ```html
     <div v-if="isRecording" class="voice-status">
       <span class="voice-status__dot" />
       正在聆听...
     </div>
     ```
  4. 脚本部分：
     ```typescript
     import { acquireVsCodeApi } from '../api/vscode';
     const vscode = acquireVsCodeApi();

     const isRecording = ref(false);
     const canStartRecording = computed(() => chatStore.runnerAlive);

     // 监听 extension host 发来的 ASR 事件
     function initVoiceInputListeners() {
       window.addEventListener('message', (event: MessageEvent) => {
         const data = event.data;
         if (data.type === 'asrEvent') {
           const payload = data.payload;
           if (payload.type === 'partial') {
             chatStore.inputText = payload.text;
           } else if (payload.type === 'final') {
             // 累积 final 文本
           } else if (payload.type === 'error') {
             stopVoiceInput();
             // 显示错误提示
           }
         } else if (data.type === 'voiceInputStopped') {
           isRecording.value = false;
         }
       });
     }

     function toggleVoiceInput() {
       if (isRecording.value) {
         stopVoiceInput();
       } else {
         isRecording.value = true;
         vscode.postMessage({ type: 'startVoiceInput' });
       }
     }

     function stopVoiceInput() {
       vscode.postMessage({ type: 'stopVoiceInput' });
     }

     onMounted(() => initVoiceInputListeners());
     ```
  5. 样式：与 Web 前端一致的麦克风按钮样式（使用 VSCode CSS 变量 `--input-bg` 等适配主题）
- **预期产出**：更新后的 `broca-vscode/src/webview/src/components/ChatInput.vue`
- **验收标准**：
  - [ ] VSCode 扩展 ChatInput 渲染时麦克风按钮可见
  - [ ] 点击麦克风按钮后，Extension Host 控制台输出音频采集启动日志
  - [ ] 说话时输入框实时显示识别文字
  - [ ] 点击停止后，识别文字保留在输入框
  - [ ] 编辑后按 Enter 发送消息，通过现有 Socket.IO 流程正常发送
  - [ ] VSCode 主题切换后，按钮和文字颜色正确适配

## 风险与应对

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| **Sherpa-ONNX Python 包兼容性问题** | 某些 Python 版本或平台可能缺少预编译 wheel | 提前在目标平台（macOS ARM x64, Linux x64）测试 `pip install sherpa-onnx`；必要时从源码编译 |
| **模型识别准确率不满足预期** | 用户反馈识别效果差，尤其是中文 | 提供模型切换机制（`BROCA_ASR_MODEL` 环境变量），可切换到更高质量的 Paraformer 模型；后续可考虑 FunASR 替代 |
| **VSCode webview CSP 阻止 WebSocket** | VSCode 中语音输入完全不可用 | VSCode CSP 的 `connect-src` 已包含 `ws://localhost`（见 explorer 报告），应支持 localhost WebSocket。如仍有问题，可通过 `vscode.env` API 或 extension host 代理 |
| **VSCode Extension Host 音频采集工具缺失** | 用户未安装 sox/ffmpeg 时无法使用语音输入 | `isSupported()` 检测 + UI 提示"请安装 sox/ffmpeg"；在 README 中提供各平台安装命令 |
| **麦克风权限被拒绝** | Web 前端无法录音 | 捕获 `NotAllowedError`，显示友好的权限引导提示 |
| **AudioContext 16kHz 采样率不被支持** | 音频采样率不匹配导致识别错误 | 检测 `audioContext.sampleRate`，如果不等于 16000 则使用线性插值重采样 |
| **高并发 WebSocket 连接导致内存增长** | 大量用户同时语音输入导致 OOM | 每个 WebSocket 连接独立的 OnlineStream；设置最大并发连接数限制（如 20）；空闲超时自动清理 |
| **浏览器标签页切到后台时 AudioContext 挂起** | 切回标签页后录音中断 | 监听 `visibilitychange` 事件，后台时暂停录音，前台时恢复 |

## 未解决的问题

- **模型选择确认**：默认使用 `sherpa-onnx-streaming-zipformer-small-bilingual-zh-en-2023-02-16`（中英双语，轻量），如需更高精度可切换到 Paraformer 模型。请在执行前确认此选择是否满足需求。
- ~~**VSCode 音频采集工具偏好**~~：**已确认**。当前 macOS 环境已有 `ffmpeg`（Homebrew），运行时自动检测 sox → ffmpeg 优先级，无需额外安装。
- **是否需要支持多语言切换**：当前方案默认中英双语模型。如果用户需要其他语言（如日语、韩语），需要额外下载对应模型并实现运行时切换逻辑。
