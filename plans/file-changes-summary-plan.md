# File Changes Summary in Execution Summary (简洁模式)

## 概述

- **目标**：在三个前端（Web、TUI、VS Code）的 chat 页面简洁模式下，为执行摘要（Execution Summary）增加"变更文件"（Changed Files）展示项：默认显示新增/删除/修改的文件数量，展开可查看具体文件列表。后端根据一个 turn 内最早和最后的 snapshot 计算文件变更。活跃 turn 完成后实时展示。
- **背景**：目前简洁模式的执行摘要包含步骤数、TODO 列表、工具调用统计三项。用户希望额外看到当前 turn 对工作区文件做了什么改动，快速了解影响范围。
- **约束条件**：
  - 三个前端（Web/TUI/VS Code）的布局和样式必须一致
  - 活跃 turn 完成后实时展示（via Socket.IO）
  - 历史 turn 数据也要包含文件变更信息（via REST API）
  - 不要修改已有的执行摘要项目（步骤/任务/工具调用）的样式
  - 不改动当前 snapshot 系统的基本逻辑，只在其上增加计算

## 相关材料

- **后端核心文件**：
  - `broca/execution_engine.py` — Step/Turn 生命周期管理，`_capture_step_end()`、`process_turn_end()`
  - `broca/snapshot/patch.py` — `PatchCalculator`，含 `calculate_diff()`（unified diff）和 `get_diff_summary()`（返回 `files_added/deleted/modified`）
  - `broca/session/models.py` — `Turn` 模型、`create_turn_end()`、`create_step_end()`
  - `broca/session/service.py` — `get_turn_stats()` 聚合 turn 统计数据
  - `broca/communication/socketio_client.py` — `send_turn_end()` Socket.IO 发送方法

- **前端组件文件**（三个前端各一）：
  - Web: `broca-web/frontend/src/components/ChatTurnCard.vue` — 简洁模式 turn 卡片
  - TUI: `broca-tui/broca_tui/widgets/turn_card.py` — 简洁模式 turn 卡片
  - VS Code: `broca-vscode/src/webview/src/components/ChatTurnCard.vue` — 简洁模式 turn 卡片

- **前端 Store 文件**（处理 socket 消息和 turn 数据）：
  - Web: `broca-web/frontend/src/stores/chat.ts` — `TurnSummary` 接口、`handleTurnEnd()`、`updateTurnSummaryOnMessage()`
  - TUI: `broca-tui/broca_tui/stores/chat_store.py` — `TurnSummary` 数据类、`finalize_turn_summary()`
  - VS Code: `broca-vscode/src/webview/src/stores/chat.ts` — `TurnSummary` 接口、`handleTurnEndMessage()`

- **后端 API**：
  - `broca-web/backend/app/api/session.py` — GET `/sessions/{id}/turns` 返回 turn 列表

- **VS Code 扩展类型**：
  - `broca-vscode/src/extension/types.ts` — `TurnSummaryData` 接口

## 总体方案

### 核心思路

后端在每个 turn 结束时，通过对比该 turn 最早快照（第一次 step_start 时捕获）和最晚快照（最后一次 step_end 时捕获），使用 `PatchCalculator.get_diff_summary()` 计算出完整文件变更摘要（包含 `files_added`、`files_deleted`、`files_modified` 及各自计数）。然后通过 `turn_end` 的 Socket.IO 消息实时推送到前端，同时存入库中供历史查询。

### 数据结构

```typescript
// 新增字段定义
interface ChangedFiles {
  totalAdded: number      // 新增文件数
  totalDeleted: number    // 删除文件数
  totalModified: number   // 修改文件数
  filesAdded: string[]    // 新增文件路径列表
  filesDeleted: string[]  // 删除文件路径列表
  filesModified: string[] // 修改文件路径列表
}
```

### 数据流

```
Step 1: _capture_step_start() → 捕获 first_snapshot_hash
Step 1: _capture_step_end()   → 捕获 last_snapshot_hash (更新为 end_snapshot_hash)
Step 2: _capture_step_start() → 更新 current_snapshot_hash
Step 2: _capture_step_end()   → 更新 last_snapshot_hash
...
process_turn_end() → 计算 diff(first_snapshot_hash, last_snapshot_hash)
                    → get_diff_summary(diff) → {totalAdded, totalDeleted, totalModified, filesAdded, filesDeleted, filesModified}
                    → 加入 turn_end message data.changed_files
                    → Socket.IO 广播到前端
                    → 入库持久化

前端 handleTurnEnd() → 提取 changed_files → 设置到 TurnSummary.changedFiles
TurnCard 渲染 → 执行摘要区域增加 "📁 变更文件" 行
```

