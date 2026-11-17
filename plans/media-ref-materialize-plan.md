# 图片/文件按需物化（ref 持久化 + 请求时 base64/files_api/url）改造计划

## 概述

- **目标**：解决国内/跨境 LLM 供应商拉取 Cloudflare R2 公网 URL 频繁超时的问题。核心做法是：**消息入库/内存历史只保存轻量「引用（ref）」+ 真实展示 URL**，在真正发请求给 LLM 前，把 ref 物化为 wire 表示。物化策略简化为二选一：**配置了 Files API 就优先走 files_api，否则走 base64；不再用 url 兜底**。两种方式各自配置文件阈值，超过阈值先压缩，压缩后仍超限则**直接报错提醒**。base64 **绝不入库、不进内存历史**。同时**解耦 `read_image` 与前端用户上传对云端存储的强依赖**：未配置云存储时，`read_image` 读本地文件即可（ref 走 `local` 种类），前端上传改走后端本地落盘端点。
- **背景**：
  - 现状链路：前端上传 → R2/Supabase → 公共 URL；`read_image` 再传 R2 → 注入 `image_url:{url: R2_url}`；LLM 供应商服务器回源下载 R2 → 跨境超时。
  - 现有代码会把 `llm_message`（含 image_url）**原样 `json.dumps` 入库并进内存 `_history`**（见 `broca/loop_engine/tool_injected_messages.py`、`broca/loop_engine/engine.py:_save_user_message`），因此 base64 若在 tool/parse 阶段生成会直接落库、常驻内存、每轮重发。
  - 前端展示依赖 `message.data.files[].url`（见 `broca-web/frontend/src/stores/chat.ts:568`、`FilePreview.vue`），所以真实 URL 必须保留在 `data.files`。
  - `read_image` 当前在 `broca/tools/image.py` 中**强制要求配置 `storage.backend`（cloudflare/supabase），否则直接返回错误**，导致本地读图能力被云存储绑架。
  - 前端用户上传（`broca-web/frontend/src/utils/upload.ts`）用浏览器直连 S3（R2/Supabase），**未配置云存储时 `isStorageConfigured()` 返回 false，`ChatInput` 直接报错阻止上传**。
- **约束条件**：
  - base64 不得进入 DB 与 `context._history`；只在 `get_stream_response` 请求前作为临时 wire 表示存在。
  - `data.files` 必须保留真实展示 URL 供前端展示与历史回放（云存储时是公网 URL；本地时是后端可访问的本地 URL）。
  - **`read_image` 必须在未配置云存储时仍可用**：此时不产生任何 S3 上传，物化直接读本地文件字节。
  - **前端用户上传必须在未配置云存储时仍可用**：改走后端 `POST /files/upload` 本地落盘，返回本地路径与 `/files/raw` 展示地址。
  - 各供应商接口不一致：base64 由 litellm 统一抹平；Files API 按供应商适配（本期先做 DeepSeek）。
  - **物化不做 url 兜底**：配 files_api 走 files_api，否则走 base64；超阈值先压缩，仍超限直接报错提醒。
  - 保持向后兼容：旧数据中 `image_url` 直接是 https URL 时仍按原逻辑处理。

## 相关材料

- 当前图片工具：`broca/tools/image.py`（`ReadImage`，负责上传 R2 并注入 llm_message）
- LLM 客户端与消息解析：`broca/llm.py`（`parse_message` L94-179、`get_stream_response` L181-248）
- 工具注入消息持久化：`broca/loop_engine/tool_injected_messages.py`
- 用户消息持久化：`broca/loop_engine/engine.py`（`_save_user_message` L384、`_inject_user_message` L420+）
- 历史重建：`broca/context.py`（`add_message` L215、`build_history_from_session` L233+）
- 存储配置：`broca/configs.py`（`StorageConfig` L79-108）
- 供应商/模态配置模板：`configs/llm_config_template.json`（`meta.modality` 结构，如 `{"text":"","image":{}}`）
- 组件接口：`broca/components/llm_client.py`（`parse_message` 抽象）
- 后端文件服务：`broca-web/backend/app/api/files.py`（`/files/preview` L254，仅文本；需新增二进制 raw 端点）
- 前端上传/展示：`broca-web/frontend/src/utils/upload.ts`、`broca-web/frontend/src/components/FilePreview.vue`
- **DeepSeek Vision 文档**：https://api-docs.deepseek.com/guides/vision/
- **DeepSeek Files API 文档**：https://api-docs.deepseek.com/guides/files_api
- 现有测试：`broca/tests/test_image_tool.py`、`broca/tests/test_tool_injected_message_order.py`
- 依赖清单：`pyproject.toml`（当前仅 `boto3`，**缺 `pillow`/`httpx`**，见 Task 2.0）
- 缓存清理联动点：`broca/commands/builtin/clear_context/__init__.py`、`broca/commands/builtin/clear_all_context/__init__.py`、`broca/commands/builtin/clear_history/__init__.py`、`broca/session/cleanup_service.py`（`cleanup_session`）、`broca/session/service.py`（`delete`/`delete_batch`）
- 身份透传链路：`broca/loop_engine/engine.py`（`_execute_step` 有 `self.agent_id`/`self.session_id`）、`broca/loop_engine/strategies/retry_llm.py`（`_stream_once` 调 `get_stream_response`）；注意 `LLMClient` 为 **singleton** 组件，缓存需按调用时身份选择目录
- 前端展示依赖：`broca-web/frontend/src/stores/chat.ts`、`broca-web/frontend/src/components/FilePreview.vue`

## 总体方案

**分层原则：持久化引用（ref） ↔ 请求时物化（materialize）。**

1. **持久化层（Phase 1）**
   - 定义 `ref://` 引用编码：把 ref 元数据编码进一个字符串占位，放进 `llm_message` 的 image/video part 的 `url` 字段。ref 支持两种 `kind`：
     - `cloud`：`{kind:"cloud", key, url, sha256, mime, size}` —— 已上传云存储，`url` 为公网地址，`key` 用于服务端回源。
     - `local`：`{kind:"local", path, url, sha256, mime, size}` —— 未配置云存储，物化直接读本地 `path`，`url` 为前端可访问的本地预览地址（可为空，如 TUI 场景）。
   - `data.files[]` 保留展示 `url` + `sha256` + `mime` + `size`（以及云场景的 `storage_key` / 本地场景的 `path`），供前端展示 + 物化取数。
   - `read_image` 与 `parse_message` 只产出 ref，不产出 base64。
   - `read_image` 解耦：配置了云存储 → 走 `cloud` ref（现状上传）；**未配置 → 走 `local` ref，不做任何 S3 上传**。

