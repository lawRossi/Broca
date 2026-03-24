import logging
import uuid
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import boto3
from jose import JWTError, jwt
from postgrest.exceptions import APIError
from pydantic import BaseModel
from storage3.types import FileOptions, ListBucketFilesOptions
from supabase import Client, create_client
from supabase.client import ClientOptions

from app.core.config import settings

# 设置日志
logger = logging.getLogger(__name__)


class SupabaseError(Exception):
    """Supabase 相关错误基类"""

    pass


class SupabaseAuthError(SupabaseError):
    """认证相关错误"""

    pass


class SupabaseDBError(SupabaseError):
    """数据库相关错误"""

    pass


class SupabaseStorageError(SupabaseError):
    """存储相关错误"""

    pass


class SupabaseRealtimeError(SupabaseError):
    """实时订阅相关错误"""

    pass


@lru_cache
def get_supabase_client() -> Client:
    """获取 Supabase 客户端实例(单例模式)

    Returns:
        Client: Supabase 客户端实例

    Raises:
        SupabaseError: 当环境变量配置不正确时

    """
    url = settings.supabase_url
    key = settings.supabase_key

    if not url or not key:
        raise SupabaseError("SUPABASE_URL and SUPABASE_KEY must be set in environment variables")

    try:
        # 使用客户端选项配置超时等参数
        options = ClientOptions(auto_refresh_token=True, persist_session=True)
        return create_client(url, key, options)
    except Exception as e:
        logger.error(f"Failed to create Supabase client: {e}")
        raise SupabaseError(f"Failed to create Supabase client: {e}") from e


@lru_cache
def get_s3_client():  # type: ignore
    """获取 S3 客户端实例(使用 Supabase S3 兼容端点)

    Returns:
        boto3.client: S3 客户端实例

    """
    return boto3.client(  # type: ignore
        "s3",
        endpoint_url=f"{settings.supabase_url}/storage/v1/s3",
        aws_access_key_id=settings.supabase_key,
        aws_secret_access_key=settings.supabase_key,
        region_name="auto",
        config=boto3.session.Config(s3={"addressing_style": "path"}),  # type: ignore[attr-defined]
    )


class SupabaseAuth:
    """Supabase 认证工具类"""

    def __init__(self, client: Client):
        """初始化认证工具类

        Args:
            client: Supabase 客户端实例

        """
        self.client = client
        self.logger = logging.getLogger(self.__class__.__name__)

    def is_token_expired(self, token: str) -> bool:
        """验证令牌是否过期

        Args:
            token: JWT 令牌字符串

        Returns:
            bool: 令牌是否有效(未过期)

        """
        try:
            payload = self.decode_supabase_token(token)
            exp = payload.get("exp")
            if exp:
                return datetime.fromtimestamp(exp) < datetime.now()
            return False
        except (SupabaseAuthError, ValueError):
            return False

    def decode_supabase_token(self, token: str) -> dict[str, Any]:
        """解码 Supabase JWT 令牌

        Args:
            token: JWT 令牌字符串

        Returns:
            Dict[str, Any]: 解码后的令牌 payload

        Raises:
            SupabaseAuthError: 当令牌无效或解码失败时

        """
        jwt_secret = settings.supabase_jwt_secret

        if not jwt_secret:
            raise SupabaseAuthError("SUPABASE_JWT_SECRET must be set in environment variables")

        try:
            payload = jwt.decode(token, jwt_secret, algorithms=["HS256"], audience="authenticated")
            logger.info("Successfully decoded Supabase token")
            return payload
        except JWTError as e:
            logger.error(f"Failed to decode Supabase token: {e}")
            raise SupabaseAuthError("Invalid token") from e

    async def sign_out(self) -> bool:
        """登出

        Returns:
            bool: 登出是否成功

        """
        try:
            self.client.auth.sign_out()
            self.logger.info("Successfully signed out")
            return True
        except Exception as e:
            self.logger.error(f"Failed to sign out: {e}")
            return False

    async def refresh_token(self, refresh_token: str) -> dict[str, Any] | None:
        """刷新令牌

        Args:
            refresh_token: 刷新令牌

        Returns:
            Optional[Dict[str, Any]]: 新的会话信息或 None

        """
        try:
            response = self.client.auth.refresh_session(refresh_token)
            if response.session:
                self.logger.info("Successfully refreshed token")
                return {
                    "access_token": response.session.access_token,
                    "refresh_token": response.session.refresh_token,
                    "expires_at": response.session.expires_at,
                }
            return None
        except Exception as e:
            self.logger.error(f"Failed to refresh token: {e}")
            return None


