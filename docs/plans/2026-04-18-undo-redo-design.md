# Undo/Redo 功能技术设计文档

## 目录
1. [概述](#概述)
2. [设计目标](#设计目标)
3. [技术架构](#技术架构)
4. [核心组件设计](#核心组件设计)
5. [撤销/重做流程](#撤销重做流程)
6. [数据模型](#数据模型)
7. [API 设计](#api-设计)
8. [实现计划](#实现计划)

---

## 概述

本文档描述 Broca Agent 系统的撤销/重做功能设计方案。方案参考 packages/opencode 的技术实现，针对 Broca 的 Python 技术栈进行适配。

核心思想：使用独立的 Git 仓库存储文件系统快照，通过记录文件变更差份（patch）实现精确撤销和重做。Step 开始时记录 snapshot hash，Step 结束时记录 patch，撤销/重做操作复用 COMMAND 消息。

---

## 设计目标

1. **支持两个撤销层级**：
   - Turn 级别：一个 turn 内的所有 step 一起撤销
   - Step 级别：一次 LLM 调用的所有 tool calls 一起撤销

2. **通过 Command 消息触发**：接收 `undo`/`redo` 命令消息执行撤销/重做

3. **基于 Git 实现**：使用独立的 Git 仓库存储快照，与项目 `.git` 完全隔离

4. **零干扰**：对用户项目git不产生任何副作用

---

## 技术架构

### 系统架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    SessionRevert 服务                        │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │  undo()     │    │  redo()     │    │  cleanup()  │  │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘  │
└─────────┼──────────────────┼──────────────────┼───────────┘
          │                  │                  │
          └──────────────────┼──────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                    Snapshot 服务                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │   track()    │    │   patch()    │    │  restore()   │  │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘  │
└─────────┼──────────────────┼──────────────────┼───────────┘
          │                  │                  │
          └──────────────────┼──────────────────┘
                             ▼
          ┌─────────────────────────────────────┐
          │     独立 Git 仓库 (隔离于项目)        │
          │  ~/.local/share/broca/snapshot/     │
          └─────────────────────────────────────┘
```

### 数据流

```
用户操作 → ExecutionEngine 处理 → 捕获快照 → 生成 Patch → 持久化到数据库
                                                      ↓
                                                   撤销时读取
                                                      ↓
                                                   应用反向 Patch
```

---

## 核心组件设计

### 1. Snapshot 服务

#### 1.1 独立 Git 仓库管理

**仓库位置**：`~/.local/share/broca/snapshot/{hash(workspace)}/`

| 组件 | 说明 |
|------|------|
| `~/.local/share/broca` | XDG 数据目录 |
| `snapshot` | 快照子目录 |
| `hash(workspace}` | 工作区哈希 |

**初始化**（首次调用 `track()` 时）：
```bash
git init

git config core.autocrlf false
git config core.longpaths true
git config core.symlinks true
git config core.fsmonitor false
```

实现隔离：
```bash
GIT_DIR=/path/to/snapshot/repo/.git
GIT_WORK_TREE=/path/to/workspace
```

#### 1.2 快照捕获 (track)

**触发时机**：Step 开始时和 Step 结束时

**执行流程**：
1. 获取并发锁（信号量）
3. 同步忽略规则（`.gitignore`）
4. 发现变更文件（`diff-files` + `ls-files`）
5. 过滤忽略文件（`check-ignore`）
6. 过滤大文件（> 2MB）
7. 暂存变更文件（`git add --all --sparse`）
8. 写入 Git 树（`git write-tree`）
9. 返回树哈希

**优化：如果当前 Step 的所有 Tool Call 都是只读类型（不修改文件），跳过快照生成**

只读 Tool Call 包括但不限于：
- `file_read` - 读取文件内容
- `glob` - 搜索文件
- `grep` - 搜索文件内容
- `list_dir` - 列出目录内容
- `tree_dir` - 列出目录树
- `web_fetch` / `web_search`  - 网络请求

**关键 Git 命令**：
```bash
git diff-files --name-only -z -- .
git ls-files --others --exclude-standard -z -- .
git add --all --sparse --pathspec-from-file=- --pathspec-file-nul
git write-tree
```

#### 1.3 Patch 计算 (patch)

**计算时机**：Step 结束时

**输出**：
```python
{
    "hash": "起始快照的Git树哈希",
    "files": ["变更文件的相对路径列表"]
}
```

**关键 Git 命令**：
```bash
git diff --cached --no-ext-diff --name-only <起始哈希> -- .
```

#### 1.4 快照恢复 (restore)

**用途**：撤销操作时恢复到指定快照

**关键 Git 命令**：
```bash
git read-tree <树哈希>
git checkout-index -a -f
```

### 2. SessionRevert 服务

#### 2.1 撤销 (undo)

**输入**：
```python
{
    "session_id": str,
    "target_message_id": Optional[str],  # 可选，指定撤销到的消息 ID
    "level": str                       # "turn" 或 "step"
}
```

**执行流程**：
1. 验证会话状态（确保非忙碌）
2. 获取所有消息（按 sequence_number 排序）
3. 收集 Patch（从锚点 step 开始向后）
4. 捕获当前快照（用于重做）
5. 恢复到撤销目标前的快照（`snapshot.restore`）
6. 应用反向 Patch（从各起始快照恢复文件）
7. 计算差异（unified diff 格式）
8. 标记消息为已撤销（reverted=true）
9. **保存撤销记录**：插入 COMMAND 消息（command=undo），包含 diff 数据
10. **重建 Context**：重新调用 `build_history_from_session()`

#### 2.2 重做 (redo)

**执行流程**：
1. 验证会话状态
2. 检查最新的撤销记录（COMMAND 消息，command=undo）
3. 从撤销记录的 snapshot 恢复快照
4. 标记消息为已重做（reverted=false）
5. **保存重做记录**：插入 COMMAND 消息（command=redo）记录重做操作
6. **重建 Context**：重新调用 `build_history_from_session()`

---

## 撤销/重做流程

### Turn 级别撤销

```
Turn 1: 用户请求 → LLM调用1 → tool_call_1 → tool_call_2
                    LLM调用2 → tool_call_3 → tool_call_4
Turn 2: undo 命令
       ↓
1. 捕获当前快照（Turn 2 开始前的状态）
2. 从 Turn 1 的所有 patch 中恢复文件
3. 计算差异
4. 插入 COMMAND 消息（command=undo，包含 diff 数据）
5. 调用 build_history_from_session()
```

### Step 级别撤销

```
Turn 1: LLM调用1 → tool_call_1 → tool_call_2
        LLM调用2 → tool_call_3 → tool_call_4
                              ↓
undo(level=step)
       ↓
1. 找到 LLM调用2 的 STEP_END 消息
2. 从快照中恢复该次调用的所有文件
3. 计算差异
4. 插入 COMMAND 消息（command=undo）
5. 调用 build_history_from_session()
```

### 重做流程

```
Turn 1: undo 命令 → 恢复到 Turn 1 开始前的状态
Turn 2: redo 命令
       ↓
1. 读取最新撤销记录（COMMAND 消息，command=undo）的 snapshot hash
2. 恢复到撤销时的快照状态
3. 插入 COMMAND 消息（command=redo）
4. 调用 build_history_from_session()
```

### Context 消息处理

MessageService的get_messages_by_session和get_messages_by_agent方法增加忽略已撤销消息的逻辑

```python
async def get_messages_by_session(
        self, session_id: str, order_by="sequence_number", skip=None, limit=None, ignore_reverted=True
    ) -> List[Message]:
        """根据会话ID获取消息"""
        filters = {"session_id": session_id}
        if ignore_reverted:
            filters["reverted"] = False
        return await self.get_batch(
            filters=filters,
            order_by=order_by,
            skip=skip,
            limit=limit,
        )

    async def get_messages_by_agent(self, agent_id: str, ignore_reverted=True) -> List[Message]:
        """根据Agent ID获取消息"""
        filters = {"agent_id": agent_id}
        if ignore_reverted:
            filters["reverted"] = False
        return await self.get_batch(
            filters=filters, order_by="sequence_number"
        )
```

每次撤销/重做后重新构建历史

```python
async def build_history_from_session(
    self, 
    session_manager: SessionManager, 
    agent_id: str,
    rebuild=False
) -> None:
    if rebuild:
        self._history = [{"role": "system", "content": self.system_prompt}]
    # ... 现有逻辑 ...
```

---

## 数据模型

### Message 模型扩展

添加 `STEP_START` 和 `STEP_END` 消息类型，用于记录 Step 级别的快照和 patch。

```python
class MessageType(str, Enum):
    # ... 现有类型 ...
    STEP_START = "step_start"    # Step 开始，记录 snapshot hash
    STEP_END = "step_end"        # Step 结束，记录 snapshot hash和patch
```

```python
class Message(SQLModel, table=True):
    # ... 现有字段 ...
    reverted : bool = False      # 是否已回滚
```


**STEP_START 消息 data 结构**：
```python
{
    "step_id": "step-1",                    # Step ID
    "snapshot_hash": "abc123...",           # Step 开始时的快照哈希
}
```

**STEP_END 消息 data 结构**：
```python
{
    "step_id": "step-1",                    # Step ID
    "snapshot_hash": "def456...",     # Step 结束的快照哈希
    "patch": {
        "snapshot_hash": "abc123...",        # 起始快照的 Git 树哈希
        "files": ["src/app.ts", "src/utils.ts"]  # 变更文件列表
    }
}
```

### 撤销/重做消息

撤销/重做操作复用 `COMMAND` 消息类型：

```python
# COMMAND 消息 data 结构
{
    "command": "undo",                      # 命令类型：undo/redo
    "level": "turn",                        # 撤销级别：turn/step
    "target_step_id": "step-1",            # 撤销目标 Step ID
    "snapshot_hash": "abc123...",           # 撤销时的快照哈希
    "diff": "diff --git a/...",             # 差异内容（unified diff格式）
    "diff_summary": {                       # 差异统计
        "total_files": 3,
        "total_additions": 10,
        "total_deletions": 5,
        "files_added": ["a.txt"],
        "files_deleted": ["b.txt"],
        "files_modified": ["c.txt"]
    }
}
```

### Diff 计算

使用 Git 命令计算差异：
```bash
git diff --cached --no-ext-diff --unified=3 <起始哈希> -- .
```

---

## API 设计

### Command 消息处理

在 `Agent._on_command()` 中添加 undo/redo 命令处理：

```python
async def _on_command(self, message: Message):
    command = message.data.get("command")

    if command == "undo":
        await self._handle_undo(message)
    elif command == "redo":
        await self._handle_redo(message)
```

---

## 实现计划

### 阶段 1：基础架构

1. 创建 `broca/snapshot/` 模块
   - `snapshot/git_manager.py` - Git 仓库管理, 使用GitPython
   - `snapshot/track.py` - 快照捕获
   - `snapshot/patch.py` - Patch 计算
   - `snapshot/restore.py` - 快照恢复

2. 创建 `broca/session/revert_service.py` - 撤销/重做服务

### 阶段 2：集成

1. 在 `ExecutionEngine` 中集成快照捕获（STEP_START / STEP_END）
2. 在 `SessionManager` 中保存 patch 信息（STEP_END）
3. 添加 command 消息处理（undo/redo）
4. 添加 `STEP_START` / `STEP_END` 消息类型


### 阶段 3：优化

1. 并发控制优化
2. 垃圾回收实现
3. 错误处理完善

---

## 关键设计决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 仓库位置 | `~/.local/share/broca/snapshot/` | 遵循 XDG 规范 |
| 并发控制 | 信号量 | 确保操作串行化 |
| 大文件阈值 | 2MB | 平衡存储和时间 |
| 忽略规则同步 | `.gitignore` + `info/exclude` | 保持一致性 |
| 稀疏检出 | 启用 | 提升性能 |
| Step 记录 | STEP_START / STEP_END 消息 | 记录 snapshot hash 和 patch |
| 撤销记录 | COMMAND 消息（command=undo/redo） | 复用现有消息类型 |
| Diff 存储 | COMMAND 消息的 data 字段 | 便于 UI 展示和历史查询 |

---

## 参考资料

- [packages/opencode 撤销/重做技术文档](../../undo_redo_tech.md)