2. **物化层（Phase 2）**
   - 在 `LiteLLMClient.get_stream_response` 调用 `acompletion` 之前，对传入 `messages` 做一次**深拷贝 + ref 物化**，不修改 `context._history`。
   - 单个 part 决策树（**二选一 + 压缩兜底 + 报错**，无 url 兜底）：
     1. 读该 provider/model 的 `meta.modality`，若**不支持该模态**（如无 `image`）→ 降级为文本链接（`文件链接：<url>`）。
     2. 支持时按「是否配置 Files API」二选一：
        - **配置了 `files_api`** → **files_api 模式**：
          - 阈值 `max_size_mb`（来自 `files_api.max_size_mb`，DeepSeek 默认 64）。
          - `size <= 阈值` → 上传并引用 `file_id`。
          - `size > 阈值` → 先压缩降采样；压缩后 `<= 阈值` → 上传引用；否则 **报错提醒**。
        - **未配置 files_api** → **base64 模式**：
          - 阈值 `max_inline_mb`（来自 `meta.media_limits.max_inline_mb`，默认 4）。
          - **注意**：阈值**不得**放进 `meta.modality.image`。因为 `parse_message` 现有逻辑 `image_part.update(modality["image"])` 会把 `modality["image"]` 里的所有键**直接混入发往 LLM 的 `image_url` part**，若把 `max_inline_mb` 放这里会被当成非法 wire 参数下发。故统一放在独立的、不参与 wire 序列化的 `meta.media_limits` 命名空间。
          - `size <= 阈值` → **base64**（`data:<mime>;base64,<...>`）。
          - `size > 阈值` → 先压缩降采样；压缩后 `<= 阈值` → base64；否则 **报错提醒**。
     3. **非图片（视频/音频）不可压缩分支**：`_compress_to_fit` 仅对 `image/*` 有效；视频/音频在 base64 模式下超阈值**无法压缩**，直接抛 `MediaFileTooLargeError`（提示「配置 files_api 或缩小文件」）。即：无 files_api 时大视频/大音频 = 直接报错，不尝试压缩。
   - **本期范围**：只处理 `image`（以及文件已存在时顺带保留的 `video` part 的报错分支）；**音频（audio）本期不纳入 ref/物化**（现有 `parse_message` 对 audio 本就是 `pass` 忽略），显式声明避免误判为遗漏。
   - **超限错误**：定义明确的异常（如 `MediaFileTooLargeError`），带文件名/大小/阈值/建议，抛出后由上层转为用户可见的报错提醒（该轮 LLM 请求失败并提示），不再静默回退。
   - 存储字节读取：`local` ref 读本地 `path`；`cloud` ref 用 `boto3 get_object`/HTTP GET（`asyncio.to_thread`）。`local` ref 完全不需要云存储。
   - **全量持久化缓存（按 agent 隔离）**：不再用「按字节上限 LRU 淘汰」，改为**全量缓存**（数据量不大，不设字节上限）。key=`sha256`（base64/压缩结果）或 `(provider, sha256)`（file_id），value 为 base64 data-url / file_id。**落盘持久化**：写入 `<broca_home>/media_cache/<session_id>/<agent_id>/`（每个 agent 独立目录），进程重启后可复用（启动时加载索引）。**TTL 最多保留 3 天**：超过 3 天的条目在访问时/启动 GC 时删除。清除联动：`/clear_context` 清当前 agent 缓存、`/clear_all_context` 清该 session 全部 agent 缓存、删除 session 时删除 `<broca_home>/media_cache/<session_id>/` 整目录。

3. **Files API 策略（Phase 3，按 provider 差异，DeepSeek 优先）**
   > 注：`files_api` 为 **provider 级** 配置（与 `base_url`/`api_key`/`models` 平级），同一 provider 共享同一上传端点/认证/配额；不放 model 的 `meta`。模型能否消费 file 块由 `meta.modality` 决定。
   - 定义 `FilesApiStrategy` 接口（`async upload(ref) -> wire_part`），按 `files_api.type` 选择具体实现；不同供应商的上传端点/参数/引用块形态差异由各自 strategy 封装。
   - **首批实现 `DeepSeekFilesStrategy`**：
     - 上传：`POST {base_url}/files`（multipart，`file` + `purpose=user_data`，可选 `expires_after[anchor]=created_at`+`expires_after[seconds]`）→ 返回 `file_id`（`file-api-...`）。
     - 引用：Chat Completions 内容块 **`{"type":"file","file":{"file_id":"file-api-..."},"file_id":"file-api-..."}`**（**双 key**：`file` 包装满足 litellm openai provider 的校验，顶层 `file_id` 满足 DeepSeek 官方裸格式；抓包确认 litellm 会同时保留两者）。
     - 限制：图片格式 JPEG/PNG/GIF/WebP；`file_id` 图最大 64MiB；内联 base64/URL 图最大 32MiB；请求体 48MiB。
   - **provider 路由与 wire 形态（已抓包核验）**：模型以 `openai/` 前缀配置（如 `openai/deepseek-v4-flash`）时 litellm 走 **openai provider**，其 `_transform_messages` 要求 `file` 块带 `file` 字段并会**原样保留其余顶层 key**；而 **DeepSeek 官方要求裸 `{"type":"file","file_id":...}`**（见 https://api-docs.deepseek.com/guides/files_api）。故采用**双 key** 技巧：块内同时给 `file:{file_id:...}`（喂 litellm）与顶层 `file_id`（喂 DeepSeek），抓包验证 litellm 输出 `{"type":"file","file":{"file_id":...},"file_id":...}`，DeepSeek 可识别顶层 `file_id`。无需猴补或原生 HTTP。
   - 其他供应商（Gemini File API 返回 `uri`、Anthropic `/v1/files` + `anthropic-beta` 头 + `source.type=file`、OpenAI `/v1/files` 但 chat 不支持 file_id 图）列为后续扩展，接口已预留。
   - `file_id` 缓存复用同一 per-agent 持久化缓存（key=`(provider, sha256)`，TTL ≤3 天）；上传失败直接报错提醒（无 url 兜底）。
   - 更新配置模板与文档。

4. **上传路径选择（Phase 4）**
   - 前端 `uploadFile`：配置了云存储 → 保持浏览器直连 S3（现状）；**未配置 → 调后端 `POST /files/upload` 本地落盘**。
   - 后端 `POST /files/upload` 存到 `<broca_home>/uploads/YYYYMMDD/<unique>.<ext>`，返回 `{name, url:"/files/raw?path=...", path, local_path, size, type, sha256}`。
   - 上传结果扩展可选字段 `storage_key`（cloud）/`local_path`（local）/`sha256`，供 `parse_message` 构造对应 kind 的 ref；旧字段 `name/url/path/size/type` 保持不变（向后兼容）。

**关键决策**：
- ref 采用 `ref://` + `base64url(json)` 单字段编码，自包含（含真实 url），保证历史回放时无需额外查表即可物化。
- ref 分 `cloud` / `local` 两种 kind，`local` 让 `read_image` 在无云存储时仍可用；前端本地展示走新增的后端 `/files/raw` 端点。
- 物化点唯一收敛在 `get_stream_response`，所有 LLM 调用（含子 agent、注入消息）自动生效。
- **物化策略简化**：files_api 优先、否则 base64；无 url 兜底；两种方式各自配置阈值（`files_api.max_size_mb` / `meta.media_limits.max_inline_mb`），超限先压缩、仍超限直接报错。阈值放在独立的 `meta.media_limits` 命名空间（**不放进 `meta.modality.*`**），避免被 `parse_message` 的 `image_part.update(modality["image"])` 混入 wire 请求。
- Files API 按 `files_api.type` 选策略，本期落地 DeepSeek；其余供应商后续扩展。
- **缓存为全量、按 agent 隔离、持久化、TTL≤3 天**：数据量小不做字节淘汰；落盘 `<broca_home>/media_cache/<session_id>/<agent_id>/`，进程重启可复用；`clear_context`/`clear_all_context`/删除 session 同步清理。

## 执行计划

### Phase 1: 持久化引用与展示 URL 分离

**目标**：消息入库/内存历史只含轻量 ref，`data.files` 保留展示 URL；base64 不进入任何持久化路径；`read_image` 在未配置云存储时仍可用（`local` ref）。

