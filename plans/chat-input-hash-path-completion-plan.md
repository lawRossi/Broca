# Chat Input `#` 文件路径补全计划

## 概述
- **目标**：在 ChatInput 组件中新增特性——输入 `#` 时触发文件路径补全，在 **broca-web**、**broca-vscode**、**broca-tui** 三个前端全部支持（broca-chrome 本次不做）。
- **背景**：三个前端的 ChatInput 已支持 `/command` 与 `@mention` 两种补全；本次新增 `#` 路径补全，与两者并列，形成三套补全体系。用户确认：`#` 之前**不需要空格**也触发补全（与 `@` 规则一致，用 `lastIndexOf('#')` 检测）。
- **约束条件**：
  - 补全根目录 = 当前会话 `workspace`（后端 `Session.workspace`），无 workspace 时回退到后端进程 cwd
  - `#..`（父目录穿越）与绝对路径暂不支持，限制在根目录内
  - 三种补全互斥，优先级：`/` > `@` > `#`，同一时刻只显示一种列表
  - 选中目录 → 插入 `dir/` 并继续钻取列出子目录；选中文件 → 插入 `#路径 `（带尾随空格）
  - 键盘交互与现有 `/`、`@` 完全一致（↑/↓ 移动、Enter 选择、Esc 关闭）

## 相关材料
- 后端文件 API：`broca-web/backend/app/api/files.py`（现有 `GET /api/files?path=X` 实现）
- 后端文件 API 测试：`broca-web/tests/integration/test_api_files.py`（测试模式参考）
- Web 前端 ChatInput：`broca-web/frontend/src/components/ChatInput.vue`
- Web 前端文件 API 封装：`broca-web/frontend/src/api/files.ts`
- Web 前端会话 API：`broca-web/frontend/src/api/session.ts`（`getSession(sessionId)` 返回含 `workspace` 的 Session）
- VSCode 前端 ChatInput：`broca-vscode/src/webview/src/components/ChatInput.vue`
- VSCode 扩展 API 客户端：`broca-vscode/src/extension/api.ts`（含 `getCommands()`，需新增 `completeFiles()`）
- VSCode 扩展消息处理：`broca-vscode/src/extension/chatWebView.ts`（`case 'fetchCommands'` / `handleFetchCommands` 模式，约 909/1954 行）
- VSCode 通信协议类型：`broca-vscode/src/extension/types.ts`（`WebViewToExtension` / `ExtensionToWebView` 联合类型，约 270/352 行）
- TUI ChatInput：`broca-tui/broca_tui/widgets/chat_input.py`（已有 `_autocomplete_type` 支持 "command"/"mention"）
- TUI Session API：`broca-tui/broca_tui/api/session.py`（`SessionAPI`，基于 `APIClient.get()`）
- TUI 会话屏：`broca-tui/broca_tui/screens/chat.py`（144-156 行已获取 `session_info["workspace"]` 传给 info_sidebar）
- TUI 测试模式：`broca-tui/tests/test_chatinput_debug.py`（`App.run_test` + `pilot` 模式参考）

## 总体方案

**后端**：在 `broca-web/backend/app/api/files.py` 新增 `GET /api/files/complete?base=<workspace>&prefix=<相对路径>` 端点，返回相对路径补全建议列表（`name`/`path`/`is_dir`），避免前端拼接服务端绝对路径。参数语义：
- `base` 为空 → 使用后端 cwd
- `prefix` 拆分为「目录部分 + 名字前缀」，如 `src/comp` → 目录 `src`、前缀 `comp`；`src/` → 目录 `src`、前缀空；空串 → 根目录
- 在 `base/dir` 下列出条目，按名字前缀过滤（startswith），目录在前、文件在后排序
- 相对路径 = `dir/name`（相对 base），后端负责拼接，前端零路径运算

**前端**：三个前端各自在 ChatInput 中增加 `#` 分支（置于 `/`、`@` 之后）：
- 输入变化时取文本中最后一个 `#`，`#` 后无空格 → 触发；有空格 → 关闭
- 调用后端 complete 端点（web 直连 `filesApi`；vscode 经 `postMessage` 由扩展进程转发；tui 经 `SessionAPI`）
- 选中文件：替换 `#` 后文本为 `#完整相对路径 ` 并关闭列表
- 选中目录：替换为 `dir/` 并立即重新请求子目录列表（继续钻取）

**测试**：后端集成测试扩展 `test_api_files.py`；TUI 新增自动化测试；web/vscode 以构建 + 手动验证清单为主（无现成组件测试目录，不引入新测试基建）。

## 执行计划

### Phase 1: 后端 `GET /api/files/complete` 端点

**目标**：提供 `#` 路径补全的后端能力。

