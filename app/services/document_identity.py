"""Document ingestion identity helpers."""

import hashlib
import json
from typing import Any

CONTENT_SHA256_KEY = "content_sha256"
LEGACY_FILE_SHA256_KEY = "file_sha256"
PIPELINE_EXECUTION_IDENTITY_KEY = "pipeline_execution_identity"
PIPELINE_EXECUTION_ID_KEY = "pipeline_execution_id"
PIPELINE_EXECUTION_IDENTITY_SCHEMA = "mimirq.pipeline_execution_identity.v1"


def normalize_content_sha256(value: Any) -> str | None:
    raw = str(value or "").strip().lower()
    return raw or None


def get_content_sha256(meta: dict[str, Any] | None) -> str | None:
    payload = meta if isinstance(meta, dict) else {}
    for key in (CONTENT_SHA256_KEY, LEGACY_FILE_SHA256_KEY):
        normalized = normalize_content_sha256(payload.get(key))
        if normalized:
            return normalized
    identity = payload.get(PIPELINE_EXECUTION_IDENTITY_KEY)
    if isinstance(identity, dict):
        return normalize_content_sha256(identity.get(CONTENT_SHA256_KEY))
    return None


def set_content_sha256(meta: dict[str, Any], content_sha256: str | None) -> str | None:
    normalized = normalize_content_sha256(content_sha256)
    if normalized is None:
        meta.pop(CONTENT_SHA256_KEY, None)
        return None
    meta[CONTENT_SHA256_KEY] = normalized
    # Keep the legacy key for older readers/tests until the rest of the codebase flips.
    meta[LEGACY_FILE_SHA256_KEY] = normalized
    return normalized


def build_document_dedup_key(*, content_sha256: str | None, pipeline_hash: str | None) -> str | None:
    sha = normalize_content_sha256(content_sha256)
    ph = str(pipeline_hash or "").strip()
    if not sha or not ph:
        return None
    return f"{sha}:{ph}"


def compute_pipeline_hash(doc_metadata: dict[str, Any]) -> str:
    relevant = {
        "parser_backend": doc_metadata.get("parser_backend"),
        "parser_backend_requested": doc_metadata.get("parser_backend_requested"),
        "chunk_strategy": doc_metadata.get("chunk_strategy"),
        "chunk_strategy_requested": doc_metadata.get("chunk_strategy_requested"),
        "pipeline": doc_metadata.get("pipeline") or {},
    }
    raw = json.dumps(relevant, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def sync_pipeline_execution_identity(
    meta: dict[str, Any],
    *,
    content_sha256: str | None,
    pipeline_hash: str | None,
    parser_backend_resolved: str | None = None,
) -> dict[str, Any]:
    normalized_sha = set_content_sha256(meta, content_sha256)
    pipeline_hash_norm = str(pipeline_hash or "").strip() or None
    dedup_key = build_document_dedup_key(content_sha256=normalized_sha, pipeline_hash=pipeline_hash_norm)
    identity = {
        "schema": PIPELINE_EXECUTION_IDENTITY_SCHEMA,
        CONTENT_SHA256_KEY: normalized_sha,
        "pipeline_hash": pipeline_hash_norm,
        "parser_backend": str(meta.get("parser_backend") or "").strip() or None,
        "parser_backend_requested": str(meta.get("parser_backend_requested") or "").strip() or None,
        "parser_backend_resolved": str(parser_backend_resolved or meta.get("parser_backend_resolved") or "").strip()
        or None,
        "chunk_strategy": str(meta.get("chunk_strategy") or "").strip() or None,
        "chunk_strategy_requested": str(meta.get("chunk_strategy_requested") or "").strip() or None,
        "dedup_key": dedup_key,
    }
    meta[PIPELINE_EXECUTION_IDENTITY_KEY] = identity
    if dedup_key:
        meta[PIPELINE_EXECUTION_ID_KEY] = dedup_key
    else:
        meta.pop(PIPELINE_EXECUTION_ID_KEY, None)
    return identity
