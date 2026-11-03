# Read Image Tool — 计划

## 概述
- **目标**：为 broca 模块新增 `read_image` 内置工具，该工具读取指定本地图像文件，上传到云端 S3 存储，并在 context 中注入一条包含图片内容的 user message，使 LLM 能够"看到"图片。
- **背景**：当前前端通过 `@aws-sdk/client-s3` 上传图片到 Cloudflare R2 / Supabase Storage，Python 后端没有任何 S3 上传能力。用户消息中的图片由前端上传后以 URL 形式传入，LLM 通过 `parse_message()` 将图片 URL 转为 `image_url` 格式。现在需要让 agent 在执行过程中也能主动"读图"。
- **约束条件**：
  - 复用 `StorageConfig`（`broca/configs.py`）中已有的云端存储配置（Cloudflare R2 / Supabase）
  - 图片 URL 格式必须与前端上传一致（`parse_message` 中 `file_type.startswith("image")` → `{"type": "image_url", "image_url": {"url": ...}}`）
  - 不能破坏现有 LLM 消息序列（OpenAI API 要求 `assistant(tool_calls) → tool(result)` 顺序不可被 user message 打断）

## 相关材料

| 材料 | 路径/说明 |
|------|-----------|
| Tool 基类（name/description/parameters/_execute/ToolResult/ToolCallContext） | `broca/tools/tool.py` |
| 现有工具示例（WebFetch/WebSearch） | `broca/tools/web.py` |
| 执行引擎（工具执行 + process_tool_call_result + context 注入） | `broca/loop_engine.py` |
| Context（add_message / history / build_history_from_session） | `broca/context.py` |
| LLMClient（parse_message 多模态消息构造） | `broca/llm.py` |
| Agent（访问 context / session_manager / llm_client / turn_id） | `broca/agent.py` |
| SessionManager（save_message / save_tool_call） | `broca/session/session_manager.py` |
| StorageConfig（cloudflare/supabase 存储配置） | `broca/configs.py` |
| ToolManager（READONLY_TOOLS 集合 / 自动发现） | `broca/tools/tool_manager.py` |
| 前端 S3 上传参考（buildS3Config + uploadFile） | `broca-web/frontend/src/utils/upload.ts` |
| pyproject.toml（依赖声明） | `pyproject.toml` |

## 总体方案

### 核心挑战：消息序列约束

OpenAI 兼容 API 要求 `assistant(tool_calls)` 后面紧跟 `tool(result)` 消息，不能插入 `user` 消息。工具在 `_execute()` 阶段执行，此时 tool result 尚未加入 context。如果 `_execute` 中直接 `context.add_message(user_image_msg)`，会在 tool_call 和 tool_result 之间插入 user message，导致下一轮 LLM 调用失败。

### 解决方案：ToolResult.extra_context_messages

1. **扩展 `ToolResult`**：新增 `extra_context_messages` 字段（`list[dict]`），工具可在返回结果时附带需要注入 context 的额外消息。
2. **修改 `process_tool_call_result`**：在保存 tool result 到 DB 并加入 context 之后，遍历 `extra_context_messages`，逐条保存到 DB 并注入 context。
3. **ReadImage 工具**：成功上传后，构造 `{"role": "user", "content": [{"type": "image_url", ...}, {"type": "text", ...}]}` 格式的 LLM 消息，放入 `ToolResult.extra_context_messages` 返回。
4. **云端上传**：新增 `boto3` 依赖，使用 `asyncio.to_thread()` 包装同步 S3 上传，根据 `StorageConfig.backend` 选择 Cloudflare R2 或 Supabase 端点。

### 消息注入时序

```
context.history 最终顺序：
[... existing ...]
assistant: {tool_calls: [read_image("path/to/img.png")]}
tool:      "图片已上传至云端: https://..."
user:      [{"type": "image_url", "image_url": {"url": "https://..."}}, {"type": "text", "text": "Image: img.png"}]
assistant: (下一轮 LLM 响应，此时可以"看到"图片)
```

## 执行计划

### Phase 1: 实现 read_image 工具

**目标**：完成 read_image 工具的全链路实现，包括基础设施扩展、工具核心逻辑、注册集成和测试验证。

**阶段验收标准**：
- [ ] `read_image` 工具可被 agent 调用，成功将本地图像上传到云端
- [ ] 上传成功后，context 中正确注入 user 角色、包含 `image_url` 的多模态消息
- [ ] 上传失败（存储未配置 / 文件不存在 / 网络错误）时，工具返回友好提示，不注入图片消息
- [ ] 消息序列顺序符合 OpenAI API 要求（tool result 在 user image message 之前）
- [ ] 会话恢复（`build_history_from_session`）时，注入的图片消息能正确重建
- [ ] `read_image` 加入 READONLY_TOOLS，不触发权限检查
- [ ] `boto3` 成功安装并可正常工作

---

#### Task 1.1: 扩展基础设施（boto3 依赖 + ToolResult + LoopEngine）