**阶段验收标准**：
- [ ] 端点可列出根目录内容（`prefix` 为空）、按前缀过滤、按 `dir/` 钻取
- [ ] 返回相对路径（相对 base），目录在前文件在后排序
- [ ] base 为空回退 cwd；`..` 段被拒绝；目录不存在返回空列表
- [ ] 集成测试通过（`pytest broca-web/tests/integration/test_api_files.py`）

#### Task 1.1: 实现 `/files/complete` 端点
- **目标**：在 `broca-web/backend/app/api/files.py` 新增补全端点
- **步骤**：
  1. 新增 pydantic 模型 `FileCompleteItem(name, path, is_dir)` 与 `FileCompleteResponse(base, prefix, completions, total)`
  2. 新增 `GET /files/complete` 路由，参数 `base: str = ""`、`prefix: str = ""`
  3. 路径解析：`base` 为空 → `Path.cwd()`；否则 `Path(base).expanduser().resolve()`；不存在的 base 返回空 completions
  4. `prefix` 校验：包含 `..` 段（`".." in Path(prefix).parts`）→ 返回空列表
  5. 拆分 `prefix`：`Path(prefix)` 的 parent（非 `.`）作为 `dir`，name 作为过滤前缀；`prefix` 以 `/` 结尾时 `dir = prefix`、过滤前缀为空
  6. 列出 `base/dir` 下条目：目录在前文件在后、按 `name.lower()` 排序；按过滤前缀 startswith 过滤（空前缀不过滤）
  7. 返回：`base`（解析后绝对路径）、`prefix`（原始）、`completions`（`path = dir/name` 相对路径，`is_dir` 标记）、`total`
  8. 复用 `ApiResponse.success()` 包装
- **预期产出**：`broca-web/backend/app/api/files.py` 新增端点；`curl` 可验证
- **验收标准**：
  - [ ] `GET /api/files/complete?base=<tmpdir>&prefix=` 返回 tmpdir 下全部条目，`path` 与 `base` 拼接后与实际路径一致
  - [ ] `prefix=src/`（base 下存在 src 目录）返回 src 下的条目，`path` 形如 `src/<name>`
  - [ ] `prefix=comp` 只返回名字以 `comp` 开头的条目
  - [ ] `prefix=../x` 返回空 `completions`；`base` 不存在返回空 `completions`
  - [ ] 排序：目录在前、文件在后，各自按名称排序

### Phase 2: 三个前端支持 `#` 路径补全

**目标**：web、vscode、tui 三个 ChatInput 全部支持 `#` 补全。

**阶段验收标准**：
- [ ] 三个前端输入 `#` 均弹出文件路径列表（无前置空格要求）
- [ ] 前缀过滤、`dir/` 钻取、选文件插入 `#路径 `、选目录继续钻取、Esc/点击外部关闭均生效
- [ ] 与 `/`、`@` 补全互斥且不回归现有功能

#### Task 2.1: broca-web ChatInput 支持 `#` 补全
- **目标**：web 前端实现 `#` 文件路径补全
- **步骤**：
  1. `broca-web/frontend/src/api/files.ts`：新增 `completeFiles(base: string, prefix: string)`，调用 `GET /files/complete`
  2. `ChatInput.vue` 新增状态：`showPathSuggestions`、`pathSuggestions`（`{name, path, is_dir}[]`）、`selectedPathIndex`、`justSelectedPath`、`pathSuggestionsRef`
  3. 新增 `chatWorkspace` ref：watch `chatStore.sessionId` 变化时调用 `sessionApi.getSession(sessionId)` 获取 `workspace`（失败置空字符串）
  4. 将现有 watch 中 `/`、`@` 检测逻辑末尾追加 `#` 检测分支：`lastIndexOf('#')`，`#` 后无空格 → 调 `completeFiles(chatWorkspace, 搜索词)` 渲染建议；有空格 → 关闭。若 `#` 检测前 `/` 或 `@` 已命中并 return，则自然互斥
  5. 把 `#` 检测抽成独立函数 `updatePathSuggestions(text)`，供 watch 与「选中目录后继续钻取」两处调用（watch 内调用时受 `justSelectedPath` 保护）
  6. 新增 `selectPath(item)`：选中文件 → 替换为 `before#path `（设置 `justSelectedPath=true`，100ms 后复位，参照 `selectMention`）；选中目录 → 替换为 `before#path/`，立即调用 `updatePathSuggestions(newText)` 继续列出子目录（不设 justSelectedPath）
  7. `handleKeyDown`：在 `/`、`@` 分支之后增加 `#` 分支（↑/↓ 移动、Enter 选择、Esc 关闭）
  8. `handleClickOutside` 与 `handleMentionClick`/`handleCommandClick` 同模式增加 `#` 列表的关闭与点击处理；`handleSendMessage` 开头 guard 增加 `justSelectedPath`
  9. 模板：新增 `#` 建议列表 DOM（复用 command/mention 列表样式），每条显示 `#` 前缀 + 路径，目录项加「📁」或 `/` 后缀
  10. placeholder 提示更新为「输入/执行命令，@指定agent，#引用文件」
