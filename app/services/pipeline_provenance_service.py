import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.core.build_info import get_build_sha
from app.rag.core.logging import get_logger

logger = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def canonical_json_sha256(value: Any) -> str:
    """
    Canonical JSON SHA256 hash helper.

    - sort_keys=true for stable ordering
    - separators without whitespace for stable encoding
    - ensure_ascii=false to avoid needless escaping (still deterministic)
    - default=str to keep this best-effort and non-throwing on odd types
    """
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _coerce_versions_dict(meta: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    raw = (
        (dict((meta if meta is not None else {})).get("pipeline_provenance_versions") or {})
        if isinstance(meta, Mapping)
        else {}
    )
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for k, v in raw.items():
        key = str(k or "").strip()
        if not key:
            continue
        if isinstance(v, dict):
            out[key] = dict(v)
        else:
            out[key] = {"value": v}
    return out


def upsert_pipeline_provenance_version(
    meta: dict[str, Any] | None,
    *,
    pipeline_hash: str,
    snapshot: dict[str, Any] | None,
    max_versions: int = 20,
) -> dict[str, Any]:
    """
    Upsert a per-pipeline_hash provenance snapshot into document metadata.

    Storage:
      metadata.pipeline_provenance_versions[pipeline_hash] = snapshot

    Capping:
    - Best-effort cap by `created_at` (ISO string) to keep metadata bounded.
    """
    base = dict((meta if meta is not None else {}))
    ph = str(pipeline_hash or "").strip()
    if not ph:
        return base

    versions = _coerce_versions_dict(base)
    snap = dict((snapshot if snapshot is not None else {}))
    snap.setdefault("pipeline_hash", ph)
    snap.setdefault("created_at", _now_iso())
    versions[ph] = snap

    cap = max(0, int(max_versions or 0))
    if cap > 0 and len(versions) > cap:
        # Remove oldest by created_at string (ISO sorts lexicographically).
        items: list[tuple[str, str]] = []
        for key, payload in versions.items():
            ts = str(payload.get("created_at") or "")
            items.append((ts, key))
        items.sort(key=lambda item: (item[0] or "", item[1]))

        while len(versions) > cap and items:
            _ts, key = items.pop(0)
            if key == ph and items:
                # Avoid deleting the just-upserted version when possible.
                continue
            versions.pop(key, None)

        # Final fallback: drop arbitrary items until capped.
        while len(versions) > cap:
            versions.pop(next(iter(versions)), None)

    base["pipeline_provenance_versions"] = versions
    return base


def _clean_rule_packs(value: Any, *, limit: int = 20) -> list[str]:
    out: list[str] = []
    if not isinstance(value, list):
        return out
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, str):
            continue
        key = raw.strip()
        if not key:
            continue
        norm = key.lower()
        if norm in seen:
            continue
        seen.add(norm)
        out.append(key[:64])
        if len(out) >= max(0, int(limit or 0)):
            break
    return out


def _clean_preprocess_steps(value: Any, *, limit: int = 30) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return out
    for raw in value:
        if not isinstance(raw, dict):
            continue
        sid = str(raw.get("id") or "").strip()
        if not sid:
            continue
        params = raw.get("params")
        params_dict = dict(params) if isinstance(params, dict) else {}
        out.append({"id": sid[:64], "params": params_dict})
        if len(out) >= max(0, int(limit or 0)):
            break
    return out