- **目标**：为工具实现做好基础设施准备——添加 boto3 依赖，扩展 ToolResult 支持 extra_context_messages，修改 LoopEngine 的 process_tool_call_result 处理额外消息
- **步骤**：
  1. 在 `pyproject.toml` 的 `dependencies` 列表中新增 `"boto3 (>=1.35.0,<2.0.0)"`
  2. 修改 `broca/tools/tool.py` 中的 `ToolResult` 类：
     - 新增 `extra_context_messages: list[dict]` 字段（默认空列表）
     - 每个 dict 结构：`{"llm_message": dict, "data": dict, "role": str}`
       - `llm_message`: LLM API 格式的消息（如 `{"role": "user", "content": [...]}`），将加入 context.history
       - `data`: 数据库 `data` 字段内容（如 `{"content": "...", "files": [...]}`）
       - `role`: 消息角色（如 `"user"`），用于 DB 存储
     - `to_dict()` 方法中不包含 `extra_context_messages`（它不参与 tool result 的序列化）
  3. 修改 `broca/loop_engine.py` 的 `process_tool_call_result()` 方法：
     - 在现有的 tool result 保存到 DB + 加入 context 之后，新增逻辑：遍历 `tool_result.extra_context_messages`
     - 对每条 extra message：生成 `message_id`，调用 `session_manager.save_message()` 保存到 DB，调用 `context.add_message(llm_message, message_id)` 加入 context
     - 如果 `config.interactive`，通过 `communicator` 广播新消息到前端（参考 `_broadcast_user_message` 的模式）
- **预期产出**：
  - `pyproject.toml` 新增 boto3 依赖
  - `broca/tools/tool.py` — ToolResult 扩展
  - `broca/loop_engine.py` — process_tool_call_result 处理 extra messages
- **验收标准**：
  - [ ] `ToolResult(status=ToolStatus.SUCCESS, content="test")` 仍可正常创建（向后兼容，`extra_context_messages` 默认为空）
  - [ ] `ToolResult(status=ToolStatus.SUCCESS, content="ok", extra_context_messages=[{"llm_message": {"role": "user", "content": "hi"}, "data": {"content": "hi"}, "role": "user"}])` 创建成功
  - [ ] `process_tool_call_result` 在处理完 tool result 后，将 extra messages 逐条保存到 DB 并加入 context.history
  - [ ] 现有所有工具的 `process_tool_call_result` 行为不变（extra_context_messages 为空时跳过）
  - [ ] `poetry install` 或 `pip install boto3` 后 `import boto3` 成功

---

#### Task 1.2: 实现 ReadImage 工具核心逻辑

- **目标**：创建 `broca/tools/image.py`，实现 `ReadImage` 工具，完成"读图 → 云端上传 → 注入 context"的完整流程
- **步骤**：
  1. 创建文件 `broca/tools/image.py`，实现 `ReadImage(Tool)` 类
  2. **Tool 元信息**：
     - `name` → `"read_image"`
     - `description` → 描述用途（读取本地图像文件，上传到云端供 LLM 查看）
     - `parameters` → `{"type": "object", "properties": {"file_path": {"type": "string", "description": "The absolute or workspace-relative path to the image file"}}, "required": ["file_path"]}`
  3. **`_execute()` 主逻辑**（按顺序）：
     1. **校验文件**：检查 `file_path` 是否存在（支持绝对路径和 workspace 相对路径），检查文件扩展名是否为图片格式（`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.bmp`, `.svg`）
     2. **校验存储配置**：通过 `get_configs().storage` 获取 `StorageConfig`，检查 `backend` 是否为 `"cloudflare"` 或 `"supabase"`，未配置则返回 `ToolResult(ERROR, "提示：云端存储未配置...")`
     3. **获取 MIME 类型**：使用 `mimetypes.guess_type(file_path)` 获取
     4. **创建 S3 客户端**（`asyncio.to_thread` 包装）：根据 `StorageConfig` 构建 boto3 S3 client
        - Cloudflare R2：endpoint=`https://{account_id}.r2.cloudflarestorage.com`，credentials 从 config 取
        - Supabase：endpoint=`{supabase_url}/storage/v1/s3`，credentials 从 config 取
        - 参考 `broca-web/frontend/src/utils/upload.ts` 中的 `buildS3Config` 逻辑
     5. **生成存储路径**：`uploads/YYYYMMDD/{encoded_filename}_{uuid6}.ext`（与前端 `generateStoragePath` 一致）
     6. **上传**（`asyncio.to_thread` 包装 `s3_client.upload_file`）
     7. **构造 public URL**：`{public_url_base}/{storage_path}`
        - Cloudflare：`config.cloudflare_public_url` 或 `https://{bucket}.{account_id}.r2.dev`
        - Supabase：`{supabase_url}/storage/v1/object/public/{bucket}`
  4. **上传成功 → 注入 context**：
     1. 检查 LLM 模型的 modality 是否支持 image：`context.agent.llm_client.config[provider]["models"][model]["meta"]["modality"]`
     2. 构造 `llm_message`：
        - 支持 image：`{"role": "user", "content": [{"type": "image_url", "image_url": {"url": public_url}}]}`
        - 不支持 image：不够早user message，ToolResult: f"Image uploaded (model does not support image input): {public_url}"
     3. 构造 DB `data`：`{"content": f"Image: {filename}", "files": [{"name": filename, "url": public_url, "type": mime_type}]}`
     4. 返回 `ToolResult(SUCCESS, f"图片已读取", extra_context_messages=[{"llm_message": ..., "data": ..., "role": "user"}])`
  5. **上传失败 → 友好提示**：
     - 返回 `ToolResult(ERROR, "图片读取失败: {error_detail}。")`
     - **不注入** extra_context_messages
