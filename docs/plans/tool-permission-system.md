# 工具权限系统设计方案

## 1. 概述

为工具执行系统新增 `permission` 字段，实现对每个工具的权限控制。权限值包括：

| 值 | 含义 | 说明 |
|---|---|---|
| `allow` | 允许（默认） | 直接执行，无需询问用户 |
| `ask` | 询问 | 每次执行前询问用户 |
| `forbidden` | 禁止 | 不执行，返回错误信息 |

当工具权限为 `ask` 时，询问用户并提供以下选项：

| 选项　　　　　　　　　| 说明　　　　　　　　　　　　　　　　　　　　　　　| granted | session_action |
| -----------------------| ---------------------------------------------------| ---------| ----------------|
| 单次允许　　　　　　　| 仅本次执行，后续仍会询问　　　　　　　　　　　　　| `true`  | `null`         |
| 当前 Session 都允许　 | 将权限临时提升为 `allow`，持续到 Session 结束　　 | `true`  | `"allow"`      |
| 单次不允许　　　　　　| 仅本次不执行，后续仍会询问　　　　　　　　　　　　| `false` | `null`         |
| 当前 Session 都不允许 | 将权限临时降级为 `forbidden`，持续到 Session 结束 | `false` | `"forbid"`     |

## 2. 涉及的文件

| 文件 | 变更类型 | 说明 |
|---|---|---|
| `configs/tool_permission_config.json` | **新建** | 默认权限配置文件 |
| `broca/tools/tool_permission_manager.py` | **新建** | 权限管理器模块 |
| `broca/permission_manager.py` | **修改** | 扩展支持 session 级决策 |
| `broca/agent.py` | **修改** | 初始化 ToolPermissionManager，传给 ExecutionEngine |
| `broca/execution_engine.py` | **修改** | `_process_tool_calls` 中集成权限检查 |
| `scripts/install.sh` | **修改** | 安装时复制配置文件 |
| `broca-web/frontend/src/stores/chat.ts` | **修改** | respondPermission 传 session_action |
| `broca-web/frontend/src/api/brocaSocket.ts` | **修改** | sendPermissionResponse 支持 session_action |
| `broca-web/frontend/src/components/PermissionDialog.vue` | **修改** | 显示4个选项按钮 |
| `broca-vscode/src/webview/src/stores/chat.ts` | **修改** | respondPermission 传 session_action |
| `broca-vscode/src/webview/src/components/PermissionDialog.vue` | **修改** | 显示4个选项按钮 |
| `broca-vscode/src/extension/chatWebView.ts` | **修改** | handlePermissionResponse 传 session_action |
| `broca-vscode/src/extension/socket.ts` | **修改** | sendPermissionResponse 支持 session_action |
| `broca-web/backend/app/...` | **可能修改** | 检查后端是否需要转发 session_action |

## 3. 详细设计

### 3.1 配置文件 `tool_permission_config.json`

```json
{
  "_description": "工具权限配置文件",
  "_permission_values": {
    "allow": "直接执行，无需询问",
    "ask": "每次执行前询问用户",
    "forbidden": "禁止执行"
  },
  "tools": {
    "read_file": "allow",
    "write_file": "ask",
    "edit_file": "ask",
    "glob": "allow",
    "grep": "allow",
    "list_dir": "allow",
    "tree_dir": "allow",
    "web_fetch": "allow",
    "web_search": "allow",
    "ask_user": "allow",
    "assign_task": "allow",
    "execute_code": "ask",
    "task_management": "allow",
    "todo_management": "allow",
    "cron": "ask",
    "memory": "allow",
    "load_skill": "allow",
    "blackboard_changes": "allow",
    "delete_blackboard": "ask",
    "list_blackboard": "allow",
    "read_blackboard": "allow",
    "write_blackboard": "ask"
  }
}
```

**加载规则（按顺序读，找到第一个就停止）：**
1. `{workspace}/.broca/tool_permission_config.json`（项目特有，优先级最高）
2. `~/.broca/configs/tool_permission_config.json`（全局默认）
3. 都不存在则全部使用默认值 `"allow"`

不再使用覆盖/合并的方式，简化加载逻辑。

### 3.2 ToolPermissionManager（新模块）