**阶段验收标准**：
- [ ] 新产生的图片用户消息，DB `content` 中不含 `base64,`，含 `ref://`。
- [ ] 配置云存储时 `data.files[].url` 为真实 `https://` 公网地址，前端可正常展示。
- [ ] **未配置云存储时 `read_image` 正常返回成功（不报错、无 S3 调用），ref 为 `kind=="local"`，`data.files[].url` 为 `/files/raw?path=...` 本地地址。**
- [ ] 历史重建（`build_history_from_session`）后 `_history` 中的图片 part 仍为 ref。
- [ ] 旧数据（image_url 直接为 https）行为不变。

#### Task 1.1: 新增 media ref 编解码工具
- **目标**：提供 ref 的编码/解码/判别的纯函数，供 tool 与 llm client 复用；ref 支持 `cloud` / `local` 两种 kind。
- **步骤**：
  1. 新建模块 `broca/media/__init__.py` 与 `broca/media/ref.py`（若无 `broca/media` 则创建）。
  2. 实现 `encode_media_ref(meta: dict) -> str`：`meta` 至少含 `kind`（`cloud`|`local`）、`url`、`sha256`、`mime`、`size`；`cloud` 额外含 `key`，`local` 额外含 `path`。返回 `ref://` + `base64url(json.dumps(meta))`。
  3. 实现 `is_media_ref(url: str) -> bool` 与 `decode_media_ref(ref: str) -> dict`（含 `kind` 校验与必填字段校验，解码失败返回 None）。
  4. 补充类型注解与 docstring。
- **预期产出**：`broca/media/ref.py` 及单元测试 `broca/tests/test_media_ref.py`。
- **验收标准**：
  - [ ] `decode_media_ref(encode_media_ref(...))` 能还原全部字段（含中文/特殊字符 url、两种 kind）。
  - [ ] `is_media_ref` 对普通 https url、空串、非法 ref 均返回 False。
  - [ ] 缺 `kind` 或 kind 非法时 `decode_media_ref` 返回 None。
  - [ ] 单测覆盖正常（cloud/local）、非法 base64、缺字段三类用例并通过。

#### Task 1.2: 改造 `read_image` 产出 ref + 解耦云存储依赖
- **目标**：`ReadImage._execute` 注入的 `llm_message` 用 ref 占位；`db_data.files` 保留展示 url 及物化所需元数据；**未配置云存储时走 `local` ref，不报错、不上传**。
- **步骤**：
  1. 上传前计算文件 `sha256`（分块读取）与 `size`（`file_path.stat().st_size`）。
  2. **移除**对 `storage.backend` 的强制校验（当前会 `return ERROR` 的分支）。
  3. 分支处理：
     - 若 `storage.backend in ("cloudflare","supabase")`：保持现有上传逻辑得到 `storage_path` 与 `public_url`；构造 `kind="cloud"` 的 ref 与 `data.files`（含 `storage_key/sha256/size/url`）。
     - 否则（未配置云存储）：**不上传**，构造 `kind="local"` 的 ref（`path=abs(file_path)`、`sha256`、`mime`、`size`），`data.files.url` 设为本地预览地址 `/files/raw?path=<urlencode(abs)>`（见 Task 1.4；TUI 场景可为空）。
  4. `image_url_part["image_url"]["url"] = encode_media_ref(meta)`。
  5. 不支持图像模态的分支：仍返回文本链接（cloud 用真实 url，local 用本地预览 url），不产 ref。
- **预期产出**：修改后的 `broca/tools/image.py`。
- **验收标准**：
  - [ ] 未配置 storage 时 `_execute` **不再返回错误**，成功返回 `extra_context_messages`。
  - [ ] 未配置 storage 时 `llm_message.image_url.url` 以 `ref://` 开头且 `decode` 后 `kind=="local"`、`path` 指向真实文件。
  - [ ] 配置 storage 时 ref `kind=="cloud"`，`data.files[0].url` 为真实 `https://`，含 `storage_key/sha256/size`。
  - [ ] `sha256` 与实际文件内容一致（单测校验）。
  - [ ] 更新 `broca/tests/test_image_tool.py` 现有断言（含"未配置存储报错"用例改为"未配置存储走 local"）并全绿。

#### Task 1.3: 改造 `parse_message` 对 files 产出 ref
- **目标**：用户上传附件的 `parse_message` 在构建 image/video part 时，根据文件来源（cloud/local）用 ref 占位，否则保持原 url；不改变 `data`（真实 url 由上层 `_save_user_message` 从 `message.data` 保存）。
- **步骤**：
  1. 在 `broca/llm.py:parse_message` 的 files 循环中，读取 `file.get("storage_key")`、`local_path`、`path`、`sha256`、`mime`(`type`)、`size`。
  2. 判定 kind（**按显式字段优先级，避免隐式启发式**）：
     1. 若含 `storage_key`（非空）→ `cloud`（`key=storage_key`）。
     2. 否则若含 `local_path`（非空）→ `local`（`path=local_path`）。
     3. 否则若 `path` 为绝对路径（`os.path.isabs(path)`）→ `local`（`path=path`）。
     4. 否则若 `path` 为相对 storage key 且存在 `url`（**旧数据形态，例：`{"path":"uploads/2024/xx.png","url":"https://r2..."}`**）→ `cloud`（`key=path`）。
     5. 以上均不满足 → 不构造 ref，维持原 `file_url`（向后兼容）。
     - 说明：新前端/新后端上传结果同时带 `storage_key` 或 `local_path`，直接命中 1/2；旧数据仅靠 4 兜底，须单独列样例并加测试。
  3. 可构造 ref → `image_part["image_url"]["url"] = encode_media_ref(...)`；否则维持 `file_url`（向后兼容旧数据）。
  4. 保证 `raw_input` 与文本拼接逻辑不变。
- **预期产出**：修改后的 `broca/llm.py`。
- **验收标准**：
  - [ ] `storage_key` 文件生成 `kind=="cloud"` ref；`local_path` 文件生成 `kind=="local"` ref；两者都无的旧数据仍为原 https url。
  - [ ] `parse_message` 返回值中不含 `base64,`。
  - [ ] 现有 `parse_message` 相关测试通过，新增 cloud/local ref 分支测试。

#### Task 1.4: 后端新增本地文件二进制端点 `/files/raw`
- **目标**：为 `local` ref 提供前端可加载的图片展示 URL（现有 `/files/preview` 只返回文本）。
- **步骤**：
  1. 在 `broca-web/backend/app/api/files.py` 新增 `GET /files/raw?path=`，返回 `FileResponse`（正确 `media_type`），仅允许图片/音视频等二进制类型，拒绝目录与超大文件（设上限，如 50MB）。
  2. 路径安全（**不得照搬 `/files/preview`**：实测 preview 仅 `resolve()`、无根目录约束，可读任意绝对路径，会引入任意文件读取漏洞）：定义明确的**允许根目录白名单**（如 `<broca_home>/uploads`、workspace 根、会话附件目录），对请求路径 `Path(path).expanduser().resolve()` 后校验 `resolved.is_relative_to(root)`（任一白名单根命中即可），**越界返回 403**；目录、不存在、非白名单类型一律拒绝。禁止仅依赖 `resolve()` 而不做根目录校验。
  3. 前端无需改动：`data.files[].url` 为 `/files/raw?path=...` 相对地址，`<img src>` 直接可用（与现有 `/files/preview` 用法一致）。