## 执行计划

### Phase 1: 后端核心逻辑
**目标**：实现 turn 级文件变更的计算、传输与存储

**阶段验收标准**：
- [ ] 每个 turn 结束时，后端能计算该 turn 最早/最晚快照间的文件变更摘要
- [ ] `turn_end` Socket.IO 消息中携带 `changed_files` 字段
- [ ] `step_end` 消息的 patch 中增加 `summary` 子字段（含 added/deleted/modified 分类）
- [ ] turn 变更数据持久化到数据库，历史 turn 可通过 REST API 获取

#### Task 1.1: 增强 `_capture_step_end()` — 在 patch 中包含 diff summary
- **目标**：在 step_end 消息的 patch 字段中增加 `summary` 子字段，包含文件的 add/delete/modify 分类信息
- **步骤**：
  1. 在 `broca/execution_engine.py` 的 `_capture_step_end()` 中，在已经 `calculate_patch()` 之后，增加一步：如果 `patch` 有 `files`，则调用 `self.patch_calculator.calculate_diff(from_hash, to_hash)` 获取 diff 内容
  2. 调用 `self.patch_calculator.get_diff_summary(diff_content)` 获取分类摘要
  3. 将摘要加入 patch 字典：`patch["summary"] = diff_summary`
  4. 注意异常处理：如果 diff 计算失败，`summary` 应为空字典
- **预期产出**：`step_end` 消息的 `data.patch` 从 `{"snapshot_hash": "...", "files": [...]}` 变为 `{"snapshot_hash": "...", "files": [...], "summary": {"total_files": N, "files_added": [...], "files_deleted": [...], "files_modified": [...], ...}}`
- **验收标准**：
  - [ ] 有写操作的 step 结束时，patch.summary 包含正确的 files_added/files_deleted/files_modified 列表
  - [ ] 无写操作的 step 结束时，patch 为空字典，不报错
  - [ ] 计算失败时（如 git 错误），patch 继续为空字典，不阻断流程

#### Task 1.2: 跟踪 turn 级最早/最晚快照
- **目标**：在执行引擎中记录每个 turn 的第一个和最后一个快照哈希，用于 turn_end 时计算全量 diff
- **步骤**：
  1. 在 `broca/execution_engine.py` 的 `__init__` 或 `execute()` 中初始化两个新属性：`self._turn_first_snapshot_hash = None`、`self._turn_last_snapshot_hash = None`
  2. 在 `_capture_step_start()` 中，当 `self.current_snapshot_hash` 有效且 `self._turn_first_snapshot_hash` 为 None 时，记录：`self._turn_first_snapshot_hash = self.current_snapshot_hash`
  3. 在 `_capture_step_end()` 中，当 `snapshot_hash`（即 `end_snapshot_hash`）有效时，更新：`self._turn_last_snapshot_hash = snapshot_hash`
- **预期产出**：执行引擎在每个 turn 执行过程中，持续跟踪最早和最晚的快照哈希
- **验收标准**：
  - [ ] 第一个 step_start 成功后，`_turn_first_snapshot_hash` 被正确设置为当时的工作区快照
  - [ ] 每个有写操作的 step_end 后，`_turn_last_snapshot_hash` 被更新为最新快照
  - [ ] turn 结束时，两个哈希值指向合理的快照（能用于 git diff）

#### Task 1.3: 在 `process_turn_end()` 中计算全量变更并加入 turn_end 消息
- **目标**：在 turn 结束时计算该 turn 的完整文件变更，并包含在 turn_end 消息中
- **步骤**：
  1. 修改 `process_turn_end()`：在保存和发送 turn_end 之前，增加文件变更计算逻辑
  2. 如果 `_turn_first_snapshot_hash` 和 `_turn_last_snapshot_hash` 都存在且不同，调用 `self.patch_calculator.calculate_diff()` 和 `get_diff_summary()`
  3. 构造 `changed_files` 字典：
     ```python
     changed_files = {
         "total_added": len(diff_summary.get("files_added", [])),
         "total_deleted": len(diff_summary.get("files_deleted", [])),
         "total_modified": len(diff_summary.get("files_modified", [])),
         "files_added": diff_summary.get("files_added", []),
         "files_deleted": diff_summary.get("files_deleted", []),
         "files_modified": diff_summary.get("files_modified", []),
     }
     ```
  4. 修改 `MessageProtocol.create_turn_end()`：增加 `changed_files` 可选参数，将其加入 `data` 字典
  5. 修改 `communicator.send_turn_end()`：增加 `changed_files` 参数透传
  6. 在 `process_turn_end()` 中调用 `send_turn_end()` 时传入 `changed_files=changed_files`
  7. 清理跟踪属性：`self._turn_first_snapshot_hash = None`、`self._turn_last_snapshot_hash = None`