路径：`broca/tools/tool_permission_manager.py`

```python
class ToolPermissionManager:
    """
    负责加载配置、管理 session 覆盖权限。
    
    权限优先级（从高到低）：
    1. Session 级别覆盖（set_session_override）
    2. 配置文件中的默认权限
    3. 系统默认值 "allow"
    """
    
    def __init__(self, workspace: Optional[str] = None):
        self._default_permissions: Dict[str, str] = {}  # 从配置文件加载
        self._session_overrides: Dict[str, str] = {}     # 当前 session 的覆盖
    
    def _load_config(self, workspace: Optional[str] = None):
        """加载配置，按顺序读，找到第一个就停止"""
        # 1. 先检查 workspace/.broca/
        if workspace:
            workspace_config = Path(workspace) / ".broca" / "tool_permission_config.json"
            if workspace_config.exists():
                self._parse_config_file(workspace_config)
                return
        # 2. 再检查 ~/.broca/configs/
        global_config = Path.home() / ".broca" / "configs" / "tool_permission_config.json"
        if global_config.exists():
            self._parse_config_file(global_config)
            return
        # 3. 都不存在，使用空配置（全部默认为 "allow"）
    
    def get_permission(self, tool_name: str) -> str:
        """获取工具的有效权限值"""
        # 1. Session 覆盖优先
        if tool_name in self._session_overrides:
            return self._session_overrides[tool_name]
        # 2. 配置中的默认值
        return self._default_permissions.get(tool_name, "allow")
    
    def set_session_override(self, tool_name: str, permission: str):
        """设置 session 级别覆盖（allow 或 forbidden）"""
    
    def clear_session_overrides(self):
        """清除所有 session 覆盖（Agent reset 时调用）"""
```

### 3.3 PermissionManager 扩展

**重要设计原则：** 现有危险代码执行的权限请求流程保持不变（仅 Allow/Deny 两个选项）。新工具权限系统的 `ask` 流程才使用 4 选项对话框。

区分方式：在 `permission_request` 消息中增加 `request_type` 字段。

| 请求来源 | request_type | 前端对话框 |
|---|---|---|
| 现有 ask_user / 危险代码流程 | `"general"` | 2 选项：Allow / Deny |
| 新工具权限系统 (tool configured as "ask") | `"tool"` | 4 选项 |

**方法变更：**

```python
# 旧方法（保留，兼容现有流程）：返回 bool
async def request_permission(self, message: str) -> bool

# 新增方法（工具权限系统使用）：返回 (granted, session_action)
async def request_tool_permission(self, message: str) -> Tuple[bool, Optional[str]]
```

- `granted`: `True`（允许）/ `False`（不允许）
- `session_action`: `None`（仅本次）/ `"allow"`（当前 session 都允许）/ `"forbid"`（当前 session 都不允许）

**请求消息格式扩展（增加 `request_type` 字段）：**

```json
{
  "message_type": "permission_request",
  "data": {
    "message": "...",
    "request_type": "tool",       // "general"（默认，现有流程）| "tool"（工具权限）
    "request_id": "xxx"
  }
}
```

**响应消息格式扩展：**

```json
{
  "message_type": "permission_response",
  "data": {
    "granted": true,
    "session_action": "allow",   // null | "allow" | "forbid"（仅 request_type="tool" 时有效）
    "request_id": "xxx"
  }
}
```

**跟踪数据结构扩展：**

```python
self._permission_requests[request_id] = {
    "event": response_event,
    "granted": None,
    "session_action": None,    # 新增，仅 tool 权限请求使用
}
```

### 3.4 ExecutionEngine 集成

修改 `execution_engine.py` 的 `_process_tool_calls` 方法：

