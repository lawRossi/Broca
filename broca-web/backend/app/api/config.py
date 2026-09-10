import copy
import json
import os
from pathlib import Path
from typing import Any

from broca.configs import get_configs
from fastapi import APIRouter, HTTPException
from loguru import logger

from app.schemas.schemas import (
    ApiResponse,
    GeneralConfigUpdateRequest,
    LLMConfigUpdateRequest,
    McpConfigUpdateRequest,
    ToolPermissionUpdateRequest,
)

router = APIRouter()

# 优先级: BROCA_LLM_CONFIG 环境变量 > configs.json 中的配置
_llm_config_path = os.getenv("BROCA_LLM_CONFIG")
if not _llm_config_path:
    configs = get_configs()
    _llm_config_path = configs.llm_config_file
LLM_CONFIG_PATH = Path(_llm_config_path)

# ---------- general（configs.json）与 tool-permission（工具权限）配置 ----------

# 已知的 general 配置字段（保存时仅写回这些字段，未知字段丢弃；保持该顺序写回）
KNOWN_GENERAL_CONFIG_FIELDS = (
    "database_dir",
    "log_file",
    "log_level",
    "llm_config_file",
    "socket_server_url",
    "api_server_url",
    "execution",
)
# execution 分组下的已知字段（数字型，执行引擎相关；顺序保持写回）
KNOWN_EXECUTION_CONFIG_FIELDS = (
    "step_max_errors",
    "llm_retry_delay",
    "tool_call_timeout",
    "assign_task_timeout",
    "llm_timeout",
    "llm_first_chunk_timeout",
    "dead_loop_window",
    "message_queue_size",
)
VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
VALID_PERMISSIONS = {"allow", "ask", "forbidden"}


def _resolve_general_config_path() -> Path:
    """按优先级解析 general 配置路径：
    BROCA_CONFIG 环境变量 > ~/.broca/configs/configs.json（TUI/运行时新路径，优先于 legacy）
    > ~/.broca/configs.json（legacy）> 项目默认 configs/configs.json。
    写回目标 = 解析出的路径（不存在时也用它作为创建路径）。
    """
    env_path = os.getenv("BROCA_CONFIG")
    if env_path:
        return Path(env_path).expanduser()
    new_path = Path.home() / ".broca" / "configs" / "configs.json"
    if new_path.exists():
        return new_path
    legacy_path = Path.home() / ".broca" / "configs.json"
    if legacy_path.exists():
        return legacy_path
    # 项目默认 configs/configs.json（与 broca.configs.get_configs 的默认路径一致）
    return Path(__file__).resolve().parents[4] / "configs" / "configs.json"


GENERAL_CONFIG_PATH = _resolve_general_config_path()
# 工具权限全局路径（与 ToolPermissionManager 一致）
TOOL_PERMISSION_PATH = Path.home() / ".broca" / "configs" / "tool_permission_config.json"
# MCP 服务器全局配置路径（与 ToolManager._load_mcp_config 的全局回退路径一致）
MCP_CONFIG_PATH = Path.home() / ".broca" / "configs" / "mcp_config.json"


def _read_json_config(path: Path) -> dict[str, Any]:
    """读取 JSON 配置文件：不存在 → 404；损坏 → 500；非 object → 500"""
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Config file not found: {path}")
    try:
        with open(path, encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Config file is not valid JSON: {e}") from e
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to read config file: {e}") from e
    if not isinstance(config, dict):
        raise HTTPException(status_code=500, detail="Config file content must be an object")
    return config


def _atomic_write_json(path: Path, config: dict[str, Any]) -> None:
    """备份（.bak）并原子写入 JSON 配置文件（.tmp + os.replace，父目录自动创建）"""
    path.parent.mkdir(parents=True, exist_ok=True)

    # 写入前备份旧配置
    if path.exists():
        backup_path = path.with_suffix(".json.bak")
        backup_path.write_bytes(path.read_bytes())

    # 临时文件 + os.replace 原子替换，避免写一半导致配置损坏
    tmp_path = path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)
        f.write("\n")
    os.replace(tmp_path, path)


def _read_llm_config() -> dict[str, Any]:
    """读取完整 LLM 配置文件内容"""
    return _read_json_config(LLM_CONFIG_PATH)