- **预期产出**：web 端 `#` 补全可用
- **验收标准**：
  - [ ] `chatStore.sessionId` 变化后能获取 workspace；`completeFiles` 请求参数正确
  - [ ] 输入 `#`（前面无空格）弹出列表；输入 `#ab` 按前缀过滤；输入 `#dir/` 列出子目录
  - [ ] 选中文件插入 `#路径 ` 且关闭列表、100ms 内不再重弹；选中目录插入 `dir/` 并继续显示子目录
  - [ ] `/`、`@`、`#` 三种列表互斥；Esc/点击外部关闭
  - [ ] `pnpm build`（broca-web/frontend）通过，`/`、`@` 补全与发送消息无回归

#### Task 2.2: broca-vscode 支持 `#` 补全
- **目标**：vscode 扩展与 webview 实现 `#` 文件路径补全
- **步骤**：
  1. `broca-vscode/src/extension/api.ts`：新增 `completeFiles(base: string, prefix: string)` → `GET /files/complete`（参照 `getCommands()`）
  2. `broca-vscode/src/extension/types.ts`：`WebViewToExtension` 联合类型增加 `'listFiles'`；`ExtensionToWebView` 增加 `'files'`
  3. `broca-vscode/src/extension/chatWebView.ts`：
     - 消息分发增加 `case 'listFiles': await this.handleListFiles(sessionId, panel, message.payload)`
     - 新增 `handleListFiles`：`apiClient.getSession(sessionId)` 拿 `workspace`（无则空串），调 `completeFiles(workspace, payload.prefix)`，`postToPanel({type:'files', payload})`；失败时 post 空列表（webview 有兜底）
  4. `broca-vscode/src/webview/src/components/ChatInput.vue`：
     - 新增状态与检测逻辑，与 Task 2.1 一致（数据源改为 `postMessage({type:'listFiles', payload:{prefix}})`，监听 `onMessage` 中 `type==='files'` 的回包）
     - `selectPath` 文件/目录行为、键盘导航、`handleSend` guard、点击外部关闭、模板列表与目录图标
  5. 常量兜底：若扩展回复 `files` 为空或 3s 未回复，隐藏列表（不展示 fallback 数据）
- **预期产出**：vscode 聊天面板 `#` 补全可用
- **验收标准**：
  - [ ] 扩展 `api.ts` 新增方法且 `handleListFiles` 通过 session workspace 请求补全
  - [ ] webview 输入 `#` 弹出列表，回包 `files` 正确驱动渲染
  - [ ] 前缀过滤、`dir/` 钻取、选文件/目录行为、Esc/点击外部关闭与 web 端一致
  - [ ] `npm run build`（broca-vscode）通过，扩展编译无类型错误

#### Task 2.3: broca-tui ChatInput 支持 `#` 补全
- **目标**：TUI 终端 ChatInput 实现 `#` 文件路径补全
- **步骤**：
  1. `broca-tui/broca_tui/api/session.py`：`SessionAPI` 新增 `complete_files(base: str, prefix: str)` → `APIClient.get("/files/complete", params={...})`，返回 `completions` 列表
  2. `broca-tui/broca_tui/widgets/chat_input.py`：
     - 新增 `_workspace` 属性与 `set_workspace(workspace)` 方法
     - `_handle_input_change` 在 command、mention 分支后增加 path 分支（`"#" in value`）：取 `value.rfind("#")`，`#` 后无空格才触发；调 `SessionAPI.complete_files(self._workspace, 搜索词)`（异步，用 `run_worker` 或缓存结果后刷新 ListView）
     - `_show_autocomplete` 增加 `"path"` 类型：文件项渲染 `#path`，目录项渲染 `#path/`（或加 `📁`）
     - `_select_autocomplete` 增加 `"path"` 分支：选中目录 → 替换为 `#dir/` 并触发一次补全刷新（继续钻取）；选中文件 → 替换为 `#path `；沿用 `_suppress_next_change`
     - `_send_message` 无需改动（已有 `_autocomplete_type` 拦截）
  3. `broca-tui/broca_tui/screens/chat.py`：载入会话时（约 144-156 行获取 workspace 处）调用 `chat_input.set_workspace(workspace)`；workspace 为空时 ChatInput 内部回退空串（后端回退 cwd）
  4. placeholder 文案补充「#引用文件」