```python
async def _process_tool_calls(self, tool_calls: List[Any]):
    for tool_call in tool_calls:
        tool_name = tool_call.function.name
        
        # --- 新增：权限检查 ---
        permission = self.tool_permission_manager.get_permission(tool_name)
        if permission == "forbidden":
            tool_result = ToolResult(
                status=ToolStatus.ERROR,
                content=f"Tool {tool_name} is forbidden by permission settings"
            )
        elif permission == "ask":
            granted, session_action = await self.agent.ask_for_tool_permission(
                tool_name, tool_call.function.arguments
            )
            if not granted:
                tool_result = ToolResult(
                    status=ToolStatus.ERROR,
                    content=f"Tool {tool_name} execution denied by user"
                )
            else:
                tool_result = await asyncio.wait_for(
                    self.tool_mapping[tool_name].execute(arguments, context),
                    timeout=timeout,
                )
            
            # 处理 session 级别决策
            if session_action == "allow":
                self.tool_permission_manager.set_session_override(tool_name, "allow")
            elif session_action == "forbid":
                self.tool_permission_manager.set_session_override(tool_name, "forbidden")
        else:  # "allow"
            tool_result = await asyncio.wait_for(
                self.tool_mapping[tool_name].execute(arguments, context),
                timeout=timeout,
            )
```

**注意：** `ask` 分支中 `tool_result` 可能未定义（当用户拒绝时），但已赋值，无问题。

### 3.5 Agent 初始化变更

在 `agent.py` 中：

```python
def _setup_execution_engine(self):
    """Set up execution engine"""
    self.tool_permission_manager = ToolPermissionManager(
        workspace=self.config.workspace
    )
    self.execution_engine = ExecutionEngine(
        ...
        tool_permission_manager=self.tool_permission_manager,  # 新增参数
    )

# 原有方法 ask_for_permission 保持不动（用于现有危险代码流程，request_type="general"）
async def ask_for_permission(self, message: str) -> bool:
    """保留现有逻辑不变"""
    ...

# 新增方法（工具权限系统使用，request_type="tool"）
async def ask_for_tool_permission(self, tool_name: str, arguments: str) -> Tuple[bool, Optional[str]]:
    """询问用户工具执行权限，带 session 级别决策"""
    self.permission_manager.set_state(
        turn_id=self.turn_id,
        agent_id=self.agent_id,
        session_id=self.session_id,
    )
    message = f"Tool `{tool_name}` requires your permission.\nArguments: {arguments}"
    async with self.error_handler.handle_permission_request():
        return await self.permission_manager.request_tool_permission(message)
```

### 3.6 ExecutionEngine 新增属性

```python
class ExecutionEngine:
    def __init__(self, ..., tool_permission_manager=None):
        self.tool_permission_manager = tool_permission_manager or ToolPermissionManager()
```

并在 `reset` 时调用：

```python
def reset(self):
    self.tool_permission_manager.clear_session_overrides()
```

### 3.7 Install 脚本变更

在 `scripts/install.sh` 的配置复制部分，增加：

```bash
# ---- 复制 tool_permission_config.json ----
PERM_DST="$BROCA_HOME/configs/tool_permission_config.json"
PERM_SRC="$PROJECT_ROOT/configs/tool_permission_config.json"

if [[ ! -f "$PERM_DST" ]]; then
    if [[ -f "$PERM_SRC" ]]; then
        cp "$PERM_SRC" "$PERM_DST"
        info "已创建工具权限配置: $PERM_DST"
    else
        warn "未找到默认工具权限配置: $PERM_SRC"
    fi
else
    info "工具权限配置已存在: ${PERM_DST}（跳过）"
fi
```

### 3.8 broca-web 前端适配

**核心逻辑：** 根据 `request_type` 决定显示 2 选项还是 4 选项对话框。

- `request_type="general"`（默认，现有流程）：Allow / Deny 两个按钮
- `request_type="tool"`（工具权限系统）：4 个按钮

**brocaSocket.ts** — `sendPermissionResponse` 增加 `session_action` 参数：

```typescript
async sendPermissionResponse(params: {
    granted: boolean
    session_action?: string  // null | "allow" | "forbid"  ← 新增
    requestId?: string
    receiverId?: string
    subscription?: string
}): Promise<void> {
    // ...
    data: {
        granted: params.granted,
        session_action: params.session_action,  // ← 新增
        request_id: params.requestId,
    },
}
```

**chat.ts (store)** — 记录 `request_type`，`respondPermission` 增加 `sessionAction` 参数：

