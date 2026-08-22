import copy
import json
import os
from pathlib import Path
from typing import Any

from broca.configs import get_configs
from fastapi import APIRouter, HTTPException
from loguru import logger

from app.schemas.schemas import ApiResponse, LLMConfigUpdateRequest

router = APIRouter()

# 优先级: BROCA_LLM_CONFIG 环境变量 > configs.json 中的配置
_llm_config_path = os.getenv("BROCA_LLM_CONFIG")
if not _llm_config_path:
    configs = get_configs()
    _llm_config_path = configs.llm_config_file
LLM_CONFIG_PATH = Path(_llm_config_path)


def _read_llm_config() -> dict[str, Any]:
    """读取完整 LLM 配置文件内容"""
    if not LLM_CONFIG_PATH.exists():
        raise HTTPException(status_code=404, detail="LLM config file not found")
    try:
        with open(LLM_CONFIG_PATH, encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"LLM config file is not valid JSON: {e}") from e
    if not isinstance(config, dict):
        raise HTTPException(status_code=500, detail="LLM config file content must be an object")
    return config


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
    LLM_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    # 写入前备份旧配置
    if LLM_CONFIG_PATH.exists():
        backup_path = LLM_CONFIG_PATH.with_suffix(".json.bak")
        backup_path.write_bytes(LLM_CONFIG_PATH.read_bytes())

    # 临时文件 + os.replace 原子替换，避免写一半导致配置损坏
    tmp_path = LLM_CONFIG_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)
        f.write("\n")
    os.replace(tmp_path, LLM_CONFIG_PATH)


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
