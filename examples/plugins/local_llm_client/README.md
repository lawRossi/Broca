# Local LLM Client Plugin (Example)

示例插件：使用本地 Ollama 模型替代云端 LLM API。

## 前提

安装并运行 [Ollama](https://ollama.com)：

```bash
# macOS
brew install ollama
ollama serve &

# 拉取模型
ollama pull llama3
```

## 安装插件

```bash
pip install -e examples/plugins/local_llm_client/
```

## 配置

### 方式 1：Entry Point（自动）

安装后自动生效，使用默认 `llama3` 模型。

### 方式 2：components.json

```json
{
    "llm_client": "local_llm.LocalLLMClient"
}
```

### 方式 3：自定义模型

```python
from local_llm import LocalLLMClient

client = LocalLLMClient(model="mistral", base_url="http://gpu-node:11434")
```

## 运行测试

```bash
pytest examples/plugins/local_llm_client/ -v
```

> 测试使用 mock，不需要运行 Ollama。

## 与 LiteLLM 的对比

| 特性 | LiteLLMClient（默认） | LocalLLMClient（本插件） |
|------|----------------------|------------------------|
| 云端 API | ✅ (OpenAI, Anthropic, ...) | ❌ |
| 本地模型 | ❌ | ✅ (Ollama) |
| API Key | 需要 | 不需要 |
| 流式响应 | ✅ | ✅ |