- **预期产出**：前端收到的 turn_end Socket.IO 消息的 `data` 中包含 `changed_files` 字段
- **验收标准**：
  - [ ] turn_end 消息的 `data.changed_files` 包含正确的 `total_added/total_deleted/total_modified` 计数和文件列表
  - [ ] turn 内无文件变更时，`changed_files` 所有计数为 0，文件列表为空
  - [ ] 无 snapshot 跟踪的场景（如只读 turn）下，`changed_files` 为 None，不报错
  - [ ] 清理逻辑正确，不影响下一个 turn

#### Task 1.4: 持久化 turn_end 消息中的 changed_files 到数据库
- **目标**：确保 turn_end 消息保存到数据库时，`changed_files` 数据同时被持久化
- **步骤**：
  1. 检查 `session_manager.save_turn_end()` 和 `session_manager.save_message()` 的实现，确保它们能保存 `data` 字典到 Message 表的 `data` 字段（JSON）
  2. `create_turn_end()` 的 `data` 已包含 `changed_files`，直接通过 `save_message()` 保存即可 — 无需额外修改
  3. 验证：在 `get_turn_stats()` 中增加逻辑，从 turn 的 turn_end 消息中提取 `changed_files`
  4. 如果 `get_turn_stats()` 找不到 turn_end 消息或其 `changed_files`，返回空字典 `{}`
- **预期产出**：turn_end 消息的 `data.changed_files` 持久化到 Message 表的 data 字段
- **验收标准**：
  - [ ] turn_end 消息保存后，数据库中对应 Message 记录的 data 字段包含 `changed_files`
  - [ ] `get_turn_stats()` 返回的字典中包含 `changed_files` 字段

#### Task 1.5: REST API 返回 changed_files
- **目标**：GET `/sessions/{id}/turns` 返回的 turn 列表中每个 turn 包含 `changed_files` 字段
- **步骤**：
  1. 修改 `broca-web/backend/app/api/session.py` 中的 turn 列表构建逻辑：从 `stats` 中提取 `changed_files` 加入 turn 字典
  2. 修改 `broca/session/service.py` 的 `get_turn_stats()`：查找 turn_end 消息，提取 `data.get("changed_files", {})`
  3. 在 turn 字典中增加：`"changed_files": stats.get("changed_files", {})`
- **预期产出**：REST API 返回的每个 turn 对象包含 `changed_files` 字段
- **验收标准**：
  - [ ] API 返回的 turn 对象有 `changed_files` 字段
  - [ ] 有文件变更的 turn，`changed_files` 包含正确计数和文件列表
  - [ ] 无文件变更的 turn，`changed_files` 为空字典 `{}`
  - [ ] 旧数据（无 turn_end 消息）的 turn，`changed_files` 为空字典，不报错

### Phase 2: 前端数据层 — TurnSummary 增加 changedFiles
**目标**：三个前端的数据模型和消息处理逻辑支持 `changedFiles` 字段

**阶段验收标准**：
- [ ] 所有三个前端的 TurnSummary 接口/数据类都包含 `changedFiles` 字段
- [ ] turn_end 消息到达时，changedFiles 被正确设置到 TurnSummary
- [ ] 从 REST API 加载历史 turn 时，changedFiles 也被正确设置

#### Task 2.1: Web 前端 — TurnSummary 和消息处理
- **目标**：Web 前端 chat store 中 TurnSummary 接口增加 `changedFiles`，消息处理逻辑解析 turn_end 的 changed_files
- **步骤**：
  1. 在 `broca-web/frontend/src/stores/chat.ts` 中，定义 `ChangedFiles` 接口
  2. 在 `TurnSummary` 接口中增加 `changedFiles: ChangedFiles | null` 字段
  3. 在 `handleTurnEnd()`（或等价的 turn_end 处理逻辑）中，从 message 的 `data?.changed_files` 提取并设置到 turn 的 `changedFiles` 属性
  4. 在 `loadTurnHistory()` 的 turn 数据映射中，从后端返回的 `t.changed_files` 映射到 `changedFiles`
  5. ~~不在 step_end 时累加 changedFiles，只在 turn_end 时全量设置~~（已确认：不展示 step 级增量）
