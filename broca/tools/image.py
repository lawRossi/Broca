"""
Read Image Tool

Reads a local image file and injects an image_url message into the LLM
context so the model can "see" the image.

The injected ``image_url`` uses a lightweight ``ref://`` reference (see
``broca.media.ref``) instead of embedding bytes or a fragile public URL:

- If cloud storage (Cloudflare R2 / Supabase) is configured, the file is
  uploaded and the ref is ``kind="cloud"`` (with a public display URL).
- Otherwise no upload happens and the ref is ``kind="local"`` (display URL
  points at the backend ``/files/raw`` endpoint).

The actual wire representation (base64 / files_api file_id) is produced later,
only right before the request is sent to the LLM.
"""

import asyncio
import hashlib
import mimetypes
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from broca.configs import get_configs
from broca.logging_config import get_logger
from broca.media.ref import encode_media_ref
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


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Compute the SHA-256 hex digest of a file by reading it in chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _local_preview_url(abs_path: Path) -> str:
    """Build a backend ``/files/raw`` URL for a local file (frontend display)."""
    return f"/files/raw?path={quote(str(abs_path), safe='')}"



class ReadImage(Tool):
    """Read a local image file and upload it to cloud storage so the LLM can see it."""
    is_readonly = True

    @property
    def name(self) -> str:
        return "read_image"

    @property
    def description(self) -> str:
        return (
            "Reads a local image file (PNG, JPG, JPEG, GIF, WebP, BMP, SVG) "
            "and injects the image into the conversation so the LLM can see it. "
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
        """Create a boto3 S3 client based on StorageConfig (delegates to media.storage)."""
        from broca.media.storage import build_s3_client

        return build_s3_client(storage)

    def _get_public_url_base(self, storage) -> str:
        """Get the public URL base for uploaded files (delegates to media.storage)."""
        from broca.media.storage import get_public_url_base

        return get_public_url_base(storage)

    def _get_bucket(self, storage) -> str:
        from broca.media.storage import get_bucket

        return get_bucket(storage)

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

        # 2. MIME type
        mime_type, _ = mimetypes.guess_type(str(file_path))
        if not mime_type:
            mime_type = "image/png"  # fallback

        # 3. Compute file metadata (sha256 + size) for the ref / data.files
        abs_path = file_path.resolve()
        try:
            size = abs_path.stat().st_size
            sha256 = await asyncio.to_thread(_sha256_file, abs_path)
        except OSError as e:
            logger.error(f"Failed to read image file metadata: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"读取图片文件失败: {e}",
            )

        # 4. Branch: cloud storage configured → upload & build cloud ref;
        #    otherwise → no upload, build local ref (no cloud storage required).
        storage = get_configs().storage
        use_cloud = bool(
            storage.backend and storage.backend in ("cloudflare", "supabase")
        )

        if use_cloud:
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

            public_url_base = self._get_public_url_base(storage)
            display_url = f"{public_url_base}/{storage_path}"
            ref_meta = {
                "kind": "cloud",
                "key": storage_path,
                "url": display_url,
                "sha256": sha256,
                "mime": mime_type,
                "size": size,
            }
        else:
            # Local ref: no S3 upload. Display url points at backend /files/raw.
            display_url = _local_preview_url(abs_path)
            ref_meta = {
                "kind": "local",
                "path": str(abs_path),
                "url": display_url,
                "sha256": sha256,
                "mime": mime_type,
                "size": size,
            }

        # Check if model supports image input
        supports_image = self._check_modality(context)

        if not supports_image:
            # Model does not support image: return the display URL as text only
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"图片已读取（当前模型不支持图片输入）: {display_url}",
            )

        # Build LLM message (multimodal user message with a ref placeholder)
        image_url_part = {
            "type": "image_url",
            "image_url": {"url": encode_media_ref(ref_meta)},
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
                {"type": "text", "text": f"Image Loaded."},
            ],
        }

        file_data = {
            "name": file_path.name,
            "url": display_url,
            "type": mime_type,
            "sha256": sha256,
            "size": size,
        }
        if ref_meta["kind"] == "cloud":
            file_data["storage_key"] = ref_meta["key"]
        else:
            file_data["local_path"] = ref_meta["path"]

        db_data = {
            "content": "Image Readed",
            "files": [file_data],
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