- **预期产出**：`broca/tools/image.py` — ReadImage 工具实现
- **验收标准**：
  - [ ] 工具自动被 `ToolManager._scan_builtin_tools()` 发现，`ToolManager().tools["read_image"]` 返回 ReadImage 实例
  - [ ] 文件不存在时返回 `ToolResult(ERROR, ...)`，content 包含 "文件不存在"
  - [ ] 非图片文件（如 `.txt`）返回 `ToolResult(ERROR, ...)`，content 包含 "不是图片文件"
  - [ ] 存储未配置（`backend` 为空）时返回 `ToolResult(ERROR, ...)`，content 包含 "云端存储未配置"
  - [ ] 上传成功时 `extra_context_messages` 包含一条 user 角色的多模态消息（`image_url` 格式），且 `content` 中包含 public URL
  - [ ] 上传失败时 `extra_context_messages` 为空列表
  - [ ] S3 上传使用 `asyncio.to_thread` 包装，不阻塞事件循环
  - [ ] 支持 Cloudflare R2 和 Supabase 两种后端，根据 `StorageConfig.backend` 自动切换

---

#### Task 1.3: 工具注册与权限配置

- **目标**：将 `read_image` 注册到 READONLY_TOOLS 集合，确保权限管理正确
- **步骤**：
  1. 在 `broca/tools/tool_manager.py` 的 `READONLY_TOOLS` 集合中添加 `"read_image"`
  2. 验证 `ToolManager._scan_builtin_tools()` 能自动发现 `broca/tools/image.py` 中的 `ReadImage` 类
- **预期产出**：`broca/tools/tool_manager.py` — READONLY_TOOLS 更新
- **验收标准**：
  - [ ] `ToolManager().READONLY_TOOLS` 包含 `"read_image"`
  - [ ] `ToolManager().tools["read_image"].name == "read_image"`
  - [ ] `read_image` 不在 `MODIFY_TOOLS` 集合中
  - [ ] 默认权限下调用 `read_image` 不需要用户确认（属于只读工具）

---

#### Task 1.4: 端到端验证

- **目标**：验证 read_image 工具在全链路中正确工作
- **步骤**：
  1. 编写单元测试（`broca/tools/test_image.py` 或 `tests/test_image_tool.py`）：
     - 测试文件不存在
     - 测试非图片文件
     - 测试存储未配置
     - 测试 boto3 S3 上传成功（mock boto3 client）
     - 测试 boto3 S3 上传失败（mock boto3 client 抛异常）
     - 测试 ToolResult 中 extra_context_messages 格式正确
     - 测试 Cloudflare 和 Supabase 两种后端的 S3 客户端创建参数
  2. 验证消息序列：
     - 构造一个包含 `read_image` tool_call 的模拟场景
     - 验证 context.history 中消息顺序：`assistant(tool_call) → tool(result) → user(image)`
     - 验证 `parse_message` 重建时能正确处理该消息
  3. 验证 `build_history_from_session` 能正确重建包含图片的用户消息
- **预期产出**：测试文件 + 通过的所有测试用例
- **验收标准**：
  - [ ] 所有单元测试通过（`pytest tests/test_image_tool.py -v`）
  - [ ] 模拟场景下 context.history 的消息顺序正确（tool result 在 user image message 之前）
  - [ ] `build_history_from_session` 重建后，图片消息以 `{"role": "user", "content": [{"type": "image_url", ...}]}` 格式正确出现在 history 中
  - [ ] 前端 `parse_message` 处理该消息时能正确识别 `image_url` 类型并构造多模态 content

## 风险与应对

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| `boto3` 与现有依赖冲突 | 安装失败 | boto3 依赖极少（botocore + jmespath），与 litellm/aiohttp 无已知冲突 |
| S3 上传超时（大图） | 工具阻塞 | 使用 `asyncio.to_thread` + `tool_call_timeout`（默认 120s）兜底；建议 LLM 只发送合理大小的图片 |
| 模型不支持 image modality | 注入 `image_url` 格式导致 LLM 调用报错 | 工具中检查 `modality`，不支持时退化为纯文本 URL |
| 前端未处理工具注入的 user message 展示 | 前端看不到图片消息 | 通过 `communicator.send_message` 广播（与 `_broadcast_user_message` 模式一致），前端已有 user message 渲染逻辑 |
| 会话恢复时图片 URL 过期 | 历史图片无法加载 | S3 公开 URL 通常不过期（Cloudflare R2/Supabase 公开 bucket 的 URL 持久有效）；过期时 LLM 仅看到 URL 文本，不影响功能 |

## 未解决的问题

- 暂无（所有关键决策已在计划制定前与用户确认）