- **预期产出**：Web 前端能接收并存储 turn 的文件变更信息
- **验收标准**：
  - [ ] 实时 turn_end 消息到达时，对应 TurnSummary 的 `changedFiles` 被正确设置
  - [ ] 加载历史 turn 时，REST API 返回的 `changed_files` 被正确映射到 TurnSummary
  - [ ] 无文件变更时，`changedFiles` 为 null

#### Task 2.2: TUI 前端 — TurnSummary 和消息处理
- **目标**：TUI 前端的 TurnSummary 数据类增加 `changed_files`，消息处理逻辑解析 turn_end 的 changed_files
- **步骤**：
  1. 在 `broca-tui/broca_tui/stores/chat_store.py` 的 `TurnSummary` 数据类中增加字段：`changed_files: Optional[Dict[str, Any]] = None`
  2. 在 `finalize_turn_summary()` 方法中增加 `changed_files` 可选参数，设置到 turn
  3. 修改 turn_end 的处理逻辑（`handle_turn_end` 回调），提取数据并传递给 `finalize_turn_summary()`
  4. 在 `load_turn_history()` 的 turn 数据映射中，从后端返回的 `t.changed_files` 映射到 `changed_files`
- **预期产出**：TUI 前端能接收并存储 turn 的文件变更信息
- **验收标准**：
  - [ ] 实时 turn_end 消息到达时，对应 TurnSummary 的 `changed_files` 被正确设置
  - [ ] 加载历史 turn 时，REST API 返回的 `changed_files` 被正确映射

#### Task 2.3: VS Code 前端 — TurnSummary 和消息处理
- **目标**：VS Code 前端的 TurnSummary 接口增加 `changedFiles`，消息处理逻辑解析 turn_end 的 changed_files
- **步骤**：
  1. 在 `broca-vscode/src/extension/types.ts` 的 `TurnSummaryData` 接口中增加 `changed_files` 字段
  2. 在 `broca-vscode/src/webview/src/stores/chat.ts` 中定义 `ChangedFiles` 接口
  3. 在 `TurnSummary` 接口中增加 `changedFiles: ChangedFiles | null` 字段
  4. 在 `handleTurnEndMessage()` 中提取 `data?.changed_files` 并设置到 turn 的 `changedFiles`
  5. 在 `loadTurnHistory()` 的 turn 数据映射中处理 `t.changed_files`
- **预期产出**：VS Code 前端能接收并存储 turn 的文件变更信息
- **验收标准**：
  - [ ] 实时 turn_end 消息到达时，对应 TurnSummary 的 `changedFiles` 被正确设置
  - [ ] 加载历史 turn 时，`changed_files` 被正确映射

### Phase 3: 前端 UI 层 — 渲染文件变更区域
**目标**：三个前端的 TurnCard 组件中，在执行摘要区域渲染"变更文件"行

**阶段验收标准**：
- [ ] 三个前端在执行摘要中均显示"📁 变更文件"行
- [ ] 默认显示文件统计（新增 N 个，删除 N 个，修改 N 个）
- [ ] 展开后显示具体文件列表，按 add/delete/modify 分组
- [ ] 三端布局和样式一致（颜色、图标、字体大小等）

