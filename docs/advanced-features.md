> [← 返回 README](../README.md)

# 决策、通信与媒体处理

## 决策组件

**核心文件**: `broca/components/decision_provider.py`, `broca/decision.py`

决策组件提供快速结构化决策能力（System One），基于 [typesafe-sdk](https://github.com/typesafe-ai/typesafe-sdk-python) 接入所有兼容 `/v1/systemone` 协议的决策模型（Kev、Laya、TypeSafe Jev、OpenRouter 等）。

### 三种问题类型

| 类型 | 说明 | 返回值 | 示例场景 |
|------|------|--------|----------|
| **Choice** | 从预定义选项中选一个 | 选中项 + 概率分布 + 置信度 | 路由到哪个团队/工具 |
| **Noul** | 是/否判断（输出概率值） | 概率 (0~1) | 是否紧急/是否退款 |
| **Score** | 在有序量表上定位 | 分数 + 概率分布 + 置信度 | 风险等级/情绪强度 |

### 使用方式

```python
from broca.decision import DecisionClient
from broca.components.decision_provider import DecisionQuestion, QuestionType

client = DecisionClient()
await client.initialize()

results = await client.decide(
    state="用户请求: 我被重复扣费了，请退款",
    questions=[
        DecisionQuestion(name="is_refund", type=QuestionType.NOUL,
                         instructions="Is this a refund request?"),
        DecisionQuestion(name="team", type=QuestionType.CHOICE,
                         instructions="Which team handles this?",
                         criteria={"billing": "Payment issues", "tech": "Bugs"}),
        DecisionQuestion(name="risk", type=QuestionType.SCORE,
                         instructions="Risk level?",
                         criteria=["low", "medium", "high", "critical"]),
    ],
)

for r in results:
    print(f"{r.question_name}: answer={r.answer}, confidence={r.confidence}, escalate={r.escalate}")
```

### 配置

通过 `configs/decision_config.json` 配置（格式同 `llm_config.json`），支持多 provider 同时接入：

```json
{
  "__default__": {"provider": "kev", "model": "kev-4b"},
  "kev": {
    "base_url": "http://localhost:8009",
    "api_key": "",
    "models": {"kev-4b": {"model": "kev-latest", "timeout": 30}}
  }
}
```

### 架构

```
Agent (策略/Hook)
     │
     ▼
DecisionProvider (ABC, singleton scope)
     │
     ▼
DecisionClient (typesafe-sdk AsyncTypeSafeClient)
     │
     ├── Kev (本地, base_url=localhost:8009)
     ├── Laya (本地/云端)
     ├── TypeSafe Jev (api.typesafe.ai)
     └── OpenRouter / SiliconFlow (网关)
```

- **接口层**：`DecisionProvider` ABC 定义在 `broca/components/`，具体实现在 `broca/decision.py`
- **ComponentRegistry 注册**：singleton scope，entry point `decision_provider`
- **内置重试**：typesafe-sdk 自动处理连接错误和可重试 HTTP 状态码（指数退避）
- **置信度门控**：`confidence < threshold` 时自动标记 `escalate=True`，供上层回退到 LLM

## Agent 间通信

**核心文件**: `broca/agent_messenger/`（`messenger.py`、`message_models.py`、`call_chain.py`、`audit.py`），接口定义在 `broca/components/agent_messenger.py`

Agent 间通信以 per-agent 组件 `DefaultAgentMessenger` 注入每个 Agent，并通过 `communicate` 工具暴露给 LLM。统一的消息模型 `AgentCommunication` 映射为四种 Socket.IO 消息类型：

| 模式 | 消息类型 | 语义 |
|------|----------|------|
| `request` | `AGENT_REQUEST` / `AGENT_REQUEST_RESPONSE` | 阻塞等待目标 Agent 回复，按 `request_id` 配对，返回 `(回复文本, status)` |
| `notify` | `AGENT_NOTIFY` | 仅等待投递 ACK，不等待业务回执，立即返回 |
| `delegate` | `AGENT_DELEGATE` | 委派**已存在**的任务（必须带 `task_id`），接收方用 `notify(kind="delegate_receipt")` 回执 |

核心机制：

- **投递 ACK**：仅在收到 `{"status": "routed"}` 时视为投递成功（2s 超时），避免消息丢失
- **回复保障**：接收方用 `try/finally` 保证正常/中止/异常路径都会回复（request）或发送恰好一次回执（delegate）；`reply()` 永不抛异常
- **自消息拦截**：发给自己直接拒绝（`self_target`），防止自请求死锁或自通知循环
- **静态 ACL**：`allowed_targets` / `allowed_modes`（`None` 表示不限制）
- **环检测**：`request` 始终强制检查 `CallChain`（`chain_cycle` / `chain_depth_exceeded`，`max_chain_depth` 默认 3）；`Agent.run()` 自动把自身 id 前置到调用链
- **任务存在性校验**：delegate 前检查任务存在，否则 `task_not_found`
- **超时**：`request_timeout` 默认 300s；超时抛 `AgentCommunicationError`
- **审计**：所有通信尝试以 JSON 行追加到 `{workspace}/.broca/agent_messenger_audit.jsonl`（含结果、拒绝原因、耗时、调用深度），best-effort 不影响通信

Agent 级配置（YAML frontmatter）：

```yaml
communication_policy:
  allowed_targets: ["researcher", "writer"]  # 省略则不限
  allowed_modes: ["request", "notify"]       # 省略则不限
  request_timeout: 300.0
  max_chain_depth: 3
```

## 媒体处理

**核心文件**: `broca/media/`（`ref.py`、`materializer.py`、`files_api.py`、`deepseek_files.py`、`cache.py`、`storage.py`）

图片/文件以轻量、自包含的 `ref://` 字符串持久化在消息历史中（而非 base64 或会过期的公开 URL），仅在 LLM 请求发出前由 `MediaMaterializer` 物化为线上格式；调用方的上下文历史不会被修改。

- **引用格式**：`ref://` + unpadded base64url(JSON)，元数据含 `kind`（`cloud` / `local`）、`url`（展示用）、`sha256`、`mime`、`size`，以及 `key`（云端对象键）或 `path`（本地路径）
- **物化决策**（逐 part）：
  1. 模型未声明对应模态 → 降级为文本 `文件链接：<url>`
  2. 配置了 Files API 且大小未超 `max_size_mb`（默认 64） → 上传并注入 `file_id`
  3. 否则 base64 内联，阈值 `meta.media_limits.max_inline_mb`（默认 4）
  4. 超限时对图片按最长边 2048 压缩并多档质量重试；仍超限或读取/上传失败则抛错（**不会静默回退到裸 URL**）
- **Files API**：`FilesApiStrategy` 抽象 + `register_strategy` 注册，当前实现为 DeepSeek Files API（`multipart/form-data` 上传，支持 `expires_after`），响应中的 `file_id` 同时以 `{"type": "file", "file": {"file_id": ...}}` 形式提供给 LiteLLM
- **缓存**：`MediaCache` 按 `{root}/{session_id}/{agent_id}/` 分目录持久化，TTL 3 天，原子写入；base64、file_id、压缩字节均可缓存；会话删除时由 `SessionCleanupService` 一并清理
- **云端读取**：`storage.py` 支持 S3 兼容存储（Cloudflare / Supabase）与 httpx HTTP 回退

`LiteLLMClient` 在 `acompletion()` / `get_stream_response()` 前调用 `materialize_messages()`；`read_image` 工具负责生成引用元数据并注入多模态消息。相关配置见 [媒体配置](configuration.md#媒体配置)。