def build_pipeline_version_snapshot(
    *,
    meta: Mapping[str, Any] | None,
    pipeline_hash: str | None = None,
    created_at: str | None = None,
    build_sha: str | None = None,
    embedding_space_hash: str | None = None,
) -> dict[str, Any]:
    """
    Build a stable, UI-facing provenance snapshot for a specific pipeline_hash version.

    The snapshot uses the supplied version and existing metadata:
    - It avoids large payloads (no markdown/chunk text).
    - It prioritizes stable hashes over exhaustive config capture.
    """
    m = meta if meta is not None else {}
    ph = m.get("pipeline_hash") if pipeline_hash is None else pipeline_hash
    if ph is not None:
        ph = ph.strip()

    created = _now_iso() if created_at is None else created_at
    build = build_sha if build_sha is not None else get_build_sha()

    if embedding_space_hash is None:
        try:
            from app.rag.embedding.utils import current_embedding_space_hash
        except Exception:
            emb = None
        else:
            emb = current_embedding_space_hash()
    else:
        emb = embedding_space_hash

    parser_backend = m.get("parser_backend")
    chunk_strategy = m.get("chunk_strategy")

    ingestion = m.get("ingestion") if isinstance(m.get("ingestion"), dict) else {}
    preprocess_cfg = ingestion.get("preprocess") if isinstance(ingestion.get("preprocess"), dict) else {}
    preprocess_steps = _clean_preprocess_steps(preprocess_cfg.get("steps"))

    preprocess_result_raw = m.get("preprocess") if isinstance(m.get("preprocess"), dict) else {}
    # Avoid leaking internal filesystem paths via ops/UI endpoints; keep only safe fields.
    preprocess_result = {
        k: preprocess_result_raw.get(k)
        for k in (
            "changed",
            "size_before",
            "size_after",
            "sha256_before",
            "sha256_after",
            "steps",
            "warnings",
        )
        if k in preprocess_result_raw
    }

    pipeline_effective = m.get("pipeline_effective") if isinstance(m.get("pipeline_effective"), dict) else {}
    pipeline_meta = m.get("pipeline") if isinstance(m.get("pipeline"), dict) else {}

    governance_rule_packs = _clean_rule_packs(m.get("governance_rule_packs"))
    governance_version = m.get("governance_version")

    # ---- Transform hashes (per step) ----
    preprocess_obj = {
        "v": "1",
        "build_sha": build,
        "pipeline_hash": ph,
        "steps": preprocess_steps,
    }
    preprocess_hash = canonical_json_sha256(preprocess_obj)

    parse_obj = {
        "v": "1",
        "build_sha": build,
        "pipeline_hash": ph,
        "parser_backend": parser_backend,
        # Include the user-requested backend if present (helps explain diffs).
        "parser_backend_requested": m.get("parser_backend_requested"),
        "file_type": m.get("file_type"),
    }
    parse_hash = canonical_json_sha256(parse_obj)

    governance_obj = {
        "v": "1",
        "build_sha": build,
        "pipeline_hash": ph,
        "governance_version": governance_version,
        "rule_packs": governance_rule_packs,
        "effective": {
            k: pipeline_effective.get(k) for k in sorted(pipeline_effective.keys()) if str(k).startswith("governance_")
        },
        # Include any declared pipeline.governance metadata (e.g. custom regex rules) when present.
        "pipeline": (pipeline_meta.get("governance") if isinstance(pipeline_meta.get("governance"), dict) else {}),
    }
    governance_hash = canonical_json_sha256(governance_obj)

    chunk_obj = {
        "v": "1",
        "build_sha": build,
        "pipeline_hash": ph,
        "chunk_strategy": chunk_strategy,
        "chunk_strategy_requested": m.get("chunk_strategy_requested"),
        "chunk_size": pipeline_effective.get("chunk_size"),
        "chunk_overlap": pipeline_effective.get("chunk_overlap"),
        "chunk_merge_small_min_chars": pipeline_effective.get("chunk_merge_small_min_chars"),
        "chunk_strategy_params": pipeline_effective.get("chunk_strategy_params")
        if isinstance(pipeline_effective.get("chunk_strategy_params"), dict)
        else {},
    }
    chunk_hash = canonical_json_sha256(chunk_obj)

    index_obj = {
        "v": "1",
        "build_sha": build,
        "pipeline_hash": ph,
        "embedding_space_hash": emb,
        "vector_backend": None,
        "effective": {
            k: pipeline_effective.get(k)
            for k in sorted(pipeline_effective.keys())
            if k
            in {
                "chunk_vector_enabled",
                "bm25_index_enabled",
                "kg_enabled",
                "event_vector_enabled",
                "entity_vector_enabled",
            }
        },
        "pipeline": (pipeline_meta.get("index") if isinstance(pipeline_meta.get("index"), dict) else {}),
    }
    try:
        from app.core.config import settings
    except Exception as exc:
        logger.debug("Ignoring settings import failure while building index provenance: %s", exc)
    else:
        index_obj["vector_backend"] = settings.VECTOR_BACKEND
    index_hash = canonical_json_sha256(index_obj)

    pipeline_run_hash = canonical_json_sha256(
        {
            "preprocess": preprocess_hash,
            "parse": parse_hash,
            "governance": governance_hash,
            "chunk": chunk_hash,
            "index": index_hash,
        }
    )[:16]

    return {
        "pipeline_hash": ph,
        "created_at": created,
        "build_sha": build,
        "embedding_space_hash": emb,
        "parser_backend": parser_backend,
        "chunk_strategy": chunk_strategy,
        "transforms": {
            "preprocess": {
                "version": "1",
                "hash": preprocess_hash,
                "steps": preprocess_steps,
                "result": preprocess_result,
            },
            "parse": {"version": "1", "hash": parse_hash, "parser_backend": parser_backend},
            "governance": {
                "version": "1",
                "hash": governance_hash,
                "enabled": bool(pipeline_effective.get("governance_enabled") or m.get("governance_enabled")),
                "rule_packs": governance_rule_packs,
                "governance_version": governance_version,
            },
            "chunk": {
                "version": "1",
                "hash": chunk_hash,
                "chunk_strategy": chunk_strategy,
                "chunk_size": pipeline_effective.get("chunk_size"),
                "chunk_overlap": pipeline_effective.get("chunk_overlap"),
            },
            "index": {
                "version": "1",
                "hash": index_hash,
                "embedding_space_hash": emb,
                "vector_backend": index_obj["vector_backend"],
            },
        },
        "pipeline_run_hash": pipeline_run_hash,
    }