#### Task 3.1: Web 前端 — ChatTurnCard.vue 渲染文件变更
- **目标**：Web 前端的 TurnCard 组件在执行摘要中渲染文件变更行
- **步骤**：
  1. 在 `broca-web/frontend/src/components/ChatTurnCard.vue` 中，新增计算属性：
     - `showChangedFiles` — 判断 `turn.changedFiles` 是否有数据（total > 0 或 fiels 非空）
     - `hasToolExecution` 计算属性中新增 `showChangedFiles` 的或条件
  2. 在 `summary-body` 内，工具调用统计行之后，新增一个 `summary-row`：
     ```html
     <div v-if="showChangedFiles" class="summary-row">
       <span class="summary-label">📁 变更文件</span>
       <span class="summary-value" @click="toggleChangedFiles">
         +{{ turn.changedFiles.totalAdded }} -{{ turn.changedFiles.totalDeleted }} ~{{ turn.changedFiles.totalModified }}
         <span class="expand-icon">{{ showChangedFilesDetail ? '▲' : '▼' }}</span>
       </span>
     </div>
     ```
  3. 新增展开/折叠状态 `showChangedFilesDetail = ref(false)`
  4. 新增折叠区域，点击展开后显示详细文件列表（三个分组）：
     ```html
     <div v-if="showChangedFiles && showChangedFilesDetail" class="changed-files-detail">
       <div v-if="changedFiles.filesAdded.length" class="file-group">
         <span class="file-group-label text-green-600">新增</span>
         <div v-for="f in changedFiles.filesAdded" class="file-item">+ {{ f }}</div>
       </div>
       <div v-if="changedFiles.filesDeleted.length" class="file-group">
         <span class="file-group-label text-red-600">删除</span>
         <div v-for="f in changedFiles.filesDeleted" class="file-item">- {{ f }}</div>
       </div>
       <div v-if="changedFiles.filesModified.length" class="file-group">
         <span class="file-group-label text-yellow-600">修改</span>
         <div v-for="f in changedFiles.filesModified" class="file-item">~ {{ f }}</div>
       </div>
     </div>
     ```
  5. 样式：文件详情区域的背景色、字体、间距与 TODO 列表区域保持一致
- **预期产出**：Web 前端 TurnCard 执行摘要中显示文件变更信息
- **验收标准**：
  - [ ] 有文件变更的 turn，显示"📁 变更文件"行，统计数字正确
  - [ ] 点击统计数字展开/折叠详细文件列表
  - [ ] 无文件变更时不显示该行
  - [ ] 展开列表按新增/删除/修改分组，每组有颜色标识
  - [ ] 样式与现有执行摘要协调一致

#### Task 3.2: TUI 前端 — turn_card.py 渲染文件变更
- **目标**：TUI 前端的 TurnCard 组件在执行摘要中渲染文件变更行
- **步骤**：
  1. 在 `broca-tui/broca_tui/widgets/turn_card.py` 的 `TurnSummary` 中，确保 `changed_files` 字段可用
  2. 在 `_has_tool_execution()` 方法中增加 `self._show_changed_files()` 判断
  3. 新增 `_show_changed_files()` 方法：判断 `_turn.changed_files` 是否有变更
  4. 在 `compose()` 的执行摘要 `accent-tool` 区域的工具调用统计行之后，新增文件变更行（使用 Horizontal + Label）：
     ```python
     # 文件变更统计行（可点击展开/折叠）
     with Horizontal(classes="turn-summary-row", id="changed-files-row"):
         yield Label("📁 变更文件", classes="turn-summary-label")
         yield Label("", classes="turn-summary-value", id="changed-files-summary")
     # 文件变更详情（折叠区域）
     with Vertical(classes="changed-files-detail", id="changed-files-detail"):
         yield Label("", id="changed-files-detail-text")
     ```
  5. 在 `update_turn()` 方法中增加更新文件变更统计和详情的逻辑
  6. 新增 `_show_changed_files_detail` 状态，点击切换
  7. 在 `_update_all_sections()` 中控制显隐
  8. 在 CSS 中增加 `.changed-files-detail` 样式（与 todo-list 样式对齐）
- **预期产出**：TUI 前端 TurnCard 执行摘要中显示文件变更信息
- **验收标准**：
  - [ ] 有文件变更的 turn，显示"📁 变更文件"行
  - [ ] 显示 "新增 N 个，删除 N 个，修改 N 个" 统计
  - [ ] 点击可展开折叠显示详细文件列表
  - [ ] 无文件变更时不显示
  - [ ] 样式与现有执行摘要协调一致

#### Task 3.3: VS Code 前端 — ChatTurnCard.vue 渲染文件变更
- **目标**：VS Code 前端的 TurnCard 组件在执行摘要中渲染文件变更行（与 Web 版逻辑一致）
- **步骤**：
  1. 在 `broca-vscode/src/webview/src/components/ChatTurnCard.vue` 中，增加与 Task 3.1 相同的计算属性和模板逻辑
  2. 样式与 Web 版一致，使用 VS Code 主题变量（如 `--vscode-editor-foreground`、`--vscode-descriptionForeground`）
  3. 确保展开/折叠交互正常
- **预期产出**：VS Code 前端 TurnCard 执行摘要中显示文件变更信息
- **验收标准**：
  - [ ] 与 Web 版布局、样式、交互完全一致
  - [ ] 使用 VS Code 主题变量，适配深色/浅色主题
  - [ ] 其他行为与 Web 版相同

