"""
MinIO 对象存储服务 - 用于存储文档解析中提取的图片
"""
import asyncio
import io
from typing import Optional, BinaryIO, Union, List, Dict, Any
import json
import time
from pathlib import Path

from minio import Minio
from minio.error import S3Error

from app.core.config import settings
from app.rag.core.logging import get_logger


logger = get_logger("storage.minio")


class MinIOService:
    """MinIO 对象存储服务"""

    def __init__(self):
        self._client: Optional[Minio] = None
        self._bucket_name = settings.MINIO_BUCKET_NAME
        self._bucket_ready = False
        self._metrics_path = Path(settings.MINIO_METRICS_LOG_PATH)

    def _get_client(self) -> Minio:
        """延迟初始化 MinIO 客户端"""
        if self._client is None:
            self._client = Minio(
                endpoint=settings.MINIO_ENDPOINT,
                access_key=settings.MINIO_ACCESS_KEY,
                secret_key=settings.MINIO_SECRET_KEY,
                secure=settings.MINIO_USE_SSL,
            )
        if not self._bucket_ready:
            self._ensure_bucket()
        return self._client

    def _ensure_bucket(self):
        """确保 bucket 存在，不存在则创建"""
        client = self._client
        if client is None:
            return

        try:
            exists = client.bucket_exists(self._bucket_name)
        except Exception as e:  # noqa: BLE001
            logger.warning("MinIO bucket check failed: %s", e)
            return

        if exists:
            self._bucket_ready = True
            return

        try:
            client.make_bucket(self._bucket_name)
            self._bucket_ready = True
            logger.info("Created bucket: %s", self._bucket_name)
        except S3Error as e:
            # Bucket may be created concurrently by another process.
            if getattr(e, "code", None) in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                self._bucket_ready = True
                return
            logger.warning("MinIO bucket create failed: %s", e)
        except Exception as e:  # noqa: BLE001
            logger.warning("MinIO bucket create failed: %s", e)

    def upload_image(
        self,
        image_data: Union[bytes, BinaryIO],
        tenant_id: str,
        dataset_id: str,
        document_id: str,
        chunk_key: str,
        extension: str = "jpg",
    ) -> str:
        """
        上传图片到 MinIO，返回 img_id。
        
        Args:
            image_data: 图片二进制数据或文件对象
            tenant_id: 租户 ID
            dataset_id: 知识库 ID
            document_id: 文档 ID
            chunk_key: 块标识（通常为 chunk_index）
            extension: 文件扩展名（默认 jpg）
        
        Returns:
            img_id: 格式 "{tenant_id}:{dataset_id}:{document_id}:{chunk_key}"
        """
        t0 = time.perf_counter()
        img_id = f"{tenant_id}:{dataset_id}:{document_id}:{chunk_key}"
        object_name = f"images/{tenant_id}/{dataset_id}/{document_id}/{chunk_key}.{extension}"

        try:
            client = self._get_client()

            # 转换为字节流
            if isinstance(image_data, bytes):
                data_stream = io.BytesIO(image_data)
                data_length = len(image_data)
            else:
                # 假设是文件对象
                data_stream = image_data
                data_stream.seek(0, 2)  # 移到末尾
                data_length = data_stream.tell()
                data_stream.seek(0)  # 重置到开头

            # 上传到 MinIO
            content_type = f"image/{extension}"
            if extension.lower() in {"jpg", "jpeg"}:
                content_type = "image/jpeg"
            client.put_object(
                bucket_name=self._bucket_name,
                object_name=object_name,
                data=data_stream,
                length=data_length,
                content_type=content_type,
            )

            logger.info("Image uploaded: %s -> %s", object_name, img_id)
            self._log_metric("upload", True, time.perf_counter() - t0, object_name)
            return img_id

        except S3Error as e:
            logger.error("MinIO upload failed: %s", e)
            self._log_metric("upload", False, time.perf_counter() - t0, object_name, error=str(e))
            raise RuntimeError(f"MinIO 图片上传失败: {e}") from e

    async def upload_image_async(
        self,
        image_data: Union[bytes, BinaryIO],
        tenant_id: str,
        dataset_id: str,
        document_id: str,
        chunk_key: str,
        extension: str = "jpg",
    ) -> str:
        """
        异步上传图片到 MinIO（在线程池中执行同步操作）
        
        Args:
            image_data: 图片二进制数据或文件对象
            tenant_id: 租户 ID
            dataset_id: 知识库 ID
            document_id: 文档 ID
            chunk_key: 块标识（通常为 chunk_index）
            extension: 文件扩展名（默认 jpg）
        
        Returns:
            img_id: 格式 "{tenant_id}:{dataset_id}:{document_id}:{chunk_key}"
        """
        return await asyncio.to_thread(
            self.upload_image,
            image_data,
            tenant_id,
            dataset_id,
            document_id,
            chunk_key,
            extension
        )

    async def upload_images_batch(
        self,
        images: List[Dict[str, Any]],
        max_concurrent: int = 10
    ) -> List[Dict[str, Any]]:
        """
        批量并发上传图片到 MinIO
        
        Args:
            images: 图片列表，每个元素为字典，包含：
                - image_data: 图片二进制数据
                - tenant_id: 租户 ID
                - dataset_id: 知识库 ID
                - document_id: 文档 ID
                - chunk_key: 块标识
                - extension: 文件扩展名（可选，默认 jpg）
            max_concurrent: 最大并发上传数，默认10
        
        Returns:
            上传结果列表，每个元素为字典：
                - success: 是否成功
                - img_id: 图片 ID（成功时）
                - error: 错误信息（失败时）
                - chunk_key: 原始 chunk_key
        """
        if not images:
            return []
        
        t0 = time.perf_counter()
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def upload_single(img_info: Dict[str, Any]) -> Dict[str, Any]:
            async with semaphore:
                try:
                    img_id = await self.upload_image_async(
                        image_data=img_info["image_data"],
                        tenant_id=img_info["tenant_id"],
                        dataset_id=img_info["dataset_id"],
                        document_id=img_info["document_id"],
                        chunk_key=img_info["chunk_key"],
                        extension=img_info.get("extension", "jpg")
                    )
                    return {
                        "success": True,
                        "img_id": img_id,
                        "chunk_key": img_info["chunk_key"]
                    }
                except Exception as e:
                    logger.error(f"Batch upload failed for chunk_key {img_info.get('chunk_key')}: {str(e)}")
                    return {
                        "success": False,
                        "error": str(e),
                        "chunk_key": img_info.get("chunk_key")
                    }
        
        tasks = [upload_single(img) for img in images]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理异常
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append({
                    "success": False,
                    "error": str(result),
                    "chunk_key": images[i].get("chunk_key")
                })
            else:
                processed_results.append(result)
        
        elapsed = time.perf_counter() - t0
        success_count = sum(1 for r in processed_results if r.get("success"))
        logger.info(
            f"Batch upload completed: {success_count}/{len(images)} successful, "
            f"elapsed: {elapsed:.2f}s"
        )
        
        return processed_results

    def get_image_url(self, img_id: str, extension: str = "jpg") -> str:
        """
        获取图片访问 URL（预签名 URL，有效期 7 天）。
        
        Args:
            img_id: 格式 "{tenant_id}:{dataset_id}:{document_id}:{chunk_key}"
            extension: 文件扩展名
        
        Returns:
            预签名 URL
        """
        t0 = time.perf_counter()
        try:
            if ":" in img_id:
                tenant_id, dataset_id, document_id, chunk_key = img_id.split(":", 3)
                object_name = f"images/{tenant_id}/{dataset_id}/{document_id}/{chunk_key}.{extension}"
            else:
                # Backward compatible: "{dataset_id}-{chunk_id}"
                dataset_id, chunk_id = img_id.split("-", 1)
                object_name = f"images/{dataset_id}/{chunk_id}.{extension}"

            client = self._get_client()
            # 预签名 URL 不会检查对象是否存在，这里先做一次存在性校验，避免前端拿到“死链接”。
            client.stat_object(bucket_name=self._bucket_name, object_name=object_name)
            url = client.presigned_get_object(
                bucket_name=self._bucket_name,
                object_name=object_name,
                expires=7 * 24 * 3600,  # 7 天有效期
            )
            self._log_metric("presign", True, time.perf_counter() - t0, object_name)
            return url

        except Exception as e:
            logger.error("MinIO presign URL failed: %s", e)
            self._log_metric("presign", False, time.perf_counter() - t0, locals().get("object_name", ""), error=str(e))
            raise RuntimeError(f"MinIO 获取图片 URL 失败: {e}") from e

    def delete_image(self, img_id: str, extension: str = "jpg"):
        """
        删除图片。
        
        Args:
            img_id: 格式 "{tenant_id}:{dataset_id}:{document_id}:{chunk_key}"
            extension: 文件扩展名
        """
        t0 = time.perf_counter()
        try:
            if ":" in img_id:
                tenant_id, dataset_id, document_id, chunk_key = img_id.split(":", 3)
                object_name = f"images/{tenant_id}/{dataset_id}/{document_id}/{chunk_key}.{extension}"
            else:
                dataset_id, chunk_id = img_id.split("-", 1)
                object_name = f"images/{dataset_id}/{chunk_id}.{extension}"

            client = self._get_client()
            client.remove_object(
                bucket_name=self._bucket_name,
                object_name=object_name,
            )
            logger.info("Image deleted: %s", object_name)
            self._log_metric("delete", True, time.perf_counter() - t0, object_name)

        except S3Error as e:
            logger.warning("MinIO delete image failed: %s", e)
            self._log_metric("delete", False, time.perf_counter() - t0, locals().get("object_name", ""), error=str(e))

    def delete_dataset_images(self, tenant_id: str, dataset_id: str):
        """
        删除整个知识库的所有图片。
        
        Args:
            tenant_id: 租户 ID
            dataset_id: 知识库 ID
        """
        t0 = time.perf_counter()
        try:
            client = self._get_client()
            prefix = f"images/{tenant_id}/{dataset_id}/"
            
            objects = client.list_objects(
                bucket_name=self._bucket_name,
                prefix=prefix,
                recursive=True,
            )
            
            for obj in objects:
                client.remove_object(
                    bucket_name=self._bucket_name,
                    object_name=obj.object_name,
                )
            
            logger.info("All images deleted for dataset %s", dataset_id)
            self._log_metric("delete_dataset", True, time.perf_counter() - t0, prefix)

        except S3Error as e:
            logger.warning("MinIO delete dataset images failed: %s", e)
            self._log_metric("delete_dataset", False, time.perf_counter() - t0, prefix, error=str(e))

    def _log_metric(self, op: str, success: bool, elapsed: float, object_name: str, error: Optional[str] = None):
        """简单的 JSON 行日志，便于外部采集/监控。"""
        try:
            self._metrics_path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "op": op,
                "success": success,
                "elapsed_ms": round(elapsed * 1000, 2),
                "object": object_name,
                "bucket": self._bucket_name,
                "ts": time.time(),
            }
            if error:
                record["error"] = error
            with self._metrics_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            # 监控不应影响主流程
            pass


# 全局实例
minio_service = MinIOService()
