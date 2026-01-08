"""
MinIO object storage service for images extracted during document parsing.
"""
import asyncio
import io
from typing import Any, Optional, BinaryIO, Union, List, Dict
import json
import time
from pathlib import Path

from app.core.config import settings
from app.rag.core.logging import get_logger


logger = get_logger("storage.minio")


class MinIOService:
    """MinIO object storage service."""

    def __init__(self):
        self._client: Optional[Any] = None
        self._bucket_name = settings.MINIO_BUCKET_NAME
        self._bucket_ready = False
        self._metrics_path = Path(settings.MINIO_METRICS_LOG_PATH)

    def _get_client(self):
        """Lazily initialize the MinIO client."""
        if not bool(getattr(settings, "MINIO_ENABLED", False)):
            raise RuntimeError("MinIO is disabled (MINIO_ENABLED=false)")

        if self._client is None:
            try:
                from minio import Minio  # type: ignore
            except ImportError as exc:
                raise RuntimeError(
                    "MinIO dependencies are missing. Install `minio` or set MINIO_ENABLED=false."
                ) from exc
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
        """Ensure the bucket exists; create it if missing."""
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
        except Exception as e:  # noqa: BLE001
            # Bucket may be created concurrently by another process.
            if getattr(e, "code", None) in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                self._bucket_ready = True
                return
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
        Upload an image to MinIO and return the img_id.

        Args:
            image_data: image bytes or a file-like object
            tenant_id: tenant ID
            dataset_id: dataset ID
            document_id: document ID
            chunk_key: chunk identifier (usually chunk_index)
            extension: file extension (default: jpg)

        Returns:
            img_id: format "{tenant_id}:{dataset_id}:{document_id}:{chunk_key}"
        """
        t0 = time.perf_counter()
        img_id = f"{tenant_id}:{dataset_id}:{document_id}:{chunk_key}"
        object_name = f"images/{tenant_id}/{dataset_id}/{document_id}/{chunk_key}.{extension}"

        try:
            client = self._get_client()

            # Convert to a byte stream.
            if isinstance(image_data, bytes):
                data_stream = io.BytesIO(image_data)
                data_length = len(image_data)
            else:
                # Assume a file-like object.
                data_stream = image_data
                data_stream.seek(0, 2)  # Seek to end.
                data_length = data_stream.tell()
                data_stream.seek(0)  # Reset to start.

            # Upload to MinIO.
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

        except Exception as e:  # noqa: BLE001
            logger.error("MinIO upload failed: %s", e)
            self._log_metric("upload", False, time.perf_counter() - t0, object_name, error=str(e))
            raise RuntimeError(f"MinIO image upload failed: {e}") from e

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
        Upload an image to MinIO asynchronously (run sync work in a thread pool).

        Args:
            image_data: image bytes or a file-like object
            tenant_id: tenant ID
            dataset_id: dataset ID
            document_id: document ID
            chunk_key: chunk identifier (usually chunk_index)
            extension: file extension (default: jpg)

        Returns:
            img_id: format "{tenant_id}:{dataset_id}:{document_id}:{chunk_key}"
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
        Upload images to MinIO concurrently in batches.

        Args:
            images: list of dicts, each containing:
                - image_data: image bytes
                - tenant_id: tenant ID
                - dataset_id: dataset ID
                - document_id: document ID
                - chunk_key: chunk identifier
                - extension: file extension (optional, default: jpg)
            max_concurrent: max concurrent uploads (default: 10)

        Returns:
            list of results, each containing:
                - success: whether the upload succeeded
                - img_id: image ID (on success)
                - error: error message (on failure)
                - chunk_key: original chunk_key
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
        
        # Process exceptions.
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
        Get an image access URL (presigned, valid for 7 days).

        Args:
            img_id: format "{tenant_id}:{dataset_id}:{document_id}:{chunk_key}"
            extension: file extension

        Returns:
            presigned URL
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
            # Presigned URLs do not check object existence; validate to avoid dead links.
            client.stat_object(bucket_name=self._bucket_name, object_name=object_name)
            url = client.presigned_get_object(
                bucket_name=self._bucket_name,
                object_name=object_name,
                expires=7 * 24 * 3600,  # 7-day expiry
            )
            self._log_metric("presign", True, time.perf_counter() - t0, object_name)
            return url

        except Exception as e:
            logger.error("MinIO presign URL failed: %s", e)
            self._log_metric("presign", False, time.perf_counter() - t0, locals().get("object_name", ""), error=str(e))
            raise RuntimeError(f"MinIO get image URL failed: {e}") from e

    def delete_image(self, img_id: str, extension: str = "jpg"):
        """
        Delete an image.

        Args:
            img_id: format "{tenant_id}:{dataset_id}:{document_id}:{chunk_key}"
            extension: file extension
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

        except Exception as e:  # noqa: BLE001
            logger.warning("MinIO delete image failed: %s", e)
            self._log_metric("delete", False, time.perf_counter() - t0, locals().get("object_name", ""), error=str(e))

    def delete_dataset_images(self, tenant_id: str, dataset_id: str):
        """
        Delete all images for a dataset.

        Args:
            tenant_id: tenant ID
            dataset_id: dataset ID
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

        except Exception as e:  # noqa: BLE001
            logger.warning("MinIO delete dataset images failed: %s", e)
            self._log_metric("delete_dataset", False, time.perf_counter() - t0, prefix, error=str(e))

    def _log_metric(self, op: str, success: bool, elapsed: float, object_name: str, error: Optional[str] = None):
        """Simple JSONL metrics log for external collection/monitoring."""
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
            # Monitoring should not affect the main flow.
            pass


# Global instance
minio_service = MinIOService()