```typescript
// permissionDialog 状态扩展
const permissionDialog = reactive({
    visible: false,
    requestId: '' as string | undefined,
    senderId: '' as string | undefined,
    message: '',
    requestType: 'general' as string,  // ← 新增: "general" | "tool"
})

// 监听 permission_request 时记录 request_type
const unsubPermission = socketStore.onPermissionRequest('chat', (m: Message) => {
    permissionDialog.visible = true
    permissionDialog.requestId = m.data?.request_id
    permissionDialog.senderId = m.sender_id
    permissionDialog.message = m.data?.message || 'Permission required'
    permissionDialog.requestType = m.data?.request_type || 'general'  // ← 新增
})

// respondPermission 增加 sessionAction 参数
const respondPermission = async (granted: boolean, sessionAction?: string) => {
    await socketStore.respondPermission({
        granted,
        session_action: sessionAction,
        requestId: permissionDialog.requestId,
        receiverId: permissionDialog.senderId || '',
        subscription: sessionId.value ? String(sessionId.value) : undefined,
    })
    permissionDialog.visible = false
}
```

**PermissionDialog.vue** — 根据 `requestType` 显示不同按钮：

```vue
<script setup lang="ts">
import { useChatStore } from '@/stores'
import { computed } from 'vue'

const chatStore = useChatStore()
const isToolPermission = computed(() => chatStore.permissionDialog.requestType === 'tool')
</script>

<template>
  <el-dialog
    v-model="chatStore.permissionDialog.visible"
    :title="isToolPermission ? 'Tool Permission Request' : 'Permission Request'"
    :width="chatStore.isMobile ? '90%' : '520px'"
    :close-on-click-modal="false"
  >
    <div class="flex items-start gap-3">
      <div class="text-3xl">{{ isToolPermission ? '🔧' : '🔐' }}</div>
      <div class="text-sm text-gray-700 whitespace-pre-wrap flex-1">
        {{ chatStore.permissionDialog.message }}
      </div>
    </div>
    <template #footer>
      <!-- 工具权限：4 选项 -->
      <template v-if="isToolPermission">
        <el-button @click="chatStore.respondPermission(false, 'forbid')">
          🔒 当前Session都不允许
        </el-button>
        <el-button @click="chatStore.respondPermission(false)">
          ❌ 单次不允许
        </el-button>
        <el-button @click="chatStore.respondPermission(true)">
          ✅ 单次允许
        </el-button>
        <el-button type="primary" @click="chatStore.respondPermission(true, 'allow')">
          🔓 当前Session都允许
        </el-button>
      </template>
      <!-- 通用权限：2 选项（现有流程） -->
      <template v-else>
        <el-button @click="chatStore.respondPermission(false)"> Deny </el-button>
        <el-button type="primary" @click="chatStore.respondPermission(true)"> Allow </el-button>
      </template>
    </template>
  </el-dialog>
</template>
```

### 3.9 broca-vscode 前端适配

**socket.ts (extension)** — `sendPermissionResponse` 增加 `session_action`：

```typescript
async sendPermissionResponse(params: {
    granted: boolean
    session_action?: string  // ← 新增
    requestId?: string
    receiverId?: string
    subscription?: string
}): Promise<void> {
    // ...
    data: {
        granted: params.granted,
        session_action: params.session_action,  // ← 新增
        request_id: params.requestId,
    },
}
```

**chatWebView.ts (extension)** — 转发 `session_action`：

```typescript
private async handlePermissionResponse(
    sessionId: string,
    payload: { granted: boolean; session_action?: string; requestId?: string; receiverId?: string }
) {
    await socketClient.sendPermissionResponse({
        granted: payload.granted,
        session_action: payload.session_action,  // ← 新增
        requestId: payload.requestId,
        receiverId: payload.receiverId,
        subscription: sessionId,
    })
}
```

**chat.ts (webview store)** — 记录 `requestType`，`respondPermission` 增加 `sessionAction`：

```typescript
// permissionDialog 状态扩展
const permissionDialog = ref({
    visible: false,
    requestId: '' as string | undefined,
    senderId: '' as string | undefined,
    message: '',
    requestType: 'general' as string,  // ← 新增
})

// 监听 permission_request 时记录 request_type
if (message.message_type === 'permission_request') {
    permissionDialog.value = {
        visible: true,
        requestId: message.data?.request_id,
        senderId: message.sender_id,
        message: message.data?.message || 'Permission required',
        requestType: message.data?.request_type || 'general',  // ← 新增
    }
    return
}

// respondPermission 增加 sessionAction 参数
function respondPermission(granted: boolean, sessionAction?: string) {
    postMessage({
        type: 'respondPermission',
        payload: {
            granted,
            session_action: sessionAction,  // ← 新增
            requestId: permissionDialog.value.requestId,
            receiverId: permissionDialog.value.senderId,
        },
    })
    permissionDialog.value.visible = false
}
```