- **预期产出**：`broca-web/backend/app/api/files.py` 新增端点。
- **验收标准**：
  - [ ] `GET /files/raw?path=<图片>` 返回 200 且 `Content-Type` 正确，浏览器可渲染。
  - [ ] 目录/不存在路径返回 404/400；超大文件返回 413 或明确错误。
  - [ ] 路径穿越（如 `../../etc/passwd`）被拒绝，返回 403（基于 `is_relative_to(白名单根)` 校验）。
  - [ ] 位于白名单根内但非白名单类型的文件被拒绝；位于根外的合法图片路径返回 403。
  - [ ] 明确前端访问 `/files/raw` 的同源/代理前提（`<img src>` 为相对地址，需与后端同源或经前端 dev proxy 转发），并在文档标注。

### Phase 2: 请求时物化管线（files_api / base64，无 url 兜底）

**目标**：在发请求前把 ref 按「模态 → 是否配置 files_api 二选一 → 阈值 → 压缩 → 报错」物化，带字节读取与 per-agent 持久化缓存（全量、TTL≤3 天），且不污染 `_history`。

**阶段验收标准**：
- [ ] 未配置 files_api、`size <= max_inline_mb` 的图片，请求体中为 `data:<mime>;base64,...`。
- [ ] 配置了 files_api 的 provider，图片以（桩）`file_id` 引用（不发送 base64）；真实 file_id 于 Phase 3 满足。
- [ ] 超过阈值时先压缩；压缩后达标则正常发送（base64 或 files_api）。
- [ ] 压缩后仍超阈值时**抛出明确错误并提醒用户**（不静默回退 url）。
- [ ] 不支持图像模态时，请求体中该 part 降级为文本链接。
- [ ] 相同 `sha256` 第二次请求命中缓存，不重复读取存储字节；进程重启后（新实例）仍命中（落盘复用）。
- [ ] 缓存按 `(session_id, agent_id)` 隔离；`/clear_context` 清当前 agent、`/clear_all_context`/删除 session 清对应目录；条目 >3 天自动过期。
- [ ] 物化前后 `context._history` 内容不变（仍为 ref）。

#### Task 2.0: 新增第三方依赖（Pillow / httpx）声明与验证
- **目标**：为压缩（Pillow）与云字节 HTTP 读取（httpx）补齐依赖声明，避免运行期 ImportError。
- **步骤**：
  1. 在 `pyproject.toml` 的 `[project.dependencies]`（或 poetry 对应位置）新增 `pillow` 与 `httpx`（版本与现有风格一致，如 `pillow (>=10.0.0,<12.0.0)`、`httpx (>=0.27.0,<1.0.0)`；若 httpx 已被 litellm 传递依赖，仍显式声明以免被上游变动移除）。
  2. 执行 `poetry install` / `uv sync`（按项目实际工具）安装并验证。
  3. 确认 `from PIL import Image`、`import httpx` 均可导入；在 CI/测试引导处保证依赖已装。
- **预期产出**：更新后的 `pyproject.toml`（+ 锁文件）。
- **验收标准**：
  - [ ] `python -c "from PIL import Image; import httpx; print('ok')"` 通过（在项目虚拟环境内）。
  - [ ] `pyproject.toml` 同时包含 `pillow` 与 `httpx` 显式声明。
  - [ ] `poetry install`/`uv sync` 无报错，锁文件已更新。

#### Task 2.1: 新增 `MediaMaterializer` 与决策树
- **目标**：实现单 part 物化的决策树与批量 messages 物化入口。
- **步骤**：
  1. 新建 `broca/media/materializer.py`，实现 `class MediaMaterializer`，注入 `config`（llm 配置）、`storage`（StorageConfig）与 `files_api_factory`（可注入的 strategy 工厂；Phase 2 用桩，Phase 3 提供真实实现）。
  2. `async def materialize_messages(self, messages, provider, model, session_id=None, agent_id=None) -> list[dict]`：深拷贝 messages，遍历 `content` list，对含 ref 的 part 调 `_resolve_part`；`session_id`/`agent_id` 用于选择 per-agent 缓存目录（见 Task 2.4）。
  3. `async def _resolve_part(self, part, provider, model)`：按决策树：
     - 取 `meta.modality`；part 类型对应模态不在 modality → 返回文本链接 part。
     - 读 ref 的 `size`。
     - **若配置了 `files_api`** → files_api 模式：阈值 = `files_api.max_size_mb`（默认 64）；`size <= 阈值` → `_via_files_api`（**委托注入的 `FilesApiStrategy`；Phase 2 用桩 strategy 返回固定 `{"type":"file","file":{"file_id":"stub"},"file_id":"stub"}` 以验证分支，真实 strategy 于 Phase 3 提供**）；否则 `_compress_to_fit(ref, 阈值)` 后仍超 → 抛 `MediaFileTooLargeError`。
     - **否则 base64 模式**：阈值 = `meta.media_limits.max_inline_mb`（默认 4，**不放在 `meta.modality.image`**，避免被 `image_part.update(modality["image"])` 混入 wire）；`size <= 阈值` → `_to_base64`；否则 `_compress_to_fit(ref, 阈值)` 后仍超 → 抛 `MediaFileTooLargeError`。
     - **非图片（视频/音频）不可压缩**：`_compress_to_fit` 返回 None → 直接抛 `MediaFileTooLargeError`（提示配置 files_api 或缩小文件）。
  3.1 **辅助方法职责**（本任务定义，后续任务填充实现）：
     - `async def _to_base64(self, ref) -> str`：返回 `data:<mime>;base64,<...>` 字符串（字节来源见 Task 2.2 `_read_bytes`）。
     - `async def _via_files_api(self, ref) -> dict`：委托注入的 `FilesApiStrategy.upload(ref)`，返回 wire content part（双 key 形态，如 `{"type":"file","file":{"file_id":...},"file_id":...}`）。
  3.2 **桩先行**：本任务阶段 `_read_bytes`（Task 2.2）、缓存（Task 2.3）、`_compress_to_fit`（Task 2.5）尚未实现，先用最小桩/接口占位，待后续任务替换真实实现（依赖图见文末）。
  4. 解码失败/取字节失败 → 记录日志并抛明确错误（不再回退 url）。
- **预期产出**：`broca/media/materializer.py`、`broca/media/errors.py`（`MediaFileTooLargeError`）。
- **验收标准**：
  - [ ] 分支各有单测（模态不支持→文本 / 未配 files_api 小文件→base64 / 配 files_api→**注入 mock strategy** 产出 `{"type":"file","file":{"file_id":...},"file_id":...}` / 超阈值压缩达标→正常发送 / 压缩后仍超→抛错）。files_api 分支的真实 strategy 于 Phase 3 提供，Phase 2 仅以桩/mock 验证分支走向。
  - [ ] 传入的 `messages` 原对象不被修改（引用不变，content 未被就地改写）。
  - [ ] 非图片（视频/音频）在 base64 模式超阈值时抛 `MediaFileTooLargeError`（不尝试压缩）。
  - [ ] 抛出的错误信息含文件名、大小、阈值、建议。

#### Task 2.2: 存储字节读取（本地 local / 云 cloud）
- **目标**：为 base64/压缩/files_api 上传提供字节来源：`local` ref 直接读本地文件（无云存储依赖），`cloud` ref 走 S3/HTTP。
- **步骤**：
  1. 在 `materializer.py` 实现 `async def _read_bytes(self, ref) -> bytes`，按 `ref["kind"]` 分派。
  2. `kind=="local"`：读 `ref["path"]`；不存在抛明确错误。
  3. `kind=="cloud"`：**优先用 `boto3`**（项目已有依赖）按 `key`/bucket `get_object` 读取（复用 `image.py` 的 `_create_s3_client` 逻辑，抽出公共函数到 `broca/media/storage.py`）；如需按真实 url HTTP GET 兜底，使用 `httpx`（已在 Task 2.0 显式声明依赖）。
  4. 用 `asyncio.to_thread` 包裹同步 IO；失败抛明确错误。
