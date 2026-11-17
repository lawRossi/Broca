import hashlib
import mimetypes
import os
import shutil
import stat
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel

from app.schemas.schemas import ApiResponse

router = APIRouter()


class FileItem(BaseModel):
    """文件/目录项"""

    name: str
    path: str
    is_dir: bool
    size: int | None = None
    modified_time: float
    permissions: str
    readable: bool = True


class FileListResponse(BaseModel):
    """文件列表响应"""

    current_path: str
    parent_path: str | None = None
    files: list[FileItem]
    total: int


class FileCompleteItem(BaseModel):
    """路径补全建议项"""

    name: str
    path: str
    is_dir: bool


class FileCompleteResponse(BaseModel):
    """路径补全响应"""

    base: str
    prefix: str
    completions: list[FileCompleteItem]
    total: int
    truncated: bool = False


# 补全条目数上限，超出截断（避免大目录响应过慢）
MAX_COMPLETE_ITEMS = 200


@router.get("/files", response_model=ApiResponse)
async def list_files(path: str = ".") -> ApiResponse:
    """获取指定路径的文件列表

    Args:
        path: 要浏览的路径，默认为当前目录

    """
    try:
        # 解析路径
        if path == ".":
            target_path = Path.cwd()
        else:
            target_path = Path(path).expanduser().resolve()

        # 安全检查：确保路径在允许的范围内
        # 这里可以添加更多的安全检查，比如限制在项目目录内
        if not target_path.exists():
            raise HTTPException(status_code=404, detail=f"Path not found: {path}")

        if not target_path.is_dir():
            raise HTTPException(status_code=400, detail=f"Not a directory: {path}")

        # 获取父目录路径
        parent_path = str(target_path.parent) if str(target_path.parent) != str(target_path) else None

        # 获取文件列表
        files = []
        for item in target_path.iterdir():
            try:
                stat_info = item.stat()

                # 获取权限字符串
                mode = stat_info.st_mode
                permissions = stat.filemode(mode)

                # 检查是否可读
                readable = os.access(item, os.R_OK)

                file_item = FileItem(
                    name=item.name,
                    path=str(item),
                    is_dir=item.is_dir(),
                    size=stat_info.st_size if not item.is_dir() else None,
                    modified_time=stat_info.st_mtime,
                    permissions=permissions,
                    readable=readable,
                )
                files.append(file_item)
            except (PermissionError, OSError) as e:
                logger.warning(f"Cannot access {item}: {e}")
                # 创建不可访问的文件项
                file_item = FileItem(
                    name=item.name,
                    path=str(item),
                    is_dir=False,  # 不确定是否是目录，默认为文件
                    size=None,
                    modified_time=0,
                    permissions="??????????",
                    readable=False,
                )
                files.append(file_item)

        # 排序：目录在前，文件在后，按名称排序
        files.sort(key=lambda x: (not x.is_dir, x.name.lower()))

        response_data = FileListResponse(
            current_path=str(target_path), parent_path=parent_path, files=files, total=len(files)
        )

        return ApiResponse.success(response_data.dict())

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error listing files in {path}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("/files/complete", response_model=ApiResponse)
async def complete_files(base: str = "", prefix: str = "") -> ApiResponse:
    """文件路径补全（供前端输入 # 触发）

    Args:
        base: 补全根目录（通常为当前会话 workspace）；为空时使用后端 cwd
        prefix: 相对 base 的路径前缀，如 "src/comp"、"src/"、""（空串 = 根目录）

    Returns:
        相对路径补全建议列表（path 相对 base，由后端拼接，前端零路径运算）
    """
    try:
        # 解析 base：空 → cwd；否则 expanduser + resolve 为绝对路径
        if not base:
            base_path = Path.cwd()
        else:
            base_path = Path(base).expanduser().resolve()

        empty_response = FileCompleteResponse(
            base=str(base_path), prefix=prefix, completions=[], total=0
        )

        # base 不存在或不是目录 → 返回空列表
        if not base_path.exists() or not base_path.is_dir():
            return ApiResponse.success(empty_response.dict())

        # prefix 校验：拒绝父目录穿越（..）与绝对路径（限制在根目录内）
        prefix_path = Path(prefix)
        if ".." in prefix_path.parts or prefix_path.is_absolute():
            return ApiResponse.success(empty_response.dict())

        # 拆分 prefix：「目录部分 + 名字前缀」
        if prefix.endswith("/"):
            dir_part = prefix.rstrip("/")
            name_prefix = ""
        else:
            parent = prefix_path.parent
            dir_part = "" if str(parent) == "." else str(parent)
            name_prefix = prefix_path.name

        # 列出 base/dir 下条目
        target_dir = base_path / dir_part if dir_part else base_path
        completions: list[FileCompleteItem] = []
        if target_dir.exists() and target_dir.is_dir():
            for item in target_dir.iterdir():
                try:
                    is_dir = item.is_dir()
                    name = item.name
                    # 按名字前缀过滤（startswith），空前缀不过滤
                    if name_prefix and not name.startswith(name_prefix):
                        continue
                    # 相对路径 = dir/name（相对 base）
                    rel_path = (Path(dir_part) / name).as_posix() if dir_part else name
                    completions.append(FileCompleteItem(name=name, path=rel_path, is_dir=is_dir))
                except (PermissionError, OSError) as e:
                    logger.warning(f"Cannot access {item}: {e}")

        # 排序：目录在前、文件在后，各自按 name.lower() 排序
        completions.sort(key=lambda x: (not x.is_dir, x.name.lower()))

        # 限制返回条数，超出截断并提示
        truncated = len(completions) > MAX_COMPLETE_ITEMS
        completions = completions[:MAX_COMPLETE_ITEMS]

        response_data = FileCompleteResponse(
            base=str(base_path),
            prefix=prefix,
            completions=completions,
            total=len(completions),
            truncated=truncated,
        )
        return ApiResponse.success(response_data.dict())

    except Exception as e:
        logger.exception(f"Error completing files: base={base}, prefix={prefix}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("/files/info", response_model=ApiResponse)
async def get_file_info(path: str) -> ApiResponse:
    """获取文件/目录的详细信息"""
    try:
        target_path = Path(path).expanduser().resolve()

        if not target_path.exists():
            raise HTTPException(status_code=404, detail=f"Path not found: {path}")

        stat_info = target_path.stat()
        mode = stat_info.st_mode

        file_info = {
            "name": target_path.name,
            "path": str(target_path),
            "is_dir": target_path.is_dir(),
            "size": stat_info.st_size if not target_path.is_dir() else None,
            "modified_time": stat_info.st_mtime,
            "created_time": stat_info.st_ctime,
            "accessed_time": stat_info.st_atime,
            "permissions": stat.filemode(mode),
            "readable": os.access(target_path, os.R_OK),
            "writable": os.access(target_path, os.W_OK),
            "executable": os.access(target_path, os.X_OK),
            "inode": stat_info.st_ino,
            "device": stat_info.st_dev,
            "hard_links": stat_info.st_nlink,
            "uid": stat_info.st_uid,
            "gid": stat_info.st_gid,
        }

        return ApiResponse.success(file_info)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting file info for {path}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("/files/preview", response_model=ApiResponse)
async def preview_file(path: str) -> ApiResponse:
    """预览文件内容（仅文本文件）

    Args:
        path: 文件路径

    """
    try:
        target_path = Path(path).expanduser().resolve()

        if not target_path.exists():
            raise HTTPException(status_code=404, detail=f"File not found: {path}")

        if target_path.is_dir():
            raise HTTPException(status_code=400, detail=f"Cannot preview directory: {path}")

        # 检查文件大小（限制预览大小）
        max_size = 10 * 1024 * 1024  # 10MB
        file_size = target_path.stat().st_size
        if file_size > max_size:
            return ApiResponse.success(
                {
                    "path": str(target_path),
                    "size": file_size,
                    "preview": None,
                    "message": f"File too large for preview ({file_size} bytes > {max_size} bytes)",
                    "truncated": False,
                }
            )

        # 尝试读取文件内容
        try:
            with open(target_path, encoding="utf-8") as f:
                content = f.read()

                return ApiResponse.success(
                    {"path": str(target_path), "size": file_size, "preview": content, "truncated": False}
                )

        except UnicodeDecodeError:
            # 二进制文件，无法预览
            return ApiResponse.success(
                {
                    "path": str(target_path),
                    "size": file_size,
                    "preview": None,
                    "message": "Binary file, cannot preview as text",
                    "truncated": False,
                }
            )

    except HTTPException:
        raise
    except PermissionError as e:
        logger.exception(f"Permission denied for {path}")
        raise HTTPException(status_code=403, detail=f"Permission denied: {path}") from e
    except Exception as e:
        logger.exception(f"Error previewing file {path}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


class FileEditRequest(BaseModel):
    """文件编辑请求"""

    content: str


# ── /files/raw: serve local binary files for local media refs ──────────────
# Max size for a raw binary response (50 MB).
_RAW_MAX_SIZE = 50 * 1024 * 1024
# Only these top-level MIME categories may be served raw.
_RAW_ALLOWED_MIME_PREFIXES = ("image/", "video/", "audio/")


def _raw_static_allowed_roots() -> list[Path]:
    """Static whitelisted root directories for ``/files/raw``.

    Includes ``<broca_home>/uploads`` (user uploads) and ``<broca_home>``
    (session attachments). Workspaces are added dynamically in
    :func:`_raw_allowed_roots`.
    """
    broca_home = Path.home() / ".broca"
    return [broca_home / "uploads", broca_home]


async def _raw_allowed_roots() -> list[Path]:
    """Whitelisted root directories (static + registered session workspaces)."""
    roots = _raw_static_allowed_roots()
    try:
        from sqlmodel import select

        from broca.session.database import db_manager
        from broca.session.models import Session

        async with db_manager.get_session() as db_session:
            result = await db_session.exec(select(Session.workspace))
            for (workspace,) in result.all():
                if workspace:
                    roots.append(Path(workspace).expanduser())
    except Exception as e:  # best-effort: never fail the request on DB issues
        logger.warning(f"/files/raw: could not load session workspaces: {e}")

    resolved: list[Path] = []
    for r in roots:
        try:
            resolved.append(r.resolve())
        except (OSError, RuntimeError):
            continue
    return resolved


@router.get("/files/raw")
async def raw_file(path: str):
    """Serve a local binary file (image/video/audio) for display.

    Used by ``local`` media refs so the frontend can render an image whose
    bytes live on the backend host. Security:
    - The resolved path MUST be inside one of the whitelisted roots
      (``is_relative_to``), otherwise 403. This blocks path traversal and
      arbitrary file reads.
    - Only image/video/audio MIME types are served.
    - Directories and missing files are rejected (400/404).
    - Files larger than 50 MB are rejected (413).

    Note: ``<img src>`` uses a same-origin relative URL, so the frontend must
    be served from the same origin as the backend (or via the dev proxy).
    """
    try:
        target = Path(path).expanduser()
        try:
            resolved = target.resolve()
        except (OSError, RuntimeError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid path: {path}") from e

        # Root whitelist check (blocks traversal / arbitrary reads)
        roots = await _raw_allowed_roots()
        if not any(resolved == r or resolved.is_relative_to(r) for r in roots):
            raise HTTPException(status_code=403, detail="Path not allowed")

        if not resolved.exists():
            raise HTTPException(status_code=404, detail=f"File not found: {path}")
        if resolved.is_dir():
            raise HTTPException(status_code=400, detail=f"Cannot serve directory: {path}")

        mime, _ = mimetypes.guess_type(str(resolved))
        if not mime or not mime.startswith(_RAW_ALLOWED_MIME_PREFIXES):
            raise HTTPException(
                status_code=403, detail=f"File type not allowed: {mime or 'unknown'}"
            )

        size = resolved.stat().st_size
        if size > _RAW_MAX_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File too large ({size} bytes > {_RAW_MAX_SIZE} bytes)",
            )

        return FileResponse(str(resolved), media_type=mime)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error serving raw file {path}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.put("/files/edit", response_model=ApiResponse)
async def edit_file(path: str, request: FileEditRequest) -> ApiResponse:
    """编辑文件内容

    Args:
        path: 文件路径
        request: 文件编辑请求（包含新的文件内容）

    """
    try:
        target_path = Path(path).expanduser().resolve()

        if not target_path.exists():
            raise HTTPException(status_code=404, detail=f"File not found: {path}")

        if target_path.is_dir():
            raise HTTPException(status_code=400, detail=f"Cannot edit directory: {path}")

        # 检查文件是否可写
        if not os.access(target_path, os.W_OK):
            raise HTTPException(status_code=403, detail=f"File is not writable: {path}")

        # 检查文件大小限制（防止上传过大文件）
        max_size = 10 * 1024 * 1024  # 10MB
        if len(request.content.encode("utf-8")) > max_size:
            raise HTTPException(
                status_code=400,
                detail=f"File content too large ({len(request.content.encode('utf-8'))} bytes > {max_size} bytes)",
            )

        # 备份原文件（可选）
        backup_path = None
        try:
            # 创建备份
            backup_path = target_path.with_suffix(target_path.suffix + ".bak")
            import shutil

            shutil.copy2(target_path, backup_path)
        except Exception as e:
            logger.warning(f"Failed to create backup for {path}: {e}")

        # 写入新内容
        try:
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(request.content)

            # 获取文件信息
            stat_info = target_path.stat()

            return ApiResponse.success(
                {
                    "path": str(target_path),
                    "size": len(request.content.encode("utf-8")),
                    "modified_time": stat_info.st_mtime,
                    "backup_created": backup_path is not None and backup_path.exists(),
                    "backup_path": str(backup_path) if backup_path else None,
                }
            )

        except Exception as e:
            # 如果写入失败，尝试恢复备份
            if backup_path and backup_path.exists():
                try:
                    shutil.copy2(backup_path, target_path)
                    logger.info(f"Restored file from backup: {path}")
                except Exception:
                    logger.exception("Failed to restore from backup")

            raise HTTPException(status_code=500, detail="Failed to write file") from e

    except HTTPException:
        raise
    except PermissionError as e:
        logger.exception(f"Permission denied for {path}")
        raise HTTPException(status_code=403, detail=f"Permission denied: {path}") from e
    except Exception as e:
        logger.exception(f"Error editing file {path}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("/files/home", response_model=ApiResponse)
async def get_home_directory() -> ApiResponse:
    """获取用户的home目录

    返回当前用户的home目录路径，用于前端初始化工作空间选择器
    """
    try:
        home_dir = str(Path.home())
        return ApiResponse.success({"home_dir": home_dir}, msg="Home directory retrieved successfully")
    except Exception as e:
        logger.exception("Error getting home directory")
        raise HTTPException(status_code=500, detail="Internal server error") from e


# ── /files/upload: local-disk upload for media refs (no cloud storage) ──────
# Max accepted upload size (50 MB), aligned with /files/raw serving limit.
_UPLOAD_MAX_SIZE = 50 * 1024 * 1024
# Chunk size used when streaming the upload to disk (1 MB).
_UPLOAD_CHUNK_SIZE = 1024 * 1024
# Uploaded files are retained for at most 2 days (date-dir based GC).
_UPLOAD_RETENTION_DAYS = 2
# Allowed file extensions (images / audio / video / text / common documents).
_UPLOAD_ALLOWED_EXTENSIONS = {
    # images
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg",
    ".tiff", ".tif", ".heic", ".heif", ".ico", ".avif",
    # video
    ".mp4", ".webm", ".mov", ".avi", ".mkv", ".m4v", ".flv",
    # audio
    ".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".wma", ".opus",
    # text
    ".txt", ".md", ".markdown", ".csv", ".json", ".xml",
    ".yaml", ".yml", ".log", ".ini", ".toml",
    # documents
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".odt", ".ods", ".odp", ".rtf", ".epub",
}


def _uploads_root() -> Path:
    """Root directory for user uploads (``<broca_home>/uploads``).

    Module-level so tests can monkeypatch it to a temp dir.
    """
    return Path.home() / ".broca" / "uploads"


def _cleanup_old_uploads(root: Path, retention_days: int = _UPLOAD_RETENTION_DAYS) -> None:
    """Delete ``YYYYMMDD`` date directories older than ``retention_days``.

    Uploads are organised as ``<root>/YYYYMMDD/<file>``. Any date directory
    strictly older than the cutoff (``now - retention_days``) is removed.
    Non-date entries and files are left untouched. Best-effort: never raises.
    """
    if not root.exists():
        return
    cutoff_str = (datetime.now() - timedelta(days=retention_days)).strftime("%Y%m%d")
    for entry in root.iterdir():
        try:
            if not entry.is_dir():
                continue
            name = entry.name
            # Only touch well-formed date dirs, and only those older than cutoff.
            if len(name) == 8 and name.isdigit() and name < cutoff_str:
                shutil.rmtree(entry, ignore_errors=True)
                logger.info(f"/files/upload: cleaned expired upload dir {entry}")
        except OSError as e:  # best-effort cleanup
            logger.warning(f"/files/upload: failed to clean {entry}: {e}")


@router.post("/files/upload", response_model=ApiResponse)
async def upload_file(file: UploadFile = File(...)) -> ApiResponse:
    """Store an uploaded file on local disk (used when cloud storage is off).

    Saves to ``<broca_home>/uploads/YYYYMMDD/<encodedName>_<uuid6>.<ext>``
    (naming reused from ``broca.tools.image`` so it matches the read_image
    tool). Returns the metadata the frontend needs to build a ``local`` media
    ref and a display URL served by ``GET /files/raw``.

    Security:
    - Extension must be in the whitelist.
    - Size capped at 50 MB (413 when exceeded).
    - Filename is URL-encoded (no path separators), so no traversal.
    - Expired date dirs (older than 2 days) are cleaned opportunistically.
    """
    original_name = file.filename or "upload"
    ext = Path(original_name).suffix.lower()
    if ext not in _UPLOAD_ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type not allowed: {ext or 'unknown'}")

    try:
        root = _uploads_root()
        # Opportunistic GC of expired date dirs (never blocks the upload).
        try:
            _cleanup_old_uploads(root)
        except Exception as e:  # cleanup must not break uploads
            logger.warning(f"/files/upload: cleanup failed: {e}")

        date_str = datetime.now().strftime("%Y%m%d")
        date_dir = root / date_str
        date_dir.mkdir(parents=True, exist_ok=True)

        # Reuse image.py naming rule (encode name, keep ASCII-safe, uuid6 suffix).
        from broca.tools.image import _generate_unique_filename

        dest = date_dir / _generate_unique_filename(original_name)

        digest = hashlib.sha256()
        size = 0
        try:
            with open(dest, "wb") as out:
                while True:
                    chunk = await file.read(_UPLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > _UPLOAD_MAX_SIZE:
                        raise HTTPException(
                            status_code=413,
                            detail=f"File too large (>{_UPLOAD_MAX_SIZE} bytes)",
                        )
                    digest.update(chunk)
                    out.write(chunk)
        except HTTPException:
            dest.unlink(missing_ok=True)
            raise
        except Exception:
            dest.unlink(missing_ok=True)
            raise
        finally:
            await file.close()

        mime, _ = mimetypes.guess_type(str(dest))
        if not mime:
            mime = file.content_type or "application/octet-stream"

        abs_path = str(dest.resolve())
        url = f"/files/raw?path={quote(abs_path)}"
        data = {
            "name": original_name,
            "url": url,
            "path": abs_path,
            "local_path": abs_path,
            "size": size,
            "type": mime,
            "sha256": digest.hexdigest(),
        }
        return ApiResponse.success(data)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error uploading file {original_name}")
        raise HTTPException(status_code=500, detail="Internal server error") from e