**PermissionDialog.vue (webview)** — 根据 `requestType` 显示不同按钮：

```vue
<script setup lang="ts">
import { useChatStore } from '../stores/chat'
import { computed } from 'vue'

const chatStore = useChatStore()
const isToolPermission = computed(() => chatStore.permissionDialog.requestType === 'tool')
</script>

<template>
  <Teleport to="body">
    <div v-if="chatStore.permissionDialog.visible" class="dialog-overlay">
      <div class="dialog-container">
        <div class="dialog-header">
          <span class="dialog-icon">{{ isToolPermission ? '🔧' : '🔒' }}</span>
          <span class="dialog-title">{{ isToolPermission ? 'Tool Permission' : 'Permission Required' }}</span>
        </div>
        <div class="dialog-body">
          <p>{{ chatStore.permissionDialog.message }}</p>
        </div>
        <div class="dialog-footer">
          <!-- 工具权限：4 选项 -->
          <template v-if="isToolPermission">
            <button class="btn btn-secondary" @click="chatStore.respondPermission(false, 'forbid')">
              🔒 Always Deny
            </button>
            <button class="btn btn-secondary" @click="chatStore.respondPermission(false)">
              ❌ Deny Once
            </button>
            <button class="btn btn-primary" @click="chatStore.respondPermission(true)">
              ✅ Allow Once
            </button>
            <button class="btn btn-primary" @click="chatStore.respondPermission(true, 'allow')">
              🔓 Always Allow
            </button>
          </template>
          <!-- 通用权限：2 选项 -->
          <template v-else>
            <button class="btn btn-secondary" @click="chatStore.respondPermission(false)">
              Deny
            </button>
            <button class="btn btn-primary" @click="chatStore.respondPermission(true)">
              Allow
            </button>
          </template>
        </div>
      </div>
    </div>
  </Teleport>
</template>
```

## 4. 数据流

### 4.1 工具权限系统（新流程，request_type="tool"）

```
LLM 返回 tool_calls
        │
        ▼
ExecutionEngine._process_tool_calls()
        │
        ├─▶ ToolPermissionManager.get_permission(tool_name)
        │       │
        │       ├─ "forbidden" ──▶ 返回错误 ToolResult
        │       │
        │       ├─ "ask" ──▶ Agent.ask_for_tool_permission()
        │       │                │
        │       │                ▼
        │       │       PermissionManager.request_tool_permission()
        │       │         (request_type="tool")
        │       │                │
        │       │                ▼  (Socket.IO: permission_request)
        │       │       PermissionDialog.vue
        │       │       (检测 request_type="tool" → 显示4选项)
        │       │                │
        │       │                ├─ "单次允许"      → (true, null)         → 执行
        │       │                ├─ "Session都允许"  → (true, "allow")      → 执行 + session覆盖
        │       │                ├─ "单次不允许"     → (false, null)        → 拒绝
        │       │                └─ "Session都不允许" → (false, "forbid")   → 拒绝 + session覆盖
        │       │
        │       └─ "allow" ──▶ 直接执行
        │
        ▼
    执行工具，保存结果
```

### 4.2 现有危险代码流程（保留，request_type="general"）

```
Agent 逻辑中调用 ask_for_permission()
        │
        ▼
PermissionManager.request_permission()
  (request_type="general"，默认)
        │
        ▼  (Socket.IO: permission_request)
PermissionDialog.vue
(检测 request_type="general" → 显示2选项: Allow / Deny)
        │
        ├─ Allow  → 继续执行
        └─ Deny   → 跳过
```

## 5. 恢复与清理

| 事件 | 行为 |
|---|---|
| Agent reset | `tool_permission_manager.clear_session_overrides()` |
| Session 结束 | session_overrides 自动丢失（不持久化） |
| Agent 重启 | session_overrides 自动丢失 |
