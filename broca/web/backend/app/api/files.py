import os
import stat
from pathlib import Path

from fastapi import APIRouter, HTTPException
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
        logger.error(f"Error listing files in {path}: {e}")
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
        logger.error(f"Error getting file info for {path}: {e}")
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
        logger.error(f"Permission denied for {path}: {e}")
        raise HTTPException(status_code=403, detail=f"Permission denied: {path}") from e
    except Exception as e:
        logger.error(f"Error previewing file {path}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


class FileEditRequest(BaseModel):
    """文件编辑请求"""

    content: str


@router.put("/files/edit", response_model=ApiResponse)
async def edit_file(path: str, request: FileEditRequest) -> ApiResponse:
    """编辑文件内容

    Args:
        path: 文件路径
        content: 新的文件内容

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
                except Exception as restore_error:
                    logger.error(f"Failed to restore from backup: {restore_error}")

            raise HTTPException(status_code=500, detail="Failed to write file") from e

    except HTTPException:
        raise
    except PermissionError as e:
        logger.error(f"Permission denied for {path}: {e}")
        raise HTTPException(status_code=403, detail=f"Permission denied: {path}") from e
    except Exception as e:
        logger.error(f"Error editing file {path}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("/files/home", response_model=ApiResponse)
async def get_home_directory() -> ApiResponse:
    """获取用户的home目录
    
    返回当前用户的home目录路径，用于前端初始化工作空间选择器
    """
    try:
        home_dir = str(Path.home())
        logger.info(f"Home directory: {home_dir}")
        return ApiResponse.success({"home_dir": home_dir}, msg="Home directory retrieved successfully")
    except Exception as e:
        logger.error(f"Error getting home directory: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e