- **预期产出**：`_read_bytes` 及复用后的 S3 client 构建函数（可放 `broca/media/storage.py`）。
- **验收标准**：
  - [ ] `local` ref 读取本地文件字节正确，且**不触发任何网络/S3 调用**（mock 断言）。
  - [ ] `cloud` ref 走 S3/HTTP 读取。
  - [ ] `local` ref 的 `path` 不存在时抛明确错误。
  - [ ] `_to_base64`（定义于 Task 2.1 的 `MediaMaterializer`/工具函数）配合 `_read_bytes` 的返回字节，产出正确的 `data:<mime>;base64,...`（本任务验证二者集成，不重复定义）。

#### Task 2.3: 全量持久化缓存（按 agent 隔离，TTL ≤3 天）
- **目标**：避免同图跨轮重复读取/编码/上传；缓存**全量保存、不按字节淘汰**，**落盘持久化**以便进程重启复用，且**每个 agent 独立**。
- **步骤**：
  1. 实现 `class MediaCache`（`broca/media/cache.py`）：`get(key)`、`put(key, value)`、`clear()`、`gc_expired()`。key 为 `sha256`（base64/压缩结果）或 `(provider, sha256)`（file_id）。
  2. **全量、无字节上限**：保留所有条目，不做 LRU 淘汰（数据量小）。
  3. **落盘持久化**：目录 `<broca_home>/media_cache/<session_id>/<agent_id>/`（每 agent 独立）；每个条目一个文件（如 `<keyhash>.b64` / `<keyhash>.fileid.json`），附 JSON 元数据（`key, created_at, size, kind`）或集中 `index.json`。`put` 原子写（临时文件 + rename），`get` 未命中读盘并按 `created_at` 校验 TTL。启动时加载索引、无需全量读盘。
  4. **TTL ≤3 天**：`created_at` 超过 3 天的条目在 `get` 时视为未命中并删除；提供 `gc_expired()` 供启动/定时调用清理过期文件。
  5. **清理 API**：`clear()` 删除本 agent 目录；`clear_session(session_id)` 删除 `<broca_home>/media_cache/<session_id>/`（供 clear_all_context / 删除 session 调用）。
  6. `_to_base64` / `_via_files_api` / `_compress_to_fit` 先查缓存，未命中再处理并 `put`。
  7. 线程/协程安全（`asyncio.Lock` 或文件锁，防止并发读写同一 key）。
  8. **agent 维度注入**：`MediaMaterializer` 的缓存实例按 `(session_id, agent_id)` 选择目录；该二者由 `get_stream_response` 新增的可选参数传入（见 Task 2.4）。
- **预期产出**：`broca/media/cache.py`。
- **验收标准**：
  - [ ] 相同 sha256 第二次不触发 `_read_bytes`（mock 计数=1）。
  - [ ] `put` 后新建 `MediaCache` 实例（模拟进程重启）仍能 `get` 命中（落盘复用）。
  - [ ] 不同 `agent_id` 的缓存目录互相隔离，互不可见。
  - [ ] `created_at` 超过 3 天的条目 `get` 返回未命中且被删除；`gc_expired()` 清理过期文件。
  - [ ] `clear()` 仅删本 agent 目录；`clear_session()` 删除整 session 缓存目录。
  - [ ] 缓存内容不进 DB、不进 `context._history`（仅落盘文件）。

#### Task 2.4: 接入 `get_stream_response`
- **目标**：在 `acompletion` 前对 messages 做物化，唯一收敛点；并把 agent/session 身份透传给物化器以选择 per-agent 缓存目录。
- **步骤**：
  1. 在 `LiteLLMClient.__init__` 构建 `MediaMaterializer`（注入 config 与 `get_configs().storage`）；**注意 `LiteLLMClient` 为 singleton 组件**，故缓存实例不能只挂在 client 上，需按调用时的 `(session_id, agent_id)` 选择。
  2. `get_stream_response` 增加**可选**参数 `agent_id=None, session_id=None`；`acompletion(...)` 之前：`messages = await self._materializer.materialize_messages(messages, provider, model, session_id=session_id, agent_id=agent_id)`。
  3. **身份透传链路**：`DefaultLoopEngine._execute_step` 调 `self._llm_strategy.call(...)` 时传入 `agent_id=self.agent_id, session_id=self.session_id`（或 initialize 时设置到 strategy）；`RetryLLMStrategy._stream_once` 再传给 `get_stream_response`。缺省时（如测试/子 agent 未传）回退到一个进程级临时目录或 `agent_id="unknown"`。
  4. `MediaFileTooLargeError` 转成 `LLMError`（带可读提示）向上抛出，让该轮失败并提醒用户。
  5. 确保 materialize 只处理含 ref 的 part；无 ref 的旧消息零改动。
- **预期产出**：修改后的 `broca/llm.py`、`broca/loop_engine/engine.py`、`broca/loop_engine/strategies/retry_llm.py`。
- **验收标准**：
  - [ ] mock `acompletion` 断言收到的 messages 中 ref 已替换为 base64 或 `file_id`。
  - [ ] 无 ref 的普通文本/旧图片消息原样透传。
  - [ ] 传入不同 `agent_id` 时，物化器使用各自缓存目录（断言路径含 `<agent_id>`）。
  - [ ] 超限错误被转成用户可见的 `LLMError`，信息含建议。

#### Task 2.5: 图片压缩降采样兜底
- **目标**：超阈值图片先压缩到目标阈值内，压不下去再报错。
- **步骤**：
  1. 在 `materializer.py` 实现 `async def _compress_to_fit(self, ref, threshold) -> bytes | None`：用 Pillow 打开图片，长边缩放到 2048（可配），转 RGB，JPEG q85 重编码，循环降质/降尺寸直到 `<= threshold` 或达到迭代上限；返回压缩字节或 None（压不下去）。
  2. 仅对 `image/*` 生效；视频/音频等不可压格式直接返回 None（上层据此报错）。
  3. 用 `asyncio.to_thread` 包裹同步 Pillow 操作；压缩失败/非图片返回 None。
  4. 压缩结果用新 sha256（内容已变）写入 per-agent 持久化缓存，避免重复压缩。
- **预期产出**：`_compress_to_fit` + 单测。
- **验收标准**：
  - [ ] 构造一张 `>4MB` 的测试图片，压缩后字节数 `< threshold`，且能被 Pillow 正常打开。
  - [ ] 非图片（如视频 mime）调用返回 None。
  - [ ] 相同源图第二次命中压缩缓存，不重复压缩（mock 计数）。
  - [ ] 压缩过程不修改原文件与 `_history`。