def _validate_llm_config(config: Any) -> None:
    """校验 LLM 配置结构，不合法时抛出 HTTPException(400)"""
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="LLM config must be an object")
    for provider_id, provider_config in config.items():
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise HTTPException(status_code=400, detail="Provider id must be a non-empty string")
        if not isinstance(provider_config, dict):
            raise HTTPException(status_code=400, detail=f"Provider '{provider_id}' must be an object")
        base_url = provider_config.get("base_url")
        api_key = provider_config.get("api_key")
        models = provider_config.get("models")
        if not isinstance(base_url, str) or not base_url.strip():
            raise HTTPException(
                status_code=400, detail=f"Provider '{provider_id}' requires a non-empty string 'base_url'"
            )
        if not isinstance(api_key, str):
            raise HTTPException(status_code=400, detail=f"Provider '{provider_id}' requires a string 'api_key'")
        if not isinstance(models, dict):
            raise HTTPException(status_code=400, detail=f"Provider '{provider_id}' requires an object 'models'")
        for model_id, model_config in models.items():
            if not isinstance(model_id, str) or not model_id.strip():
                raise HTTPException(
                    status_code=400, detail=f"Model id of provider '{provider_id}' must be a non-empty string"
                )
            if not isinstance(model_config, dict):
                raise HTTPException(
                    status_code=400, detail=f"Model '{model_id}' of provider '{provider_id}' must be an object"
                )
            # meta.modality 为运行时必需字段（broca.llm.LLMClient 直接读取，缺失会导致 KeyError）
            meta = model_config.get("meta")
            if not isinstance(meta, dict):
                raise HTTPException(
                    status_code=400,
                    detail=f"Model '{model_id}' of provider '{provider_id}' requires an object 'meta'",
                )
            modality = meta.get("modality")
            if not isinstance(modality, dict):
                raise HTTPException(
                    status_code=400,
                    detail=f"Model '{model_id}' of provider '{provider_id}' requires an object 'meta.modality'",
                )


def _write_llm_config(config: dict[str, Any]) -> None:
    """备份并原子写入 LLM 配置文件"""
    _atomic_write_json(LLM_CONFIG_PATH, config)


def _validate_execution_config(config: Any) -> None:
    """校验 execution 分组：必须 object；字段若存在必须为数字且非负；未知字段记录 warning。"""
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="General config field 'execution' must be an object")
    for key, value in config.items():
        if key in KNOWN_EXECUTION_CONFIG_FIELDS:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Execution config field '{key}' must be a non-negative number",
                )
        else:
            logger.warning("Unknown execution config field '%s' will be dropped on save", key)


def _validate_general_config(config: Any) -> None:
    """校验 general 配置：必须 object；已知字段若存在必须为 string；log_level 必须合法；
    execution 分组有独立的 object 校验；未知字段仅记录 warning（写回时丢弃）。"""
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="General config must be an object")
    for key, value in config.items():
        if key not in KNOWN_GENERAL_CONFIG_FIELDS:
            logger.warning("Unknown general config field '%s' will be dropped on save", key)
    for key, value in config.items():
        if key == "execution":
            _validate_execution_config(value)
        elif key in KNOWN_GENERAL_CONFIG_FIELDS:
            if not isinstance(value, str):
                raise HTTPException(
                    status_code=400, detail=f"General config field '{key}' must be a string"
                )
    log_level = config.get("log_level")
    if log_level is not None and log_level not in VALID_LOG_LEVELS:
        raise HTTPException(
            status_code=400,
            detail=f"log_level must be one of {sorted(VALID_LOG_LEVELS)}, got '{log_level}'",
        )


def _filter_general_config(config: dict[str, Any]) -> dict[str, Any]:
    """仅保留已知字段，并按 KNOWN_GENERAL_CONFIG_FIELDS 顺序写回；
    execution 分组进一步过滤为已知 execution 字段。"""
    result: dict[str, Any] = {}
    for key in KNOWN_GENERAL_CONFIG_FIELDS:
        if key not in config:
            continue
        if key == "execution":
            exec_src = config[key]
            if isinstance(exec_src, dict):
                result[key] = {
                    fk: exec_src[fk]
                    for fk in KNOWN_EXECUTION_CONFIG_FIELDS
                    if fk in exec_src
                }
        else:
            result[key] = config[key]
    return result


def _validate_tool_permission_config(config: Any) -> None:
    """校验工具权限配置：必须 object；tools 必须为 dict（可为空）且每个权限值合法；
    _description 若存在必须 string；_permission_values 若存在必须 object 且值均为 string。"""
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="Tool permission config must be an object")
    tools = config.get("tools", {})
    if not isinstance(tools, dict):
        raise HTTPException(
            status_code=400, detail="Tool permission config 'tools' must be an object"
        )
    for tool_name, permission in tools.items():
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise HTTPException(
                status_code=400, detail="Tool name must be a non-empty string"
            )
        if permission not in VALID_PERMISSIONS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Permission for tool '{tool_name}' must be one of "
                    f"{sorted(VALID_PERMISSIONS)}, got '{permission}'"
                ),
            )
    description = config.get("_description")
    if description is not None and not isinstance(description, str):
        raise HTTPException(status_code=400, detail="'_description' must be a string")
    permission_values = config.get("_permission_values")
    if permission_values is not None:
        if not isinstance(permission_values, dict):
            raise HTTPException(status_code=400, detail="'_permission_values' must be an object")
        for key, value in permission_values.items():
            if not isinstance(value, str):
                raise HTTPException(
                    status_code=400,
                    detail=f"'_permission_values.{key}' must be a string",
                )


