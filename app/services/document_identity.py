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
    if value is None:
        return None
    raw = str(value).strip().lower()
    return raw if raw else None


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
    if pipeline_hash is None:
        return None
    ph = pipeline_hash.strip()
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
    dedup_key = build_document_dedup_key(content_sha256=normalized_sha, pipeline_hash=pipeline_hash)
    identity = {
        "schema": PIPELINE_EXECUTION_IDENTITY_SCHEMA,
        CONTENT_SHA256_KEY: normalized_sha,
        "pipeline_hash": pipeline_hash,
        "parser_backend": meta.get("parser_backend"),
        "parser_backend_requested": meta.get("parser_backend_requested"),
        "parser_backend_resolved": (
            parser_backend_resolved if parser_backend_resolved is not None else meta.get("parser_backend_resolved")
        ),
        "chunk_strategy": meta.get("chunk_strategy"),
        "chunk_strategy_requested": meta.get("chunk_strategy_requested"),
        "dedup_key": dedup_key,
    }
    meta[PIPELINE_EXECUTION_IDENTITY_KEY] = identity
    if dedup_key:
        meta[PIPELINE_EXECUTION_ID_KEY] = dedup_key
    else:
        meta.pop(PIPELINE_EXECUTION_ID_KEY, None)
    return identity