#### Task 2.6: 缓存生命周期清理（clear_context / 删除 session / TTL GC）
- **目标**：保证缓存随上下文清除与 session 删除同步清理，并有过期 GC 兜底。
- **步骤**：
  1. **`/clear_context`**（`broca/commands/builtin/clear_context/__init__.py`）：在重建 context 后，调用 `MediaCache.clear()` 清除**当前 agent** 的缓存目录（`<broca_home>/media_cache/<session_id>/<agent_id>/`）。
  2. **`/clear_all_context`**（`broca/commands/builtin/clear_all_context/__init__.py`）：调用 `MediaCache.clear_session(session_id)` 删除该 session 下**全部 agent** 缓存目录。
  3. **`/clear_history`**（`broca/commands/builtin/clear_history/__init__.py`）：该命令会把整个 session 所有 agent 的消息/turn 标记 reverted 并重建全部 agent 上下文，语义等同清空整个会话 → 同样调用 `MediaCache.clear_session(session_id)` 删除该 session 全部 agent 缓存目录。
  4. **删除 session**（`broca/session/cleanup_service.py:cleanup_session`）：新增一步（独立 try/except，容错不影响其他清理）删除 `<broca_home>/media_cache/<session_id>/` 整目录。
  5. **TTL GC**：在 `MediaCache` 启动或 `gc_expired()` 中清理 >3 天条目；可选接入现有调度器做定期清理。
- **预期产出**：修改后的 `clear_context`、`clear_all_context`、`clear_history`、`cleanup_service.py`，及 `MediaCache.clear/clear_session/gc_expired`。
- **验收标准**：
  - [ ] 执行 `/clear_context` 后当前 agent 缓存目录被清空，其他 agent 不受影响。
  - [ ] 执行 `/clear_all_context` 后该 session 全部 agent 缓存目录被清空。
  - [ ] 执行 `/clear_history` 后该 session 全部 agent 缓存目录被清空。
  - [ ] 删除 session 后 `<broca_home>/media_cache/<session_id>/` 目录被删除。
  - [ ] 单测覆盖四条清理路径，且清理失败不抛异常（仅 warning）。

### Phase 3: Files API 策略（按 provider 差异，DeepSeek 优先）

**目标**：为大文件提供供应商原生上传通道；用统一接口封装各家差异，**首批落地 DeepSeek**；上传失败直接报错提醒（无 url 兜底）。

**阶段验收标准**：
- [ ] **Phase 3 起始先完成 Task 3.0：用双 key 块 `{"type":"file","file":{"file_id":...},"file_id":...}` smoke 确认 DeepSeek 接受（容忍多余 `file` 字段），否则回退原生 HTTP/猴补/base64。**
- [ ] 配置了 `files_api.type="deepseek"` 的 provider，图片走 DeepSeek Files 上传并以双 key 块 `{"type":"file","file":{"file_id":...},"file_id":...}` 引用；未配置走 base64。
- [ ] 上传失败时抛出明确错误提醒（不静默回退）。
- [ ] `(provider, sha256)` 维度 TTL 缓存生效，未过期不重复上传。
- [ ] 配置模板与文档说明各字段，并列出 provider 差异表。

#### Task 3.0: 双 key file 块 smoke 验证（Phase 3 前置，轻量）
- **目标**：确认「双 key 块 `{"type":"file","file":{"file_id":...},"file_id":...}` 经 openai provider 发到 DeepSeek 被接受」，仅一次冒烟。
- **背景（已抓包核验）**：`openai/deepseek-v4-flash` 经 litellm 发包装形态；用双 key（`file` + 顶层 `file_id`）可让 litellm 校验通过且 DeepSeek 拿到裸 `file_id`（抓包确认 litellm 输出两者都保留）。
- **步骤**：
  1. 用真实/测试 `file_id` 发一次 `acompletion(model="openai/deepseek-v4-flash", api_base="https://api.deepseek.com/v1", messages=[{...,"content":[{"type":"file","file":{"file_id":"<file-api-...>"},"file_id":"<file-api-...>"}]}])`，确认被接受（无 400）。
  2. 若 DeepSeek 因多出的 `file` 字段严格校验报错，回退：①原生 HTTP 直发裸 `file_id`；②猴补 litellm 转换拍平为裸形态；③放弃 file_id 改用内联 base64。据结果定 Task 3.2。
- **预期产出**：`scripts/smoke_deepseek_file_block.py` + 结论。
- **验收标准**：
  - [ ] smoke 明确给出「双 key 块是否被 DeepSeek 接受」的结论。
  - [ ] 结论回填「未解决的问题」并据此定 Task 3.2 的引用块形态。

#### Task 3.1: 定义 `FilesApiStrategy` 接口与按类型选择
- **目标**：抽象各供应商上传差异，按配置选择实现。
- **步骤**：
  1. 新建 `broca/media/files_api.py`，定义 `class FilesApiStrategy(ABC)`：`async def upload(self, ref: dict, provider_cfg: dict) -> dict | None`（返回可用于 wire 的 content part，双 key 形态如 `{"type":"file","file":{"file_id":...},"file_id":...}`）。
  2. 实现工厂/注册表：读取 `files_api.type`（`deepseek` / 预留 `gemini`/`anthropic`/`openai`）返回对应 strategy；无配置返回 None。
  3. 预留 provider 差异扩展点（不同上传端点、认证头、引用块形态）。
- **预期产出**：`broca/media/files_api.py`。
- **验收标准**：
  - [ ] 未配置或 type 未知时返回 None，materializer 走 base64。
  - [ ] 配置 `type="deepseek"` 时返回 `DeepSeekFilesStrategy` 实例。
  - [ ] 配置解析失败记录日志并回退 None（即走 base64）。

#### Task 3.2: 实现 `DeepSeekFilesStrategy`（首个 provider）
- **目标**：按 DeepSeek 官方 Files API 完成上传与引用。
- **步骤**：
  1. 上传：`POST {base_url}/files`，`multipart/form-data`，字段 `file`（字节）+ `purpose=user_data`；如需过期，附 `expires_after[anchor]=created_at` + `expires_after[seconds]`（3600–2592000）。
  2. 解析响应 `{"id":"file-api-...", ...}`，取 `id` 作为 `file_id`。
  3. 引用块：返回**双 key** `{"type":"file","file":{"file_id":"file-api-..."},"file_id":"file-api-..."}`（`file` 包装喂 litellm、顶层 `file_id` 喂 DeepSeek；抓包确认两者都保留；**不是** `image_url`）。
  4. 图片格式校验（JPEG/PNG/GIF/WebP，按内容嗅探，非扩展名）；大小上限 64MiB（`file_id` 图）；超限报错。
  5. `(provider, sha256)` 缓存 `file_id`，复用 Task 2.3 的 per-agent 持久化缓存（TTL 取 `min(3 天, provider expires_at)`）；命中直接复用，进程重启后仍可复用。
  6. 在 materializer 的 files_api 分支调用；上传异常 → 抛明确错误提醒（无 url 兜底）。
  7. **下发方式**：经现有 `openai/` 前缀模型走 openai provider 下发双 key 块 `{"type":"file","file":{"file_id":...},"file_id":...}`（抓包确认 litellm 保留顶层 `file_id`）；如 Task 3.0 smoke 发现 DeepSeek 因多余 `file` 字段报错，按结论回退原生 HTTP / 猴补 / 内联 base64，不做静默兜底。
- **预期产出**：`DeepSeekFilesStrategy` + TTL 缓存 + 单测（mock HTTP/litellm）。
- **验收标准**：
  - [ ] mock 上传成功返回双 key 块 `{"type":"file","file":{"file_id":"file-api-..."},"file_id":"file-api-..."}`，且未走 base64。
  - [ ] 第二次相同 sha256 命中缓存不重复 HTTP。
  - [ ] 非图片/超大/上传抛错时抛出明确错误（不静默回退）。
  - [ ] 下发双 key 块 `{"type":"file","file":{"file_id":...},"file_id":...}` 的用例（成功或明确报错路径）通过。