### Phase 4: 集成测试与验证
**目标**：端到端验证整个功能链路的正确性

**阶段验收标准**：
- [ ] 完整链路测试通过（编辑文件 → turn 完成 → 前端展示变更）
- [ ] 边界情况测试通过（无变更、只读操作、新建文件、删除文件、混合变更）
- [ ] 历史数据兼容性验证通过

#### Task 4.1: 端到端功能测试
- **目标**：验证从文件编辑到前端展示的完整链路
- **步骤**：
  1. 启动后端服务（Web 开发模式或 TUI 服务）
  2. 在一个会话中发送编辑文件的请求
  3. 在三个前端中分别验证：
     - turn 完成前：执行摘要中无文件变更信息（或为空）
     - turn 完成后：执行摘要中显示正确的文件变更统计
     - 展开后：显示具体的文件路径列表
  4. 分别测试以下场景：
     - 新建文件（`write_file` 新路径）
     - 修改文件（`edit_file` 已有路径）
     - 删除文件（如果有删除操作的工具）
     - 混合变更（同时新建、修改、删除）
     - 只读 turn（仅 `read_file`/`grep`/`web_search` 等，无文件变更）
     - 跨多个 step 的文件变更
- **预期产出**：所有场景下文件变更信息正确展示
- **验收标准**：
  - [ ] 新建文件的 turn 显示"新增 1 个"，展开显示文件名
  - [ ] 修改文件的 turn 显示"修改 N 个"，展开显示文件名
  - [ ] 混合变更的 turn 三个计数均正确
  - [ ] 只读 turn 不显示文件变更行
  - [ ] 跨 step 的变更被正确汇总

#### Task 4.2: 历史数据加载验证
- **目标**：验证从 REST API 加载历史 turn 时文件变更信息正确
- **步骤**：
  1. 创建几个包含文件变更的 turn
  2. 刷新页面或重新打开会话
  3. 切换到简洁模式
  4. 验证加载的历史 turn 包含正确的文件变更信息
- **预期产出**：历史 turn 的文件变更信息正确加载
- **验收标准**：
  - [ ] 历史 turn 显示正确的文件变更统计
  - [ ] 展开后显示正确的文件列表
  - [ ] 旧数据（该功能上线前的 turn）不显示文件变更行（`changedFiles` 为 null）

#### Task 4.3: 回归测试
- **目标**：确保新增功能不破坏现有功能
- **步骤**：
  1. 验证简洁模式现有功能正常：步骤数、TODO 列表、工具调用统计、最终回复、推理内容、撤销
  2. 验证明细模式不受影响
  3. 验证 Agent 编排场景不受影响
- **预期产出**：现有功能正常
- **验收标准**：
  - [ ] 简洁模式原有执行摘要项目正常显示
  - [ ] 明细模式消息列表正常
  - [ ] 撤销功能正常
  - [ ] 编排场景不受影响

## 风险与应对

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| 快照哈希为 None 时 diff 计算失败 | turn 完成后无法展示文件变更 | 在计算前做空值检查；加入 try/except，失败时 `changed_files = None` |
| 跨 step 的同一文件被反复修改，汇总不准确 | 文件变更统计不准确 | 方案设计为 turn_end 时全量计算（最早 vs 最晚快照），不依赖 step 级累加，从根本上解决 |
| 大量文件变更时 diff 计算耗时 | turn_end 消息延迟 | diff 计算是 git 内部操作（tree diff），通常很快；如有性能问题可加异步超时或缓存 |
| 旧数据（无 step_end messages 或无 turn_end message） | API 返回空 changed_files | 在 `get_turn_stats()` 中做 None 检查，旧数据返回空字典 |
| 三个前端样式不一致 | 用户体验不统一 | 统一设计规范：使用相同图标 `📁`、相同标签名 `变更文件`、相同颜色体系（绿=新增，红=删除，黄/橙=修改） |

## 已确认的约束

以下约束已在计划中固化：

- **不展示 step 级增量**：仅在 turn_end 时计算全量变更，不逐 step 累加展示。
- **不展示变更行数**：只展示文件级别的统计（新增/删除/修改了多少个文件），不展示增删行数。
- **无文件变更时不展示整项**：当 `changedFiles` 为 `null` 或所有计数均为 0 时，整行"📁 变更文件"不渲染。
- **变更文件详情默认折叠**：只显示统计数字，用户点击展开后展示详细文件列表。