def _validate_mcp_string_map(server_name: str, value: Any, field: str) -> None:
    """校验 MCP 服务器的 env/headers 字段：可为空，若存在必须是 string → string 的对象。"""
    if value is None:
        return
    if not isinstance(value, dict):
        raise HTTPException(
            status_code=400, detail=f"MCP server '{server_name}' field '{field}' must be an object"
        )
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise HTTPException(
                status_code=400,
                detail=f"MCP server '{server_name}' field '{field}' must be an object of strings",
            )


def _validate_mcp_config(config: Any) -> None:
    """校验 MCP 配置结构，不合法时抛出 HTTPException(400)。

    顶层必须为 object；每个服务器名为非空字符串、配置为 object，且必须提供
    'command'（stdio）或 'url'（HTTP）之一。

    - stdio：command 非空 string；args 若存在必须是 string 列表；env 若存在必须是
      string→string；cwd 若存在必须是 string。
    - HTTP：url 非空 string；headers 若存在必须是 string→string。
    - 两者共有：tool_timeout 若存在必须是正数（bool 不接受）。
    """
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="MCP config must be an object")
    for server_name, server_config in config.items():
        if not isinstance(server_name, str) or not server_name.strip():
            raise HTTPException(
                status_code=400, detail="MCP server name must be a non-empty string"
            )
        if not isinstance(server_config, dict):
            raise HTTPException(
                status_code=400, detail=f"MCP server '{server_name}' must be an object"
            )

        command = server_config.get("command")
        url = server_config.get("url")
        if command is None and url is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"MCP server '{server_name}' requires either a 'command' (stdio) "
                    f"or a 'url' (HTTP)"
                ),
            )

        if command is not None:
            if not isinstance(command, str) or not command.strip():
                raise HTTPException(
                    status_code=400,
                    detail=f"MCP server '{server_name}' field 'command' must be a non-empty string",
                )
            args = server_config.get("args")
            if args is not None and (
                not isinstance(args, list) or not all(isinstance(a, str) for a in args)
            ):
                raise HTTPException(
                    status_code=400,
                    detail=f"MCP server '{server_name}' field 'args' must be a list of strings",
                )
            _validate_mcp_string_map(server_name, server_config.get("env"), "env")
            cwd = server_config.get("cwd")
            if cwd is not None and not isinstance(cwd, str):
                raise HTTPException(
                    status_code=400,
                    detail=f"MCP server '{server_name}' field 'cwd' must be a string",
                )

        if url is not None:
            if not isinstance(url, str) or not url.strip():
                raise HTTPException(
                    status_code=400,
                    detail=f"MCP server '{server_name}' field 'url' must be a non-empty string",
                )
            _validate_mcp_string_map(server_name, server_config.get("headers"), "headers")

        tool_timeout = server_config.get("tool_timeout")
        if tool_timeout is not None and (
            isinstance(tool_timeout, bool)
            or not isinstance(tool_timeout, (int, float))
            or tool_timeout <= 0
        ):
            raise HTTPException(
                status_code=400,
                detail=f"MCP server '{server_name}' field 'tool_timeout' must be a positive number",
            )


@router.get("/llm/providers", response_model=ApiResponse)
async def get_llm_providers() -> ApiResponse:
    """获取可用的LLM提供商列表"""
    try:
        if not LLM_CONFIG_PATH.exists():
            raise HTTPException(status_code=404, detail="LLM config file not found")

        with open(LLM_CONFIG_PATH, encoding="utf-8") as f:
            config = json.load(f)

        # 将提供商ID转换为前端需要的格式
        providers = []
        for provider_id, _ in config.items():
            # 从配置中提取提供商显示名称
            provider_name = provider_id.capitalize()
            if provider_id == "z-ai":
                provider_name = "Z-AI"
            elif provider_id == "openrouter":
                provider_name = "OpenRouter"
            elif provider_id == "deepseek":
                provider_name = "DeepSeek"
            elif provider_id == "nvidia":
                provider_name = "NVIDIA"
            else:
                provider_name = provider_id

            providers.append({"id": provider_id, "name": provider_name})

        return ApiResponse.success(providers, msg="LLM providers retrieved successfully")
    except Exception as e:
        logger.exception("Error getting LLM providers")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.get("/llm/models/{provider}", response_model=ApiResponse)
