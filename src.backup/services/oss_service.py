"""阿里云OSS服务 - 用于上传图片供API访问"""
import uuid
import logging
from pathlib import Path
from typing import BinaryIO

import oss2

from src.config import OSS_ACCESS_KEY, OSS_SECRET_KEY, OSS_ENDPOINT, OSS_BUCKET

logger = logging.getLogger(__name__)


class OSSService:
    """阿里云OSS服务类"""

    def __init__(
        self,
        access_key: str = OSS_ACCESS_KEY,
        secret_key: str = OSS_SECRET_KEY,
        endpoint: str = OSS_ENDPOINT,
        bucket_name: str = OSS_BUCKET,
    ):
        self.access_key = access_key
        self.secret_key = secret_key
        self.endpoint = endpoint
        self.bucket_name = bucket_name
        self._bucket = None

    def _get_bucket(self):
        """获取OSS Bucket实例（懒加载）"""
        if self._bucket is None:
            if not all([self.access_key, self.secret_key, self.endpoint, self.bucket_name]):
                raise ValueError("OSS配置不完整，请检查环境变量")
            
            auth = oss2.Auth(self.access_key, self.secret_key)
            self._bucket = oss2.Bucket(auth, self.endpoint, self.bucket_name)
        return self._bucket

    async def upload_file(
        self,
        local_path: str,
        remote_dir: str = "material_images",
        content_type: str = "image/png",
    ) -> str:
        """上传本地文件到OSS

        Args:
            local_path: 本地文件路径
            remote_dir: OSS上的目录名
            content_type: 文件MIME类型

        Returns:
            上传后的文件URL
        """
        path = Path(local_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {local_path}")

        # 生成唯一文件名
        ext = path.suffix or ".png"
        filename = f"{uuid.uuid4().hex}{ext}"
        key = f"{remote_dir}/{filename}"

        # 上传文件
        bucket = self._get_bucket()
        headers = {"Content-Type": content_type}
        
        with open(path, "rb") as f:
            bucket.put_object(key, f, headers=headers)

        # 构建URL
        url = f"https://{self.bucket_name}.{self.endpoint.replace('http://', '').replace('https://', '')}/{key}"
        
        logger.info(f"[OSS] 上传成功: {local_path} -> {url}")
        return url

    async def upload_bytes(
        self,
        data: bytes,
        remote_dir: str = "material_images",
        content_type: str = "image/png",
    ) -> str:
        """上传字节数据到OSS

        Args:
            data: 文件字节数据
            remote_dir: OSS上的目录名
            content_type: 文件MIME类型

        Returns:
            上传后的文件URL
        """
        # 生成唯一文件名
        filename = f"{uuid.uuid4().hex}.png"
        key = f"{remote_dir}/{filename}"

        # 上传
        bucket = self._get_bucket()
        headers = {"Content-Type": content_type}
        bucket.put_object(key, data, headers=headers)

        # 构建URL
        url = f"https://{self.bucket_name}.{self.endpoint.replace('http://', '').replace('https://', '')}/{key}"
        
        logger.info(f"[OSS] 上传字节数据成功: {url}")
        return url

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
            bucket = self._get_bucket()
            bucket.delete_object(key)
            logger.info(f"[OSS] 删除成功: {oss_url}")
            return True
        except Exception as e:
            logger.error(f"[OSS] 删除失败: {e}")
            return False


# 全局OSS服务实例
_oss_service = None


def get_oss_service() -> OSSService:
    """获取OSS服务实例（单例）"""
    global _oss_service
    if _oss_service is None:
        _oss_service = OSSService()
    return _oss_service
