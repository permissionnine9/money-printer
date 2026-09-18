"""阿里云OSS服务 - 使用boto3通过S3协议访问"""
import uuid
import logging
import time
from pathlib import Path
from io import BytesIO

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from backend.core.config import OSS_ACCESS_KEY, OSS_SECRET_KEY, OSS_ENDPOINT, OSS_REGION, OSS_BUCKET

logger = logging.getLogger(__name__)


class OSSService:
    """阿里云OSS服务类 - 使用boto3 S3兼容协议"""

    def __init__(
        self,
        access_key: str = OSS_ACCESS_KEY,
        secret_key: str = OSS_SECRET_KEY,
        endpoint: str = OSS_ENDPOINT,
        region: str = OSS_REGION,
        bucket_name: str = OSS_BUCKET,
    ):
        self.access_key = access_key
        self.secret_key = secret_key
        self.endpoint = endpoint
        self.region = region
        self.bucket_name = bucket_name
        self._conn = None

    def _get_conn(self):
        """获取S3客户端连接（懒加载）"""
        if self._conn is None:
            if not all([self.access_key, self.secret_key, self.endpoint, self.bucket_name]):
                raise ValueError("OSS配置不完整，请检查环境变量")

            # 参考: https://help.aliyun.com/zh/oss/developer-reference/use-amazon-s3-sdks-to-access-oss
            self._conn = boto3.client(
                's3',
                region_name=self.region,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                endpoint_url=self.endpoint,
                config=Config(
                    s3={"addressing_style": "virtual"},
                    signature_version='v4'
                )
            )
        return self._conn

    def _close_conn(self):
        """关闭连接"""
        if self._conn:
            del self._conn
            self._conn = None

    def _bucket_exists(self) -> bool:
        """检查bucket是否存在"""
        try:
            self._get_conn().head_bucket(Bucket=self.bucket_name)
            return True
        except ClientError:
            logger.warning(f"Bucket不存在或无权限: {self.bucket_name}")
            return False

    def _build_object_url(self, key: str) -> str:
        """构建对象的公共 URL"""
        endpoint_host = self.endpoint.replace('http://', '').replace('https://', '')
        return f"https://{self.bucket_name}.{endpoint_host}/{key}"

    def _upload(
        self,
        key: str,
        fileobj_factory,
        *,
        log_label: str,
        content_type: str,
        use_presigned: bool,
        presigned_expires: int,
    ) -> str:
        """上传文件对象到 OSS（带重试），返回预签名或公共 URL

        fileobj_factory: 每次重试重新构造文件对象的工厂（boto3 异常结束时
        会关闭传入的 fileobj，复用已关闭句柄会失败）
        """
        for attempt in range(3):
            try:
                conn = self._get_conn()
                conn.upload_fileobj(
                    fileobj_factory(),
                    self.bucket_name,
                    key,
                    ExtraArgs={"ContentType": content_type}
                )

                # 返回预签名URL或公共URL
                if use_presigned:
                    url = self.get_presigned_url(key, expires=presigned_expires)
                    if url:
                        logger.info(f"[OSS] {log_label}成功（预签名URL）")
                        return url
                    else:
                        logger.warning(f"[OSS] 获取预签名URL失败，使用公共URL")

                url = self._build_object_url(key)
                logger.info(f"[OSS] {log_label}成功: {url}")
                return url
            except Exception as e:
                logger.error(f"[OSS] 上传失败 (尝试 {attempt + 1}/3): {e}")
                self._close_conn()  # 重置连接
                time.sleep(1)

        raise RuntimeError(f"OSS上传失败: {key}")

    async def upload_file(
        self,
        local_path: str,
        remote_dir: str = "material_images",
        content_type: str = "image/png",
        use_presigned: bool = True,
        presigned_expires: int = 3600,
    ) -> str:
        """上传本地文件到OSS

        Args:
            local_path: 本地文件路径
            remote_dir: OSS上的目录名
            content_type: 文件MIME类型
            use_presigned: 是否返回预签名URL（默认为True，解决私有Bucket访问问题）
            presigned_expires: 预签名URL过期时间（秒）

        Returns:
            上传后的文件URL（公共URL或预签名URL）
        """
        path = Path(local_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {local_path}")

        ext = path.suffix or ".png"
        key = f"{remote_dir}/{uuid.uuid4().hex}{ext}"
        return self._upload(
            key, lambda: open(path, "rb"),
            log_label=f"上传 {local_path}",
            content_type=content_type,
            use_presigned=use_presigned,
            presigned_expires=presigned_expires,
        )

    async def upload_bytes(
        self,
        data: bytes,
        remote_dir: str = "material_images",
        content_type: str = "image/png",
        ext: str = ".png",
        use_presigned: bool = True,
        presigned_expires: int = 3600,
    ) -> str:
        """上传字节数据到OSS

        Args:
            data: 文件字节数据
            remote_dir: OSS上的目录名
            content_type: 文件MIME类型
            ext: 文件扩展名
            use_presigned: 是否返回预签名URL（默认为True）
            presigned_expires: 预签名URL过期时间（秒）

        Returns:
            上传后的文件URL（公共URL或预签名URL）
        """
        key = f"{remote_dir}/{uuid.uuid4().hex}{ext}"
        return self._upload(
            key, lambda: BytesIO(data),
            log_label="上传字节数据",
            content_type=content_type,
            use_presigned=use_presigned,
            presigned_expires=presigned_expires,
        )

    def delete_file(self, oss_url: str) -> bool:
        """删除OSS上的文件

        Args:
            oss_url: OSS文件URL

        Returns:
            是否删除成功
        """
        try:
            # 从URL中提取key
            key = oss_url.split(f"{self.bucket_name}.")[-1].split("/", 1)[1]
            conn = self._get_conn()
            conn.delete_object(Bucket=self.bucket_name, Key=key)
            logger.info(f"[OSS] 删除成功: {oss_url}")
            return True
        except Exception as e:
            logger.error(f"[OSS] 删除失败: {e}")
            return False

    def get_presigned_url(self, key: str, expires: int = 3600) -> str:
        """获取预签名URL

        Args:
            key: OSS对象key
            expires: 过期时间（秒）

        Returns:
            预签名URL
        """
        for attempt in range(3):
            try:
                conn = self._get_conn()
                url = conn.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': self.bucket_name, 'Key': key},
                    ExpiresIn=expires
                )
                return url
            except Exception as e:
                logger.error(f"[OSS] 获取预签名URL失败 (尝试 {attempt + 1}/3): {e}")
                self._close_conn()
                time.sleep(1)
        return ""


# 全局OSS服务实例
_oss_service = None


def get_oss_service() -> OSSService:
    """获取OSS服务实例（单例）"""
    global _oss_service
    if _oss_service is None:
        _oss_service = OSSService()
    return _oss_service


def refresh_oss_service() -> OSSService:
    """刷新OSS服务实例（重新读取配置）"""
    global _oss_service
    _oss_service = OSSService()
    return _oss_service