async def get_llm_models(provider: str) -> ApiResponse:
    """获取指定提供商的可用模型"""
    try:
        if not LLM_CONFIG_PATH.exists():
            raise HTTPException(status_code=404, detail="LLM config file not found")

        with open(LLM_CONFIG_PATH, encoding="utf-8") as f:
            config = json.load(f)

        if provider not in config:
            raise HTTPException(status_code=404, detail=f"Provider '{provider}' not found")

        provider_config = config[provider]

        # 提取模型配置（从 models 字段中读取）
        models_config = provider_config.get("models", {})
        models = []
        for model_id, model_config in models_config.items():
            if isinstance(model_config, dict):
                models.append({"id": model_id, "name": model_id})

        return ApiResponse.success(models, msg=f"Models for provider '{provider}' retrieved successfully")
    except Exception as e:
        logger.exception("Error getting LLM models")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.get("/llm", response_model=ApiResponse)
async def get_llm_config() -> ApiResponse:
    """获取完整 LLM 配置（含提供商、模型、api_key）"""
    try:
        config = _read_llm_config()
        return ApiResponse.success(config, msg="LLM config retrieved successfully")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting LLM config")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.put("/llm", response_model=ApiResponse)
async def update_llm_config(request: LLMConfigUpdateRequest) -> ApiResponse:
    """保存完整 LLM 配置（写入前校验结构并自动备份旧文件）"""
    try:
        _validate_llm_config(request.config)
        _write_llm_config(copy.deepcopy(request.config))
        logger.info("LLM config saved to %s", LLM_CONFIG_PATH)
        return ApiResponse.success(msg="LLM config saved successfully")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error saving LLM config")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


# -------------------- general（configs.json）---------------------


@router.get("/general", response_model=ApiResponse)
async def get_general_config() -> ApiResponse:
    """获取基础配置文件（configs.json）内容"""
    try:
        config = _read_json_config(GENERAL_CONFIG_PATH)
        return ApiResponse.success(config, msg="General config retrieved successfully")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting general config")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.put("/general", response_model=ApiResponse)
async def update_general_config(request: GeneralConfigUpdateRequest) -> ApiResponse:
    """保存基础配置：校验 + 仅写回已知字段（未知字段丢弃）+ 备份 + 原子写"""
    try:
        _validate_general_config(request.config)
        filtered = _filter_general_config(request.config)
        _atomic_write_json(GENERAL_CONFIG_PATH, filtered)
        logger.info("General config saved to %s", GENERAL_CONFIG_PATH)
        return ApiResponse.success(msg="General config saved successfully")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error saving general config")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


# -------------------- tool-permission（工具权限）---------------------


@router.get("/tool-permission", response_model=ApiResponse)
async def get_tool_permission_config() -> ApiResponse:
    """获取工具权限配置文件（tool_permission_config.json）内容"""
    try:
        config = _read_json_config(TOOL_PERMISSION_PATH)
        return ApiResponse.success(config, msg="Tool permission config retrieved successfully")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting tool permission config")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.put("/tool-permission", response_model=ApiResponse)
async def update_tool_permission_config(request: ToolPermissionUpdateRequest) -> ApiResponse:
    """保存工具权限配置：校验 + 保留请求中全部字段（含元数据）+ 备份 + 原子写"""
    try:
        _validate_tool_permission_config(request.config)
        _atomic_write_json(TOOL_PERMISSION_PATH, copy.deepcopy(request.config))
        logger.info("Tool permission config saved to %s", TOOL_PERMISSION_PATH)
        return ApiResponse.success(msg="Tool permission config saved successfully")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error saving tool permission config")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


# -------------------- mcp（MCP 服务器配置）---------------------


@router.get("/mcp", response_model=ApiResponse)
async def get_mcp_config() -> ApiResponse:
    """获取 MCP 服务器配置文件（mcp_config.json）内容"""
    try:
        config = _read_json_config(MCP_CONFIG_PATH)
        return ApiResponse.success(config, msg="MCP config retrieved successfully")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting MCP config")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.put("/mcp", response_model=ApiResponse)
async def update_mcp_config(request: McpConfigUpdateRequest) -> ApiResponse:
    """保存 MCP 服务器配置：校验 + 保留请求中全部字段（含服务器顺序）+ 备份 + 原子写"""
    try:
        _validate_mcp_config(request.config)
        _atomic_write_json(MCP_CONFIG_PATH, copy.deepcopy(request.config))
        logger.info("MCP config saved to %s", MCP_CONFIG_PATH)
        return ApiResponse.success(msg="MCP config saved successfully")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error saving MCP config")
        raise HTTPException(500, f"Internal server error: {e!s}") from e
