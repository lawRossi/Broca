import json
import os
from pathlib import Path

from broca.configs import get_configs
from fastapi import APIRouter, HTTPException
from loguru import logger

from app.schemas.schemas import ApiResponse

router = APIRouter()

# 优先级: BROCA_LLM_CONFIG 环境变量 > configs.json 中的配置
_llm_config_path = os.getenv("BROCA_LLM_CONFIG")
if not _llm_config_path:
    configs = get_configs()
    _llm_config_path = configs.llm_config_file
LLM_CONFIG_PATH = Path(_llm_config_path)


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
