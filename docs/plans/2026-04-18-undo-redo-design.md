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

核心思想：使用独立的 Git 仓库存储文件系统快照，通过记录文件变更差份（patch）实现精确撤销和重做。

---

## 设计目标

1. **支持两个撤销层级**：
   - Turn 级别：一个 turn 内的所有 tool calls 一起撤销
   - Tool Call 级别：单个 tool call 单独撤销，精确到单个文件操作

2. **通过 Command 消息触发**：接收 `undo`/`redo` 命令消息执行撤销/重做

3. **基于 Git 实现**：使用独立的 Git 仓库存储快照，与项目 `.git` 完全隔离

4. **零干扰**：对用户项目不产生任何副作用

---

## 技术架构

### 系统架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    SessionRevert 服务                       │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐ │
│  │  undo()     │    │  redo()     │    │  cleanup()  │ │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘ │
└─────────┼──────────────────┼──────────────────┼──────────┘
          │                  │                  │
          └──────────────────┼──────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                    Snapshot 服务                            │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐   │
│  │   track()    │    │   patch()    │    │  restore()   │   │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘ │
└─────────┼──────────────────┼──────────────────┼──────────┘
          │                  │                  │
          └──────────────────┼──────────────────┘
                             ▼
         ┌─────────────────────────────────────┐
         │     独立 Git 仓库 (隔离于项目)        │
         │  ~/.local/share/broca/snapshot/      │
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

**仓库位置**：`~/.local/share/broca/snapshot/{session_id}/`

| 组件 | 说明 |
|------|------|
| `~/.local/share/broca` | XDG 数据目录 |
| `snapshot` | 快照子目录 |
| `{session_id}` | 会话唯一标识 |

**初始化**（首次调用 `track()` 时）：
```bash
# 初始化空仓库
git init

# 配置 Git 选项
git config core.autocrlf false
git config core.longpaths true
git config core.symlinks true
git config core.fsmonitor false
```

通过环境变量实现隔离：
```bash
GIT_DIR=/path/to/snapshot/repo/.git
GIT_WORK_TREE=/path/to/project/root
```

#### 1.2 快照捕获 (track)

**触发时机**：
- Turn 开始时（`start_turn`）
- Turn 结束时（`end_turn`）

**执行流程**：
1. 获取并发锁（信号量）
2. 检查启用状态
3. 同步忽略规则（`.gitignore`）
4. 发现变更文件（`diff-files` + `ls-files`）
5. 过滤忽略文件（`check-ignore`）
6. 过滤大文件（> 2MB）
7. 暂存变更文件（`git add --all --sparse`）
8. 写入 Git 树（`git write-tree`）
9. 返回树哈希

**关键 Git 命令**：
```bash
# 发现已跟踪且修改的文件
git diff-files --name-only -z -- .

# 发现未跟踪的新文件
git ls-files --others --exclude-standard -z -- .

# 暂存所有变更
git add --all --sparse --pathspec-from-file=- --pathspec-file-nul

# 写入树对象
git write-tree
```

#### 1.3 Patch 计算 (patch)

**计算时机**：Turn 结束时

**输入**：起始快照哈希

**输出**：
```python
{
    "hash": "起始快照的Git树哈希",
    "files": ["变更文件的相对路径列表"]
}
```

**关键 Git 命令**：
```bash
# 对比两次快照的差异
git diff --cached --no-ext-diff --name-only <起始哈希> -- .
```

#### 1.4 快照恢复 (restore)

**用途**：撤销操作时恢复到指定快照

**关键 Git 命令**：
```bash
# 读取树到索引
git read-tree <树哈希>

# 检出到工作树
git checkout-index -a -f
```

### 2. SessionRevert 服务

#### 2.1 撤销 (undo)

**输入**：
```python
{
    "session_id": str,
    "turn_id": Optional[str],  # 可选，指定撤销到的turn
    "level": str              # "turn" 或 "tool_call"
}
```

**执行流程**：
1. 验证会话状态（确保非忙碌）
2. 获取所有消息
3. 收集 Patch（从锚点开始向后）
4. 捕获当前快照
5. 恢复到回滚前的快照（`snapshot.restore`）
6. 应用反向 Patch（从起始快照恢复文件）
7. 计算差异（用于UI展示）
8. 保存回滚元数据

#### 2.2 重做 (redo)

**输入**：
```python
{
    "session_id": str
}
```

**执行流程**：
1. 验证会话状态
2. 检查回滚元数据
3. 恢复到撤销时的快照
4. 清除回滚元数据

---

## 撤销/重做流程

### Turn 级别撤销

```
Turn 1: 用户请求 → tool_call_1 → tool_call_2 → tool_call_3
Turn 2: undo 命令
       ↓
1. 捕获当前快照（Turn 2 开始前的状态）
2. 从 Turn 1 的 patch 中恢复文件
3. 保存撤销元数据（包含快照哈希）
```

### Tool Call 级别撤销

```
Turn 1: tool_call_1(edit_file) → tool_call_2(read_file) → tool_call_3(write_file)
                                                                      ↓
undo(tool_call=tool_call_3)
       ↓
1. 找到 tool_call_3 的 patch
2. 从快照中恢���该文件的原始状态
3. 保存撤销元数据
```

### 重做流程

```
Turn 1: undo 命令 → 恢复到 Turn 1 开始前的状态
Turn 2: redo 命令
       ↓
1. 读取撤销元数据中的快照哈希
2. 恢复到撤销时的快照状态
3. 清除撤销元数据
```

---

## 数据模型

### Session 模型扩展

```python
class SessionRevertInfo(BaseModel):
    """撤销/重做元信息"""
    turn_id: str                    # 撤销到的turn ID
    turn_level: str                 # "turn" 或 "tool_call"
    snapshot: str                 # 撤销时的快照哈希
    patch_files: List[str]         # 撤销的文件列表
    diff: str                     # 差异内容（unified diff格式）
    reverted_at: datetime          # 撤销时间


class Session(BaseModel):
    # ... 现有字段 ...
    revert: Optional[SessionRevertInfo] = None
```

### Message 模型扩展

```python
class PatchPart(BaseModel):
    """Patch 部分"""
    patch_hash: str                 # 起始快照的 Git 树哈希
    files: List[str]             # 变更文件的相对路径列表
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

### 提供的 Functions

为 LLM 提供的工具函数：

```python
class Undo(Tool):
    name = "undo"
    description = "撤销上一次的修改操作"

    parameters = {
        "type": "object",
        "properties": {
            "level": {
                "type": "string",
                "enum": ["turn", "tool_call"],
                "description": "撤销层级"
            }
        }
    }


class Redo(Tool):
    name = "redo"
    description = "重做被撤销的修改操作"
```

---

## 实现计划

### 阶段 1：基础架构

1. 创建 `broca/snapshot/` 模块
   - `snapshot/git_manager.py` - Git 仓库管理
   - `snapshot/track.py` - 快照捕获
   - `snapshot/patch.py` - Patch 计算
   - `snapshot/restore.py` - 快照恢复

2. 创建 `broca/session/revert_service.py` - 撤销/重做服务

### 阶段 2：集成

1. 在 `ExecutionEngine` 中集成快照捕获
2. 在 `SessionManager` 中保存 patch 信息
3. 添加 command 消息处理

### 阶段 3：工具函数

1. 添加 `undo`/`redo` 工具函数
2. 更新 TUI 支持（如需要）

### 阶段 4：优化

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

---

## 参考资料

- [packages/opencode 撤销/重做技术文档](../../undo_redo_tech.md)