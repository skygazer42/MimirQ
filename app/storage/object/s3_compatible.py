
import time
from pathlib import Path
from typing import Any

from minio import Minio

from app.storage.object.minio import MinIOService


class S3CompatibleObjectStore(MinIOService):
    """
    Thin S3-compatible object store backed by the MinIO Python SDK.

    Scope:
    - reuse the existing MinIOService behavior and method surface
    - allow provider-specific factory routing for S3 / OSS / COS style endpoints
    - avoid changing existing MinIO callers
    """

    def __init__(
        self,
        *,
        provider_name: str,
        enabled: bool,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket_name: str,
        use_ssl: bool,
        metrics_log_path: str,
        documents_enabled: bool,
    ) -> None:
        super().__init__()
        self._provider_name = str(provider_name or "s3_compatible").strip().lower() or "s3_compatible"
        self._enabled = bool(enabled)
        self._endpoint = str(endpoint or "").strip()
        self._access_key = str(access_key or "").strip()
        self._secret_key = str(secret_key or "").strip()
        self._bucket_name = str(bucket_name or "").strip()
        self._use_ssl = bool(use_ssl)
        self._documents_enabled = bool(documents_enabled)
        self._metrics_path = Path(metrics_log_path or "./logs/object_store_metrics.jsonl")

    def describe_backend(self) -> dict[str, Any]:
        return {
            "provider": self._provider_name,
            "enabled": self._enabled,
            "endpoint": self._endpoint,
            "bucket": self._bucket_name,
            "secure": self._use_ssl,
            "documents_enabled": self._documents_enabled,
        }

    def build_object_uri(self, bucket: str, object_name: str) -> str:
        b = str(bucket or "").strip()
        o = str(object_name or "").lstrip("/").strip()
        if not b or not o:
            raise ValueError("invalid_object_uri_components")
        return f"{self._provider_name}://{b}/{o}"

    def _get_client(self):
        if not self._enabled:
            raise RuntimeError(f"{self._provider_name} object storage is disabled")
        if not self._endpoint:
            raise RuntimeError(f"{self._provider_name} endpoint is required")
        if not self._bucket_name:
            raise RuntimeError(f"{self._provider_name} bucket is required")

        if self._client is None:
            self._client = Minio(
                endpoint=self._endpoint,
                access_key=self._access_key,
                secret_key=self._secret_key,
                secure=self._use_ssl,
            )
        if not self._bucket_ready:
            self._ensure_bucket()
        return self._client

    def health_check(self) -> dict[str, Any]:
        enabled = bool(self._enabled)
        if not enabled:
            return {"enabled": False, "status": "disabled", "provider": self._provider_name}

        base = super().health_check()
        base["provider"] = self._provider_name
        return base

    def upload_document_file(
        self,
        *,
        file_path: Path,
        tenant_id: str,
        dataset_id: str,
        document_id: str,
        extension: str,
        content_type: str | None = None,
    ) -> str:
        if not self._documents_enabled:
            raise RuntimeError(f"{self._provider_name} document storage is disabled")
        t0 = time.perf_counter()
        object_name = self.build_document_object_name(
            tenant_id=str(tenant_id),
            dataset_id=str(dataset_id),
            document_id=str(document_id),
            extension=str(extension or ""),
        )
        client = self._get_client()
        try:
            client.fput_object(
                bucket_name=self._bucket_name,
                object_name=object_name,
                file_path=str(file_path),
                content_type=content_type or "application/octet-stream",
            )
            self._log_metric("upload_doc", True, time.perf_counter() - t0, object_name)
            return self.build_object_uri(self._bucket_name, object_name)
        except Exception as exc:  # noqa: BLE001
            self._log_metric("upload_doc", False, time.perf_counter() - t0, object_name, error=str(exc))
            raise RuntimeError(f"{self._provider_name} document upload failed: {exc}") from exc


__all__ = ["S3CompatibleObjectStore"]
