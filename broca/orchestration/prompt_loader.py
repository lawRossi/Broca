"""
Prompt Loader — 编排器提示词模板加载器

使用 Jinja2 从 prompts/ 目录加载按编排类型分组的模板。
所有编排器通过此加载器获取提示词，实现提示词与代码分离。
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from jinja2 import Environment, FileSystemLoader, TemplateNotFound

from broca.logging_config import get_logger

logger = get_logger(__name__)

# prompts/ 目录的绝对路径
_PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")


class PromptLoader:
    """
    编排器提示词模板加载器

    按编排类型分组加载 Jinja2 模板，支持传入上下文变量渲染。

    用法:
        prompt = PromptLoader.render("graph", "task_context.j2", step=..., ...)
    """

    # Jinja2 环境缓存（按类型），避免重复创建
    _envs: Dict[str, Environment] = {}

    @classmethod
    def _get_env(cls, orchestrator_type: str) -> Environment:
        """
        获取指定编排类型的 Jinja2 环境。

        Args:
            orchestrator_type: 编排类型名称（如 'pipeline', 'round_table'）

        Returns:
            Jinja2 Environment 实例
        """
        if orchestrator_type not in cls._envs:
            template_dir = os.path.join(_PROMPTS_DIR, orchestrator_type)
            if not os.path.isdir(template_dir):
                raise ValueError(
                    f"Prompt directory not found for orchestrator type "
                    f"'{orchestrator_type}': {template_dir}"
                )
            cls._envs[orchestrator_type] = Environment(
                loader=FileSystemLoader(template_dir),
                trim_blocks=True,
                lstrip_blocks=True,
                keep_trailing_newline=False,
            )
        return cls._envs[orchestrator_type]

    @classmethod
    def render(
        cls,
        orchestrator_type: str,
        template_name: str,
        **kwargs: Any,
    ) -> str:
        """
        渲染指定编排类型的提示词模板。

        Args:
            orchestrator_type: 编排类型名称（如 'pipeline', 'round_table'）
            template_name: 模板文件名（如 'task_context.j2'）
            **kwargs: 模板上下文变量

        Returns:
            渲染后的提示词字符串

        Raises:
            ValueError: 模板目录不存在或模板未找到
        """
        env = cls._get_env(orchestrator_type)
        try:
            template = env.get_template(template_name)
            return template.render(**kwargs)
        except TemplateNotFound as e:
            raise ValueError(
                f"Template '{template_name}' not found for orchestrator type "
                f"'{orchestrator_type}'. Available templates: "
                f"{os.listdir(os.path.join(_PROMPTS_DIR, orchestrator_type))}"
            ) from e

    @classmethod
    def render_or_default(
        cls,
        orchestrator_type: str,
        template_name: str,
        default: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """
        安全渲染，模板不存在时返回默认值。

        Args:
            orchestrator_type: 编排类型名称
            template_name: 模板文件名
            default: 默认值（模板不存在时返回）
            **kwargs: 模板上下文变量

        Returns:
            渲染后的提示词字符串或默认值
        """
        try:
            return cls.render(orchestrator_type, template_name, **kwargs)
        except (ValueError, TemplateNotFound) as e:
            if default is not None:
                logger.warning(
                    f"Template '{template_name}' not found for "
                    f"'{orchestrator_type}', using default. Error: {e}"
                )
                return default
            raise

    @classmethod
    def list_templates(cls, orchestrator_type: str) -> list[str]:
        """
        列出指定编排类型的所有可用模板。

        Args:
            orchestrator_type: 编排类型名称

        Returns:
            模板文件名列表
        """
        template_dir = os.path.join(_PROMPTS_DIR, orchestrator_type)
        if not os.path.isdir(template_dir):
            return []
        return sorted([
            f for f in os.listdir(template_dir)
            if f.endswith(".j2")
        ])