#### Task 3.3: 配置模板与文档更新（含 provider 差异表）
- **目标**：让使用者可声明传输策略，并说明各 provider 差异。
- **步骤**：
  1. 更新 `configs/llm_config_template.json`：在相关 model 的 `meta` 增加：
     - `media_limits.max_inline_mb`（base64 阈值，默认 4）。**必须放在 `meta.media_limits` 独立命名空间，不得放进 `meta.modality.image`**——否则会被 `parse_message` 的 `image_part.update(modality["image"])` 混入发往 LLM 的 `image_url` part，造成非法参数/供应商报错。
     - `files_api`（可选）：`{"type":"deepseek","purpose":"user_data","expires_seconds":86400,"max_size_mb":64}`（`max_size_mb` 为 files_api 阈值，默认按 provider，DeepSeek 64）。
  2. 在 `docs/` 补充字段说明与默认值，说明「配了 files_api 优先走 files_api，否则走 base64；无 url 兜底；超阈值先压缩、仍超报错」。
  3. 补充 **provider 差异表**：DeepSeek（`POST /files` + `file_id` + 双 key `{"type":"file","file":{"file_id":...},"file_id":...}` 块 + 64MiB；模型用 `openai/` 前缀走 openai provider）、Gemini（File API 返回 `uri`）、Anthropic（`/v1/files` + `anthropic-beta` 头 + `source.type=file`）、OpenAI（`/v1/files` 但 chat 图不支持 file_id）。
- **预期产出**：模板 + 文档更新。
- **验收标准**：
  - [ ] 模板 JSON 合法，`python -c "import json;json.load(open(...))"` 通过。
  - [ ] 模板中 `max_inline_mb` 位于 `meta.media_limits`，且 `meta.modality.image` 内不含任何非 wire 配置字段（断言 `parse_message` 产出的 `image_url` part 仅含 `url` 及 wire 允许键）。
  - [ ] 文档列明字段含义、默认值、示例，并含 provider 差异表与"无 url 兜底/超限报错"策略说明。

#### Task 3.4: 端到端回归测试
- **目标**：覆盖完整链路，含 DeepSeek files_api 分支。
- **步骤**：
  1. 端到端：`read_image`（mock 上传）→ 持久化 content 为 ref、data.files 为真实 url → `get_stream_response`（mock acompletion）断言最终 wire 为 base64。
  2. DeepSeek `files_api` 配置 → 走 `POST /files` 上传，最终 wire 为双 key 块 `{"type":"file","file":{"file_id":...},"file_id":...}`；上传失败 → 报错。
  3. 历史重建后再请求 → 仍为 base64（缓存命中）。
  4. **缓存 TTL vs 文件保留期**：缓存命中时即便源文件已过期仍可物化；缓存未命中且源文件已删（模拟 >2 天）→ 抛明确错误提示重新上传。
- **预期产出**：`broca/tests/test_media_materialize_e2e.py`。
- **验收标准**：
  - [ ] 四条 e2e 场景通过（含 DeepSeek file_id 引用、缓存 TTL/文件过期一致性）。
  - [ ] `pytest broca/tests/ -k "media or image"` 全绿，且不访问真实 `~/.broca/`。
  - [ ] `pytest broca/tests/test_tool_injected_message_order.py` 亦全绿（守住消息顺序不回归）。

### Phase 4: 前端用户上传解耦云存储

> 说明：本阶段是独立子系统（前端 + 后端上传端点），与 LLM 物化正交，可并行开发。因跨越前端/后端且含安全约束，单列一个阶段以保持可验证性。

**目标**：未配置云存储时，前端用户上传仍可用（走后端本地落盘），返回本地展示 URL 与本地路径，供后续 `local` ref 物化；配置云存储时行为不变。

**阶段验收标准**：
- [ ] 未配置云存储时，前端选择图片可上传成功，消息中 `data.files[].url` 为 `/files/raw?path=...`，且 `<img>` 请求该 URL 返回 200 且 `Content-Type` 为 `image/*`。
- [ ] 未配置云存储时，上传的图片能作为 `local` ref 被 LLM 物化为 base64（链路打通）。
- [ ] 配置云存储时，上传行为与改造前一致（浏览器直连 S3，url 为公网地址）。
- [ ] 上传端点对超大文件、非法类型、路径穿越有防护。

#### Task 4.1: 后端新增 `POST /files/upload` 本地落盘端点
- **目标**：接收 multipart 文件，存本地并返回前端所需元数据。
- **步骤**：
  1. 在 `broca-web/backend/app/api/files.py` 新增 `POST /files/upload`（`UploadFile`）。
  2. 存到 `<broca_home>/uploads/YYYYMMDD/<encodedName>_<uuid6>.<ext>`（后端复用 `image.py` 的 `_generate_storage_path` 命名规则保证唯一；前端 `generateStoragePath` 仅路径规则对齐，非调用同一函数）。
  3. 计算 `size`、`mime`、`sha256`（分块）。
  4. 返回 `{name, url:"/files/raw?path=<urlencode(abs)>", path:abs, local_path:abs, size, type, sha256}`。
  5. 安全：限制大小（如 50MB）、校验扩展名白名单（图片/音视频/文本/常见文档）、文件名清洗。
  6. **保留期 ≤2 天**：`<broca_home>/uploads/` 下按 `YYYYMMDD` 日期目录组织，新增清理逻辑删除**早于 2 天**的日期目录（可在每次上传时机会式清理，或接入现有调度器定期 GC）。注意：被 `local` ref 引用、且仍在缓存/物化中需要的文件也应遵循 2 天保留上限（超期即删，物化时缺失则按 Task 2.2 抛明确错误提示重新上传）。
- **预期产出**：`broca-web/backend/app/api/files.py` 新增端点。
- **验收标准**：
  - [ ] 上传图片返回 200，`local_path` 指向真实落盘文件，`url` 可被 `/files/raw` 访问。
  - [ ] 超过大小上限返回 413/400；非法扩展名被拒绝。
  - [ ] 中文文件名正确落盘且 `url` 可访问（编码正确）。
  - [ ] 超过 2 天的 `uploads/YYYYMMDD/` 日期目录被清理逻辑删除（单测用伪造旧日期目录验证）。

#### Task 4.2: 前端 `upload.ts` 双通道改造
- **目标**：配置云存储走 S3，否则走后端上传；扩展 `UploadResult`。
- **步骤**：
  1. 扩展 `UploadResult` 增加可选 `storage_key?`、`local_path?`、`sha256?`。
  2. `uploadFile`：`getStorageConfig()` 有值 → 现有 S3 直传（补充返回 `storage_key: path`、`sha256` 计算）；无值 → `POST /files/upload`（multipart），映射后端响应。
  3. 云直传时也计算 `sha256` 以便 ref 使用：优先 `crypto.subtle.digest`（仅在 secure context：https 或 `localhost` 可用）；**非 secure context 时回退到纯 JS 实现 `js-sha256`**（新增前端依赖并写入 AC），保证 `sha256` 始终可得，避免 ref 无法构造。
- **预期产出**：修改后的 `broca-web/frontend/src/utils/upload.ts`。
- **验收标准**：
  - [ ] 无云配置时调用后端端点并返回含 `local_path` 的结果。
  - [ ] 有云配置时仍走 S3 直传，返回含 `storage_key`。
  - [ ] 两种结果均含 `sha256`。
  - [ ] 非 secure context（http 非 localhost）下 `sha256` 仍能通过 `js-sha256` 兜底计算，且结果与 `crypto.subtle` 一致。

