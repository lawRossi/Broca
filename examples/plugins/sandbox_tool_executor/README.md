# Sandbox ToolExecutor Plugin (Example)

示例插件：所有工具在沙箱环境中执行。

## 安装

```bash
pip install -e examples/plugins/sandbox_tool_executor/
```

## 配置

安装后，entry point 自动注册。也可通过 `components.json` 显式指定：

```json
{
    "tool_executor": "sandbox_executor:SandboxToolExecutor"
}
```

## 运行测试

```bash
pytest examples/plugins/sandbox_tool_executor/ -v
```

## 工作原理

`SandboxToolExecutor` 实现了 `ToolExecutor` ABC：

1. `initialize()` — 注入 `tool_mapping`、`permission_provider`、`config`、`communicator`
2. `execute_tool()` — 在沙箱中执行工具（示例中为模拟执行）
3. `get_permission()` / `is_readonly_tool()` — 权限查询

生产环境中，将 `_sandbox_run()` 替换为实际的沙箱实现（Docker / Firecracker / gVisor）。
