"""
Parse cache for deterministic parser results.

Goal:
- Avoid re-running expensive parsing backends for identical inputs by caching the parsed
  per-page markdown output.

Design constraints:
- Must be safe-by-default (disabled unless explicitly enabled).
- Must not require heavyweight deps.
- Cache storage is best-effort and should never fail ingestion.

Implementation:
- Store JSON blobs in MinIO (when enabled) under a stable key:
    sha256(file) + resolved_backend + config_hash (+ version)
- Enforce TTL client-side by checking stored created_at timestamps.
"""

import contextlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping

from app.core.config import settings
from app.parsing.backends import require_resolved_parser_backend
from app.rag.core.hashing import stable_hash, stable_json_dumps
from app.rag.core.logging import get_logger
from app.storage.object.minio import minio_service

logger = get_logger("services.parse_cache")


SCHEMA = "mimirq.parse_cache.v2"


def _parse_iso(ts: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(ts or "").strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except Exception:
        return None


def _age_seconds(created_at: str) -> float | None:
    dt = _parse_iso(created_at)
    if dt is None:
        return None
    return max(0.0, (datetime.now(UTC) - dt).total_seconds())


def build_parse_cache_key(
    *,
    file_sha256: str,
    resolved_backend: str,
    config_hash: str,
    version: str,
) -> str:
    payload = {
        "schema": SCHEMA,
        "file_sha256": str(file_sha256 or "").strip().lower(),
        "backend": str(resolved_backend or "").strip().lower(),
        "config_hash": str(config_hash or "").strip(),
        "version": str(version or "").strip(),
    }
    return stable_hash(stable_json_dumps(payload), length=32)


def build_parse_cache_object_name(
    *,
    tenant_id: str,
    dataset_id: str,
    cache_key: str,
) -> str:
    tid = str(tenant_id or "").strip()
    did = str(dataset_id or "").strip()
    key = str(cache_key or "").strip()
    if not tid or not did or not key:
        raise ValueError("invalid_parse_cache_object_name_components")
    prefix = str(settings.PARSE_CACHE_MINIO_PREFIX or "parse_cache").strip().strip("/")
    if not prefix:
        prefix = "parse_cache"
    return f"{prefix}/{tid}/{did}/{key}.json"


@dataclass(frozen=True, slots=True)
class ParseCacheEntry:
    created_at: str
    file_sha256: str
    resolved_backend: str
    config_hash: str
    documents: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "created_at": self.created_at,
            "file_sha256": self.file_sha256.strip().lower(),
            "resolved_backend": require_resolved_parser_backend(self.resolved_backend),
            "config_hash": self.config_hash.strip(),
            "documents": list(self.documents),
        }

    @staticmethod
    def from_obj(obj: Any) -> "ParseCacheEntry | None":
        if not isinstance(obj, Mapping):
            return None
        if obj.get("schema") != SCHEMA:
            return None
        required_text = ("created_at", "file_sha256", "resolved_backend", "config_hash")
        if any(not isinstance(obj.get(key), str) or not obj[key].strip() for key in required_text):
            return None
        try:
            resolved_backend = require_resolved_parser_backend(obj["resolved_backend"])
        except ValueError:
            return None
        docs = obj.get("documents")
        if not isinstance(docs, list):
            return None
        cleaned_docs: list[dict[str, Any]] = []
        for it in docs:
            if not isinstance(it, Mapping):
                return None
            page_content = it.get("page_content")
            if not isinstance(page_content, str):
                return None
            meta = it.get("metadata", {})
            if not isinstance(meta, Mapping):
                return None
            meta_d: dict[str, Any] = dict(meta)
            document_id = it.get("id")
            if document_id is not None and not isinstance(document_id, str):
                return None
            # Best-effort strip unstable/local-only fields (avoid stale paths).
            for k in ("artifact_dir", "asset_base_dir", "image_path"):
                meta_d.pop(k, None)
            cleaned_docs.append(
                {
                    "page_content": page_content,
                    "metadata": meta_d,
                    "id": document_id,
                }
            )
        return ParseCacheEntry(
            created_at=obj["created_at"],
            file_sha256=obj["file_sha256"].strip().lower(),
            resolved_backend=resolved_backend,
            config_hash=obj["config_hash"].strip(),
            documents=cleaned_docs,
        )


def get_parse_cache(
    *,
    tenant_id: str,
    dataset_id: str,
    cache_key: str,
    ttl_sec: int,
    max_bytes: int,
) -> tuple[ParseCacheEntry | None, int | None]:
    """
    Return (entry, age_ms).
    """
    if not bool(settings.PARSE_CACHE_ENABLED):
        return None, None
    if not bool(settings.MINIO_ENABLED):
        return None, None
    ttl_i = max(0, int(ttl_sec or 0))
    max_bytes_i = max(0, int(max_bytes or 0))
    if ttl_i <= 0 or max_bytes_i <= 0:
        return None, None

    try:
        object_name = build_parse_cache_object_name(
            tenant_id=str(tenant_id),
            dataset_id=str(dataset_id),
            cache_key=str(cache_key),
        )
    except Exception:
        return None, None

    try:
        raw = minio_service.get_object_bytes(object_name=object_name, max_bytes=max_bytes_i)
    except Exception:
        return None, None

    try:
        obj = json.loads(raw.decode("utf-8"))
    except Exception:
        return None, None

    entry = ParseCacheEntry.from_obj(obj)
    if entry is None:
        return None, None

    age_s = _age_seconds(entry.created_at)
    if age_s is None:
        return None, None
    age_ms = int(round(age_s * 1000))
    if ttl_i > 0 and age_s > float(ttl_i):
        # Best-effort cleanup of stale cache (do not fail).
        with contextlib.suppress(Exception):
            minio_service.delete_object(object_name=object_name)
        return None, None

    return entry, age_ms


def set_parse_cache(
    *,
    tenant_id: str,
    dataset_id: str,
    cache_key: str,
    entry: ParseCacheEntry,
    max_bytes: int,
) -> bool:
    if not bool(settings.PARSE_CACHE_ENABLED):
        return False
    if not bool(settings.MINIO_ENABLED):
        return False
    max_bytes_i = max(0, int(max_bytes or 0))
    if max_bytes_i <= 0:
        return False

    try:
        object_name = build_parse_cache_object_name(
            tenant_id=str(tenant_id),
            dataset_id=str(dataset_id),
            cache_key=str(cache_key),
        )
    except Exception:
        return False

    try:
        blob = json.dumps(entry.to_dict(), ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    except Exception:
        return False
    if len(blob) > max_bytes_i:
        return False

    try:
        minio_service.put_object_bytes(
            object_name=object_name,
            data=blob,
            content_type="application/json",
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.info("Parse cache set failed (ignored): %s", str(exc)[:200])
        return False


__all__ = [
    "ParseCacheEntry",
    "build_parse_cache_key",
    "get_parse_cache",
    "set_parse_cache",
]
