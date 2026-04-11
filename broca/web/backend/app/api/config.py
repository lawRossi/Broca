import json
from pathlib import Path

from broca.configs import get_configs
from fastapi import APIRouter, HTTPException
from loguru import logger

from app.schemas.schemas import ApiResponse

router = APIRouter()

configs = get_configs()
LLM_CONFIG_PATH = Path(configs.llm_config_file)


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
        logger.error(f"Error getting LLM providers: {e}")
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

        # 提取模型配置（排除base_url和api_key）
        models = []
        for model_id, model_config in provider_config.items():
            if model_id not in ["base_url", "api_key"] and isinstance(model_config, dict):
                model_name = model_id
                models.append({"id": model_id, "name": model_name})

        return ApiResponse.success(models, msg=f"Models for provider '{provider}' retrieved successfully")
    except Exception as e:
        logger.error(f"Error getting LLM models: {e}")
        raise HTTPException(500, f"Internal server error: {e!s}") from e