- **预期产出**：TUI `#` 补全可用
- **验收标准**：
  - [ ] `ChatInput.set_workspace` 生效；`SessionAPI.complete_files` 请求参数与返回解析正确
  - [ ] 输入 `#` 弹出列表（ListView），`#ab` 前缀过滤，`#dir/` 钻取
  - [ ] 选中目录插入 `#dir/` 并继续显示子目录；选中文件插入 `#path ` 并关闭
  - [ ] 与 `/`、`@` 补全互斥；Enter 在有列表时先选择而非发送（沿用现有逻辑）
  - [ ] `python -m pytest broca-tui/tests`（相关用例）通过

### Phase 3: 测试与验证

**目标**：补齐自动化测试并完成三前端的手动验证。

**阶段验收标准**：
- [ ] 后端集成测试新增 complete 用例并全部通过
- [ ] TUI 新增自动化测试通过
- [ ] 三前端按验证清单手动验证通过，无回归

#### Task 3.1: 后端集成测试
- **目标**：为 `/files/complete` 增加集成测试
- **步骤**：
  1. 在 `broca-web/tests/integration/test_api_files.py` 新增 `TestFileCompleteAPI` 类
  2. 用例：根目录列出（prefix 空）、前缀过滤、`dir/` 钻取、`..` 拒绝、base 不存在空列表、排序（目录在前）
  3. 运行 `cd broca-web/backend && python -m pytest ../tests/integration/test_api_files.py -q`（或项目既有 pytest 启动方式）
- **预期产出**：新增测试类且全部通过
- **验收标准**：
  - [ ] 新增 ≥5 个用例覆盖上述场景
  - [ ] 测试全部通过，且不影响既有 files 用例

#### Task 3.2: TUI 自动化测试
- **目标**：TUI ChatInput `#` 补全自动化测试
- **步骤**：
  1. 新增 `broca-tui/tests/test_chatinput_path_complete.py`（参照 `test_chatinput_debug.py` 的 `App.run_test` + `pilot` 模式）
  2. 用例：`set_workspace` 后输入 `#` 弹出 ListView；`#ab` 过滤；`#dir/` 钻取（mock `SessionAPI.complete_files`）；选择目录后续传；选择文件插入 `#path `
  3. 对 `complete_files` 用 monkeypatch/mock 返回固定数据，避免真实网络
  4. 运行 `cd broca-tui && python -m pytest tests/test_chatinput_path_complete.py -q`
- **预期产出**：TUI 自动化测试通过
- **验收标准**：
  - [ ] 新增测试文件，覆盖触发、过滤、钻取、选择四类行为
  - [ ] 测试全部通过，无真实网络依赖

#### Task 3.3: 三前端手动验证清单
- **目标**：验证 web/vscode 前端功能与整体无回归
- **步骤**：
  1. web：`cd broca-web/frontend && pnpm build`；启动前后端，在聊天页验证清单（输入 `#` 出列表、`#a` 过滤、`#dir/` 钻取、选文件/目录、Esc 关闭、`/` `@` 不受影响）
  2. vscode：`cd broca-vscode && npm run build`；F5 调试扩展，打开聊天面板执行同清单
  3. tui：运行 `python -m broca_tui`（或项目启动方式），执行同清单
  4. 将验证结果记录到 `plans/reports/execution/` 下
- **预期产出**：三前端手动验证通过，记录验证结果
- **验收标准**：
  - [ ] web/vscode 构建通过，无 TS 错误
  - [ ] 三前端功能清单全部通过
  - [ ] `/`、`@` 补全、文件上传、发送消息无回归

## 风险与应对
| 风险 | 影响 | 应对策略 |
|------|------|----------|
| `#` 无条件触发导致误弹（如 markdown 标题、注释） | 输入干扰 | 与 `@` 规则一致（用户确认）；`#` 后有空格立即关闭；Esc/点击外部可关闭 |
| 异步请求竞态（快速输入时旧响应覆盖新响应） | 建议列表错乱 | 前端记录请求序号/仅采纳最后一次请求的响应（Vue 用递增 id 判断，TUI 在 worker 内比对） |
| 会话 workspace 获取失败 | 无根目录，列表为空 | 回退空串 → 后端用 cwd；前端静默隐藏列表，不报错 |
| 目录权限不足/条目不可读 | 部分条目缺失 | 后端沿用现有 `except (PermissionError, OSError)` 容错（参考 list_files） |
| 大目录性能 | 响应慢 | 限制每次返回条目数上限（如 200），超出截断并提示 |
| 三套补全互斥逻辑回归 | `/`、`@` 现有功能受影响 | 检测顺序固定 `/` > `@` > `#`；每个前端改动后跑既有相关测试 |

## 未解决的问题
- 无（已与用户确认触发规则与交互设计；broca-chrome 明确本次不做）