class SupabaseDB:
    """Supabase 数据库操作工具类"""

    def __init__(self, client: Client):
        """初始化数据库操作工具类

        Args:
            client: Supabase 客户端实例

        """
        self.client = client
        self.logger = logging.getLogger(self.__class__.__name__)

    async def select(
        self,
        table: str,
        columns: str = "*",
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        """查询数据

        Args:
            table: 表名
            columns: 列名，默认为 "*"
            filters: 过滤条件字典
            order_by: 排序字段
            limit: 限制数量
            offset: 偏移量

        Returns:
            List[Dict[str, Any]]: 查询结果列表

        Raises:
            SupabaseDBError: 查询失败时

        """
        try:
            query = self.client.table(table).select(columns)

            # 应用过滤条件
            if filters:
                for key, value in filters.items():
                    query = query.eq(key, value)

            # 应用排序
            if order_by:
                query = query.order(order_by)

            # 应用分页
            if limit:
                query = query.limit(limit)
            if offset:
                query = query.range(offset, offset + (limit or 10) - 1)

            result = query.execute()
            self.logger.info(f"Successfully selected from {table}")
            return cast(list[dict[str, Any]], result.data)

        except APIError as e:
            self.logger.error(f"Database error in select from {table}: {e}")
            raise SupabaseDBError(f"Failed to select from {table}") from e
        except Exception as e:
            self.logger.error(f"Unexpected error in select from {table}: {e}")
            raise SupabaseDBError("Unexpected error") from e

    async def insert(
        self, table: str, data: dict[str, Any] | list[dict[str, Any]], return_columns: str = "*"
    ) -> list[dict[str, Any]] | None:
        """插入数据

        Args:
            table: 表名
            data: 要插入的数据(单条或批量)
            return_columns: 返回的列名

        Returns:
            List[Dict[str, Any]]: 插入后的数据

        Raises:
            SupabaseDBError: 插入失败时

        """
        try:
            result = self.client.table(table).insert(data).select(return_columns).execute()  # type: ignore[attr-defined]
            self.logger.info(f"Successfully inserted {len(data) if isinstance(data, list) else 1} records into {table}")
            return cast(list[dict[str, Any]], result.data)

        except APIError as e:
            self.logger.error(f"Database error in insert to {table}: {e}")
            raise SupabaseDBError(f"Failed to insert to {table}") from e
        except Exception as e:
            self.logger.error(f"Unexpected error in insert to {table}: {e}")
            raise SupabaseDBError("Unexpected error") from e

    async def update(
        self, table: str, data: dict[str, Any], filters: dict[str, Any], return_columns: str = "*"
    ) -> list[dict[str, Any]] | None:
        """更新数据

        Args:
            table: 表名
            data: 要更新的数据
            filters: 过滤条件
            return_columns: 返回的列名

        Returns:
            List[Dict[str, Any]]: 更新后的数据

        Raises:
            SupabaseDBError: 更新失败时

        """
        try:
            query = self.client.table(table).update(data).select(return_columns)  # type: ignore[attr-defined]

            # 应用过滤条件
            for key, value in filters.items():
                query = query.eq(key, value)

            result = query.execute()
            self.logger.info(f"Successfully updated {table}")
            return cast(list[dict[str, Any]], result.data)

        except APIError as e:
            self.logger.error(f"Database error in update {table}: {e}")
            raise SupabaseDBError(f"Failed to update {table}") from e
        except Exception as e:
            self.logger.error(f"Unexpected error in update {table}: {e}")
            raise SupabaseDBError("Unexpected error") from e

    async def delete(self, table: str, filters: dict[str, Any]) -> bool:
        """删除数据

        Args:
            table: 表名
            filters: 过滤条件

        Returns:
            bool: 删除是否成功

        Raises:
            SupabaseDBError: 删除失败时

        """
        try:
            query = self.client.table(table).delete()

            # 应用过滤条件
            for key, value in filters.items():
                query = query.eq(key, value)

            query.execute()
            self.logger.info(f"Successfully deleted from {table}")
            return True

        except APIError as e:
            self.logger.error(f"Database error in delete from {table}: {e}")  # noqa: S608
            raise SupabaseDBError(f"Failed to delete from {table}") from e  # noqa: S608
        except Exception as e:
            self.logger.error(f"Unexpected error in delete from {table}: {e}")  # noqa: S608
            raise SupabaseDBError("Unexpected error") from e

    async def upsert(
        self,
        table: str,
        data: dict[str, Any] | list[dict[str, Any]],
        on_conflict: str | None = None,
        return_columns: str = "*",
    ) -> list[dict[str, Any]] | None:
        """插入或更新数据（如果存在则更新，否则插入）

        Args:
            table: 表名
            data: 要插入/更新的数据
            on_conflict: 冲突检测列
            return_columns: 返回的列名

        Returns:
            List[Dict[str, Any]]: 处理后的数据

        Raises:
            SupabaseDBError: 操作失败时

        """
        try:
            if on_conflict:
                query = self.client.table(table).upsert(data, on_conflict=on_conflict).select(return_columns)  # type: ignore[attr-defined]
            else:
                query = self.client.table(table).upsert(data).select(return_columns)  # type: ignore[attr-defined]
            result = query.execute()
            self.logger.info(f"Successfully upserted {len(data) if isinstance(data, list) else 1} records to {table}")
            return cast(list[dict[str, Any]], result.data)

        except APIError as e:
            self.logger.error(f"Database error in upsert to {table}: {e}")
            raise SupabaseDBError(f"Failed to upsert to {table}") from e
        except Exception as e:
            self.logger.error(f"Unexpected error in upsert to {table}: {e}")
            raise SupabaseDBError("Unexpected error") from e

    async def check_user_exists(self, user_id: str) -> bool:
        """检查用户是否存在

        Args:
            client: Supabase 客户端实例
            user_id: 用户 ID

        Returns:
            bool: 用户是否存在

        """
        try:
            result = await self.select("users", filters={"id": user_id}, limit=1)
            return len(result) > 0
        except SupabaseDBError:
            return False


class SupabaseStorage:
    """Supabase 存储操作工具类"""

    def __init__(self, client: Client):
        """初始化存储操作工具类

        Args:
            client: Supabase 客户端实例

        """
        self.client = client
        self.logger = logging.getLogger(self.__class__.__name__)

    async def upload_file(
        self, bucket: str, path: str, file_data: bytes | str, content_type: str | None = None
    ) -> dict[str, Any]:
        """上传文件

        Args:
            bucket: 存储桶名
            path: 文件路径
            file_data: 文件数据
            content_type: 内容类型

        Returns:
            Dict[str, Any]: 上传结果

        Raises:
            SupabaseStorageError: 上传失败时

        """
        try:
            options = cast(FileOptions, {"content-type": content_type}) if content_type else None
            result = self.client.storage.from_(bucket).upload(path, file_data, options)
            self.logger.info(f"Successfully uploaded file to {bucket}/{path}")
            return cast(dict[str, Any], result)

        except Exception as e:
            self.logger.error(f"Storage error in upload to {bucket}/{path}: {e}")
            raise SupabaseStorageError("Failed to upload file") from e

    async def download_file(self, bucket: str, path: str) -> bytes:
        """下载文件

        Args:
            bucket: 存储桶名
            path: 文件路径

        Returns:
            bytes: 文件数据

        Raises:
            SupabaseStorageError: 下载失败时

        """
        try:
            result = self.client.storage.from_(bucket).download(path)
            self.logger.info(f"Successfully downloaded file from {bucket}/{path}")
            return result

        except Exception as e:
            self.logger.error(f"Storage error in download from {bucket}/{path}: {e}")
            raise SupabaseStorageError("Failed to download file") from e

    def get_public_url(self, bucket: str, path: str) -> str:
        """获取文件的公开 URL

        Args:
            bucket: 存储桶名
            path: 文件路径

        Returns:
            str: 公开 URL

        """
        try:
            result = self.client.storage.from_(bucket).get_public_url(path)
            return result

        except Exception as e:
            self.logger.error(f"Storage error in get_public_url for {bucket}/{path}: {e}")
            raise SupabaseStorageError("Failed to get public URL") from e

    async def delete_file(self, bucket: str, path: str) -> bool:
        """删除文件

        Args:
            bucket: 存储桶名
            path: 文件路径

        Returns:
            bool: 删除是否成功

        Raises:
            SupabaseStorageError: 删除失败时

        """
        try:
            self.client.storage.from_(bucket).remove([path])
            self.logger.info(f"Successfully deleted file from {bucket}/{path}")
            return True

        except Exception as e:
            self.logger.error(f"Storage error in delete from {bucket}/{path}: {e}")  # noqa: S608
            raise SupabaseStorageError("Failed to delete file") from e

    async def list_files(
        self, bucket: str, path: str | None = None, limit: int | None = None, offset: int | None = None
    ) -> list[dict[str, Any]]:
        """列出文件

        Args:
            bucket: 存储桶名
            path: 文件夹路径
            limit: 限制数量
            offset: 偏移量

        Returns:
            List[Dict[str, Any]]: 文件列表

        Raises:
            SupabaseStorageError: 列出文件失败时

        """
        try:
            options = ListBucketFilesOptions()
            if limit:
                options["limit"] = limit
            if offset:
                options["offset"] = offset

            result = self.client.storage.from_(bucket).list(path, options if options else None)
            self.logger.info(f"Successfully listed files from {bucket}/{path or ''}")
            return result

        except Exception as e:
            self.logger.error(f"Storage error in list from {bucket}/{path or ''}: {e}")
            raise SupabaseStorageError("Failed to list files") from e

    async def generate_filename(self, original_filename: str) -> str:
        """生成唯一的文件名

        Args:
            original_filename: 原始文件名

        Returns:
            str: 唯一文件名

        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        file_extension = Path(original_filename).suffix

        return f"{timestamp}_{unique_id}{file_extension}"

    async def upload_file_to_s3(
        self, bucket: str, key: str, file_data: bytes, content_type: str | None = None
    ) -> dict[str, Any]:
        """通过 S3 API 上传文件到 Supabase Storage

        Args:
            bucket: 存储桶名
            key: 文件键名（路径）
            file_data: 文件数据（bytes）
            content_type: 内容类型

        Returns:
            Dict[str, Any]: 上传结果

        Raises:
            SupabaseStorageError: 上传失败时

        """
        try:
            s3_client = get_s3_client()
            upload_params = {
                "Bucket": bucket,
                "Key": key,
                "Body": file_data,
            }
            if content_type:
                upload_params["ContentType"] = content_type

            result = s3_client.put_object(**upload_params)
            self.logger.info(f"Successfully uploaded file to S3: {bucket}/{key}")
            return {"bucket": bucket, "key": key, "etag": result.get("ETag"), "version_id": result.get("VersionId")}

        except Exception as e:
            self.logger.error(f"S3 upload error for {bucket}/{key}: {e}")
            raise SupabaseStorageError("Failed to upload file to S3") from e


class SupabaseDep(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    auth: SupabaseAuth
    client: Client
    db: SupabaseDB
    storage: SupabaseStorage


def get_supbase() -> SupabaseDep:
    supabase_client = get_supabase_client()
    return SupabaseDep(
        auth=SupabaseAuth(supabase_client),
        client=supabase_client,
        db=SupabaseDB(supabase_client),
        storage=SupabaseStorage(supabase_client),
    )
