"""
Read Image Tool

Reads a local image file, uploads it to cloud S3 storage (Cloudflare R2 or
Supabase), and injects an image_url message into the LLM context so the
model can "see" the image.
"""

import asyncio
import mimetypes
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from broca.configs import get_configs
from broca.logging_config import get_logger
from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus

logger = get_logger(__name__)

SUPPORTED_IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".svg",
}


def _generate_unique_filename(original_name: str) -> str:
    """Generate a unique, ASCII-safe filename matching frontend logic."""
    name, dot, ext = original_name.rpartition(".")
    if not dot:
        name, ext = original_name, ""
    sanitized = quote(name, safe="")
    unique_id = uuid.uuid4().hex[:6]
    return f"{sanitized}_{unique_id}.{ext}" if ext else f"{sanitized}_{unique_id}"


def _generate_storage_path(original_name: str) -> str:
    """Generate S3 storage path: uploads/YYYYMMDD/{encoded_filename}_{uuid6}.ext"""
    safe_filename = _generate_unique_filename(original_name)
    date_str = datetime.now().strftime("%Y%m%d")
    return f"uploads/{date_str}/{safe_filename}"


class ReadImage(Tool):
    """Read a local image file and upload it to cloud storage so the LLM can see it."""

    @property
    def name(self) -> str:
        return "read_image"

    @property
    def description(self) -> str:
        return (
            "Reads a local image file (PNG, JPG, JPEG, GIF, WebP, BMP, SVG), "
            "uploads it to cloud storage, and injects the image into the "
            "conversation so the LLM can see it. "
            "Use this when you need to visually inspect a local image file."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": (
                        "The absolute or workspace-relative path to the image file"
                    ),
                },
            },
            "required": ["file_path"],
        }

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _resolve_file_path(self, file_path: str, workspace: str | None) -> Path | None:
        """Resolve file_path to an absolute Path, supporting workspace-relative."""
        p = Path(file_path)
        if p.is_absolute():
            return p
        if workspace:
            resolved = Path(workspace) / p
            if resolved.exists():
                return resolved
        # Fallback: treat as relative to CWD
        return p

    def _check_modality(self, context: ToolCallContext) -> bool:
        """Check if the current LLM model supports image input."""
        try:
            agent = context.agent
            if not agent:
                return False
            llm_client = agent.llm_client
            provider = agent.config.provider
            model = agent.config.model
            modality = (
                llm_client.config[provider]["models"][model]["meta"]["modality"]
            )
            return "image" in modality
        except (KeyError, AttributeError, TypeError):
            logger.warning("Could not check image modality, assuming not supported")
            return False

    def _create_s3_client(self, storage) -> "boto3.client":
        """Create a boto3 S3 client based on StorageConfig."""
        import boto3
        from boto3.s3.transfer import TransferConfig

        if storage.backend == "cloudflare":
            endpoint = f"https://{storage.cloudflare_account_id}.r2.cloudflarestorage.com"
            access_key_id = storage.cloudflare_access_key_id
            secret_key = storage.cloudflare_secret_access_key
        elif storage.backend == "supabase":
            endpoint = f"{storage.supabase_url}/storage/v1/s3"
            access_key_id = storage.supabase_s3_access_key_id
            secret_key = storage.supabase_s3_secret_access_key
        else:
            raise ValueError(f"Unsupported storage backend: {storage.backend}")

        from botocore.client import Config as BotocoreConfig

        return boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name="auto",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_key,
            config=BotocoreConfig(s3={"addressing_style": "path"}),
        )

    def _get_public_url_base(self, storage) -> str:
        """Get the public URL base for uploaded files."""
        if storage.backend == "cloudflare":
            return storage.cloudflare_public_url or (
                f"https://{storage.cloudflare_bucket}.{storage.cloudflare_account_id}.r2.dev"
            )
        elif storage.backend == "supabase":
            return f"{storage.supabase_url}/storage/v1/object/public/{storage.supabase_bucket}"
        raise ValueError(f"Unsupported storage backend: {storage.backend}")

    def _get_bucket(self, storage) -> str:
        if storage.backend == "cloudflare":
            return storage.cloudflare_bucket or "upload"
        elif storage.backend == "supabase":
            return storage.supabase_bucket or "upload"
        raise ValueError(f"Unsupported storage backend: {storage.backend}")

    # ------------------------------------------------------------------
    # main execution
    # ------------------------------------------------------------------

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        file_path_str = arguments["file_path"]
        workspace = context.workspace

        # 1. Validate file
        file_path = self._resolve_file_path(file_path_str, workspace)
        if not file_path or not file_path.exists() or not file_path.is_file():
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"文件不存在: {file_path_str}",
            )

        ext = file_path.suffix.lower()
        if ext not in SUPPORTED_IMAGE_EXTENSIONS:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"文件不是图片文件（不支持的格式: {ext}）。"
                f"支持的格式: {', '.join(sorted(SUPPORTED_IMAGE_EXTENSIONS))}",
            )

        # 2. Validate storage config
        storage = get_configs().storage
        if not storage.backend or storage.backend not in ("cloudflare", "supabase"):
            return ToolResult(
                status=ToolStatus.ERROR,
                content="云端存储未配置。请在设置中配置 Cloudflare R2 或 Supabase 存储。",
            )

        # 3. MIME type
        mime_type, _ = mimetypes.guess_type(str(file_path))
        if not mime_type:
            mime_type = "image/png"  # fallback

        # 4-6. S3 upload (wrapped in to_thread to avoid blocking the event loop)
        storage_path = _generate_storage_path(file_path.name)
        bucket = self._get_bucket(storage)

        def _sync_upload():
            s3_client = self._create_s3_client(storage)
            s3_client.upload_file(
                str(file_path),
                bucket,
                storage_path,
                ExtraArgs={"ContentType": mime_type},
            )

        try:
            await asyncio.to_thread(_sync_upload)
        except Exception as e:
            logger.error(f"Image upload failed: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"图片上传失败: {e}",
            )

        # 7. Public URL
        public_url_base = self._get_public_url_base(storage)
        public_url = f"{public_url_base}/{storage_path}"

        # Check if model supports image input
        supports_image = self._check_modality(context)

        if not supports_image:
            # Model does not support image: return the URL as text only
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"图片已上传（当前模型不支持图片输入）: {public_url}",
            )

        # Build LLM message (multimodal user message with image_url)
        image_url_part = {
            "type": "image_url",
            "image_url": {"url": public_url},
        }
        # Merge modality config (e.g. detail level) if present
        try:
            agent = context.agent
            modality = (
                agent.llm_client.config[agent.config.provider]["models"][
                    agent.config.model
                ]["meta"]["modality"]
            )
            image_meta = modality.get("image", {})
            if image_meta:
                image_url_part.update(image_meta)
        except (KeyError, AttributeError, TypeError):
            pass

        llm_message = {
            "role": "user",
            "content": [
                image_url_part,
                {"type": "text", "text": f"Image Readed"},
            ],
        }

        db_data = {
            "content": "Image Readed",
            "files": [
                {
                    "name": file_path.name,
                    "url": public_url,
                    "type": mime_type,
                }
            ],
        }

        return ToolResult(
            status=ToolStatus.SUCCESS,
            content=f"图片已读取",
            extra_context_messages=[
                {
                    "llm_message": llm_message,
                    "data": db_data,
                    "role": "user",
                }
            ],
        )