#### Task 4.3: `ChatInput` 解除存储硬阻断 + 类型透传
- **目标**：未配置存储不再阻止上传；新字段透传到消息 `data.files`。
- **步骤**：
  1. `uploadSingleFile` 移除 `isStorageConfigured()` 的硬阻断（改为不阻止，交由 `uploadFile` 内部选择通道）。
  2. `handleSendMessage` 构造 `uploadedFiles` 时透传 `storage_key/local_path/sha256`。
  3. 更新 `chat.ts` 中 `sendUserMessage` 的 files 参数类型与 `userFiles` 类型（新增可选字段）。
- **预期产出**：修改后的 `ChatInput.vue`、`chat.ts`。
- **验收标准**：
  - [ ] 未配置存储时选择图片不再报"存储未配置"，可正常发送。
  - [ ] `data.files` 中可见 `local_path` 或 `storage_key`、`sha256`。
  - [ ] TypeScript 编译通过（`npm run build`/`vue-tsc`）。

#### Task 4.4: 前端上传解耦的端到端验证
- **目标**：串起前端上传 → 后端落盘 → local ref → 物化 base64。
- **步骤**：
  1. 后端单测：`/files/upload` 落盘 + `/files/raw` 回读字节一致。
  2. 前端单测（如现有 vitest 体系）：`uploadFile` 在无云配置时调用后端端点（mock fetch）。
  3. 链路：构造 `local_path` 文件 → `parse_message` 产 local ref → `get_stream_response` 物化为 base64。
- **预期产出**：相关测试用例。
- **验收标准**：
  - [ ] 后端上传/回读字节一致性测试通过。
  - [ ] 前端双通道选择测试通过。
  - [ ] local ref 物化链路测试通过。
  - [ ] 前端通过 `/files/raw?path=...` 展示本地图片验证同源/代理前提成立（与后端同源或经 dev proxy），否则 `<img>` 加载失败需在文档标注部署要求。

## 依赖关系

- Task 1.1 → 1.2、1.3（ref 工具先行）；1.4（后端 raw 端点）可与 1.2 并行，供 local 展示 url 使用。
- Phase 2 依赖 Phase 1 完成（需 ref 产出）。
- Task 2.0（依赖声明）→ 2.1 → 2.2、2.3、2.5 → 2.4（先声明 Pillow/httpx，物化器先于缓存/压缩/接入）。
- Task 2.3（缓存）→ 2.6（清理联动）；2.6 还依赖 Task 2.4 透传的 `(session_id, agent_id)` 目录约定。
- Phase 3 依赖 Phase 2 的 files_api 分支占位（2.1 中预留）。
- Task 3.0（DeepSeek file 块 smoke）→ 3.1 → 3.2 → 3.4；3.3 可与 3.2 并行。**Task 3.0 轻量 smoke 确认 wire 形态，一般预期直接通过。**
- **关键路径收敛点：Task 2.4**（`get_stream_response` 接入），2.2/2.3/2.5 完成后替换 2.1 的桩即达；2.6 在其后收尾。
- **Phase 4 依赖 Task 1.1（ref 编码）、Task 1.4（`/files/raw` 展示端点）；Task 4.1 → 4.2 → 4.3 → 4.4 顺序执行。Phase 4 可与 Phase 2/3 并行。**

## 风险与应对

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| 图片超阈值 | 请求失败 | 先 Pillow 压缩降采样（长边 2048/q85）压到阈值内；仍超则**报错提醒**（无 url 兜底） |
| 服务端拉取 R2 仍慢 | 物化变慢 | 本地文件优先 + per-agent 持久化缓存 + 超时**报错**，不静默降级 |
| ref 编码/解码不兼容历史数据 | 旧会话图片丢失 | `is_media_ref` 判别，非 ref 一律按原 url 处理 |
| Files API 各供应商差异大 | 实现蔓延 | 统一 `FilesApiStrategy` 接口，按 `files_api.type` 选择；本期只落地 DeepSeek，其余列为扩展 |
| litellm 发出的 `file` 块形态与 DeepSeek 要求不一致 | file_id 引用失败 | 用**双 key** 块（`file:{file_id:...}` + 顶层 `file_id`）：抓包确认 litellm 保留顶层 `file_id`，DeepSeek 可识别；残留风险是 DeepSeek 是否容忍多余 `file` 字段，由 Task 3.0 smoke 确认，不容忍则回退原生 HTTP/猴补/base64 |
| 物化就地修改 messages 污染历史 | 上下文错乱 | 强制深拷贝 content，单测断言原对象不变 |
| 缓存磁盘增长 | 占满磁盘 | 全量缓存但 **TTL≤3 天**，`gc_expired()` 启动/定期清理；`clear_context`/删除 session 联动清理 |
| 缓存跨进程/跨 agent 串味 | 数据错乱/泄露 | 按 `<session_id>/<agent_id>` 独立目录隔离；key 含 `(provider, sha256)` |
| 缓存 TTL（3 天）与本地文件保留期（2 天）不一致 | 缓存命中可用、未命中但源文件已删→报错，行为不一致 | 明确「命中缓存优先；未命中且源文件已过期→抛 `MediaFileTooLargeError`/明确错误提示重新上传」；e2e 覆盖该场景 |
| local ref 的 `path` 在物化时已被删除/移动 | 图片丢失 | `_read_bytes` 抛明确错误提醒；`read_image` 刚读的本地文件通常仍存在 |
| 后端与 agent 子进程不共享文件系统（容器/远程） | `/files/raw` 读不到本地图 | 与现有 `/files/preview` 同假设；跨机部署时建议配置云存储走 cloud ref |
| 本地落盘占满磁盘 | 服务异常 | `/files/upload` 限制单文件大小 + **上传目录保留期 ≤2 天**（删除旧日期目录）；`local` ref 超期文件物化时报错提示重新上传 |
| 前端云直传与后端上传返回结构不一致 | ref 构造失败 | 统一 `UploadResult` 契约（含可选 `storage_key/local_path/sha256`），旧字段不变 |
| 依赖未声明（Pillow/httpx） | 压缩/HTTP 取字节功能直接不可用，运行期 ImportError | Phase 2 新增 Task 2.0 在 `pyproject.toml` 声明 `pillow`、`httpx`，并加安装/导入验证 AC 与 CI 校验 |
| `/files/raw` 无根目录限制 | 任意文件读取，泄露本机敏感文件 | 定义允许根白名单 + `resolved.is_relative_to(root)` 校验，越界 403；补充路径穿越测试（见 C2） |

## 未解决的问题

> 已决策项（如 DeepSeek 作为首批 Files API 实现、其余供应商按同一 `FilesApiStrategy` 后续扩展）已并入「总体方案 / Phase 3」，此处仅保留真正待执行确认的开放项。

- **DeepSeek file 块下发（已定方案，待 smoke 收尾）**：采用**双 key** 块 `{"type":"file","file":{"file_id":...},"file_id":...}`——`file` 包装满足 litellm openai provider 校验，顶层 `file_id` 满足 DeepSeek 官方裸格式（抓包确认 litellm 两者都保留）。唯一待确认：DeepSeek 是否容忍多余的 `file` 字段，由 Task 3.0 一次 smoke 定论；若不容忍则回退原生 HTTP 直发裸 `file_id` / 猴补 / 内联 base64。
- **deepseek 模型模态配置对齐（待执行确认）**：DeepSeek 视觉能力绑定 `deepseek-flash` 模型；须在执行时确认当前 `configs/llm_config.json` 中 deepseek 模型的 `model` 名与 `meta.modality.image` 配置对齐，否则物化会因"模态不支持"降级为文本链接。
