"""媒体引用（media ref）与请求时物化相关工具。

本包提供把图片/视频等媒体在「持久化层」以轻量引用（ref）表示，并在真正
发往 LLM 前物化为 wire 表示（base64 / files_api file_id）的能力。
"""

from broca.media.errors import MediaFileTooLargeError, MediaMaterializeError
from broca.media.files_api import (
    FilesApiStrategy,
    build_files_api_strategy,
    make_files_api_factory,
)
from broca.media.materializer import MediaMaterializer
from broca.media.ref import (
    decode_media_ref,
    encode_media_ref,
    is_media_ref,
)

__all__ = [
    "encode_media_ref",
    "decode_media_ref",
    "is_media_ref",
    "MediaMaterializer",
    "MediaFileTooLargeError",
    "MediaMaterializeError",
    "FilesApiStrategy",
    "build_files_api_strategy",
    "make_files_api_factory",
]
