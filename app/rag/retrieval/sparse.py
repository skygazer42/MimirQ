"""
Sparse retrieval utilities (SPLADE-style scaffolding).

This module supports:
- a deterministic sparse encoder for unit/regression tests (no model downloads)
- a small persisted sparse index format for caching per-scope sparse vectors on disk

Design constraints:
- No default behavior changes (providers are used only when enabled via settings).
- Retired neural model selections fail before encoding.
"""

import gzip
import hashlib
import json
import re
import threading
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from app.rag.core.metadata import _stringified_metadata_text
from typing import Any, Protocol

from app.core.model_execution import reject_retired_provider
from app.rag.core.logging import get_logger

logger = get_logger(__name__)

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]+|\d+|[\u4e00-\u9fff]{2,}")
_INDEX_SCHEMA_V1 = "mimirq.sparse_index.v1"
VALID_SPARSE_PROVIDERS = frozenset({"deterministic"})
_SPARSE_PROVIDER_ALIASES = {
    "det": "deterministic",
    "deterministic": "deterministic",
}
_SPARSE_STATUS_VALUES = frozenset({"ready", "disabled", "fallback"})
_SPARSE_REASON_VALUES = frozenset(
    {
        "none",
        "sparse_disabled",
        "provider_invalid",
    }
)


def normalize_sparse_provider_name(provider: str | None) -> str:
    reject_retired_provider(provider, capability="sparse")
    raw = str((provider if provider is not None else "")).strip().lower()
    if not raw:
        return "deterministic"
    return _SPARSE_PROVIDER_ALIASES.get(raw, raw)


def resolve_sparse_provider_capability(
    *,
    requested_provider: str | None,
    sparse_enabled: bool,
    default_provider: str = "deterministic",
) -> dict[str, Any]:
    """
    Resolve sparse provider capability and deterministic fallback status.

    Contract goals:
    - Keep provider normalization deterministic and low-cardinality.
    - Expose explicit fallback reasons for audit/debug/metrics.
    - Never require callers to guess whether runtime fell back to deterministic.
    """
    requested_raw = str((requested_provider if requested_provider is not None else "")).strip().lower()
    requested_norm = normalize_sparse_provider_name(requested_raw)
    default_norm = normalize_sparse_provider_name(default_provider)
    if default_norm not in VALID_SPARSE_PROVIDERS:
        default_norm = "deterministic"

    provider_supported = requested_norm in VALID_SPARSE_PROVIDERS

    effective_provider = requested_norm if provider_supported else default_norm
    status = "ready"
    reason = "none"
    if not bool(sparse_enabled):
        status = "disabled"
        reason = "sparse_disabled"
    elif not provider_supported:
        status = "fallback"
        reason = "provider_invalid"
        effective_provider = default_norm

    return {
        "requested_provider": requested_raw,
        "requested_provider_normalized": requested_norm,
        "effective_provider": effective_provider,
        "provider_supported": provider_supported,
        "model_required": False,
        "model_configured": False,
        "status": status if status in _SPARSE_STATUS_VALUES else "fallback",
        "reason": reason if reason in _SPARSE_REASON_VALUES else "provider_invalid",
    }


def _norm_token(t: str) -> str:
    tok = t.strip()
    if not tok:
        return ""
    return tok.casefold() if tok.isascii() else tok


def tokenize(text: str) -> list[str]:
    raw = text
    out: list[str] = []
    seen: set[str] = set()
    for m in _TOKEN_RE.finditer(raw):
        tok = _norm_token(m.group(0))
        if not tok:
            continue
        if tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
    return out


def parse_synonyms(raw: str) -> dict[str, set[str]]:
    """
    Parse comma-separated synonym pairs like: "kubernetes:k8s,postgresql:postgres".

    Output is symmetric: both sides expand to each other.
    """
    text = raw.strip()
    if not text:
        return {}

    pairs = [p.strip() for p in text.split(",") if p and p.strip()]
    out: dict[str, set[str]] = {}
    for p in pairs:
        if ":" not in p:
            continue
        left, right = p.split(":", 1)
        a = _norm_token(left)
        b = _norm_token(right)
        if not a or not b or a == b:
            continue
        out.setdefault(a, set()).add(b)
        out.setdefault(b, set()).add(a)
    return out


@dataclass(frozen=True)
class SparseVector:
    weights: dict[str, float]


class SparseEncoder(Protocol):
    def encode_batch(self, texts: Sequence[str]) -> list[SparseVector]:
        """Encode texts into sparse vectors (batch-friendly)."""


class DeterministicSparseEncoder:
    """
    Deterministic sparse encoder intended for tests.

    Scoring behavior:
    - exact token weights are 1.0
    - synonym-expanded tokens are `synonym_weight` (default 0.9)

    This is NOT a replacement for SPLADE; it is scaffolding to validate plumbing.
    """

    def __init__(
        self,
        *,
        synonyms: dict[str, set[str]] | None = None,
        synonym_weight: float = 0.9,
    ) -> None:
        self._synonyms = synonyms if synonyms is not None else {}
        self._syn_w = float(synonym_weight)

    def encode(self, text: str) -> SparseVector:
        toks = tokenize(text)
        if not toks:
            return SparseVector(weights={})

        weights: Counter[str] = Counter()
        for t in toks:
            weights[t] = max(weights.get(t, 0.0), 1.0)
            for syn in self._synonyms.get(t, set()):
                if not syn or syn == t:
                    continue
                weights[syn] = max(weights.get(syn, 0.0), self._syn_w)

        return SparseVector(weights=dict(weights))

    def encode_batch(self, texts: Sequence[str]) -> list[SparseVector]:
        return [self.encode(t) for t in (texts or [])]


_ENCODER_LOCK = threading.Lock()
_ENCODER_CACHE: dict[str, SparseEncoder] = {}


def get_sparse_encoder(
    *, provider: str, synonyms: dict[str, set[str]] | None = None, synonyms_raw: str = ""
) -> SparseEncoder:
    """Return the deterministic test encoder; neural SPLADE execution has been retired."""
    p = normalize_sparse_provider_name(provider)
    if p not in VALID_SPARSE_PROVIDERS:
        raise ValueError(f"Unsupported sparse provider: {provider}")
    if synonyms is not None:
        return DeterministicSparseEncoder(synonyms=synonyms)
    key = f"deterministic:{synonyms_raw}"
    with _ENCODER_LOCK:
        cached = _ENCODER_CACHE.get(key)
        if cached is not None:
            return cached
        inst = DeterministicSparseEncoder(synonyms=parse_synonyms(synonyms_raw))
        _ENCODER_CACHE[key] = inst
        return inst


def _stable_key(text: str) -> str:
    return hashlib.sha256((text).encode("utf-8", errors="ignore")).hexdigest()


def build_sparse_provider_config(*, provider: str, synonyms_raw: str = "") -> dict[str, Any]:
    p = normalize_sparse_provider_name(provider)
    if p not in VALID_SPARSE_PROVIDERS:
        raise ValueError(f"Unsupported sparse provider: {provider}")
    return {"provider": p, "synonyms_raw": synonyms_raw}


def _coerce_sparse_vector(obj: Any) -> SparseVector:
    """Read existing sparse vectors from the persisted index representation."""
    if isinstance(obj, SparseVector):
        return obj
    if isinstance(obj, dict):
        weights: dict[str, float] = {}
        for k, v in obj.items():
            if k is None or v is None:
                continue
            try:
                weights[str(k)] = float(v)
            except Exception:
                get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                continue
        return SparseVector(weights=weights)
    return SparseVector(weights={})


class SparseIndexStore:
    def __init__(self, *, base_dir: str) -> None:
        self._base = Path(base_dir.strip() or "./data/sparse_indexes")

    def _index_path(self, *, cache_key: str, provider_config: dict[str, Any]) -> Path:
        key = f"{cache_key}|{json.dumps(provider_config, sort_keys=True, ensure_ascii=True)}"
        digest = _stable_key(key)[:24]
        provider = str(provider_config.get("provider") or "deterministic").strip().lower() or "deterministic"
        sub = self._base / provider
        return sub / f"index_{digest}.json.gz"

    def load(
        self,
        *,
        cache_key: str,
        provider_config: dict[str, Any],
        expected_fingerprint: str,
        expected_version_token: str | None = None,
    ) -> dict[str, SparseVector] | None:
        path = self._index_path(cache_key=cache_key, provider_config=provider_config)
        if not path.exists():
            return None
        try:
            raw = gzip.decompress(path.read_bytes()).decode("utf-8", errors="ignore")
            obj = json.loads(raw)
        except Exception:
            return None
        if not isinstance(obj, dict):
            return None
        if obj.get("schema") != _INDEX_SCHEMA_V1:
            return None
        if obj.get("corpus_fingerprint") != expected_fingerprint:
            return None
        expected_token = str((expected_version_token if expected_version_token is not None else "")).strip()
        stored_token = _stringified_metadata_text(obj, "version_token")
        if expected_token and stored_token != expected_token:
            return None
        vecs = obj.get("vectors")
        if not isinstance(vecs, dict):
            return None
        out: dict[str, SparseVector] = {}
        for doc_id, weights in vecs.items():
            if not doc_id:
                continue
            out[str(doc_id)] = _coerce_sparse_vector(weights)
        return out

    def save(
        self,
        *,
        cache_key: str,
        provider_config: dict[str, Any],
        corpus_fingerprint: str,
        vectors: dict[str, SparseVector],
        version_token: str | None = None,
    ) -> Path:
        path = self._index_path(cache_key=cache_key, provider_config=provider_config)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            return path

        payload = {
            "schema": _INDEX_SCHEMA_V1,
            "provider": provider_config["provider"],
            "provider_config": dict(provider_config),
            "corpus_fingerprint": corpus_fingerprint,
            "version_token": str((version_token if version_token is not None else "")).strip(),
            "doc_count": len(vectors or {}),
            "vectors": {
                k: (v.weights if isinstance(v, SparseVector) else _coerce_sparse_vector(v).weights)
                for k, v in (vectors or {}).items()
            },
        }
        try:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            path.write_bytes(gzip.compress(data))
        except Exception as exc:
            logger.debug("Ignoring sparse index write failure: %s", exc)
        return path


def dot_product(query: SparseVector, doc: SparseVector) -> float:
    if not query.weights or not doc.weights:
        return 0.0
    # Iterate over smaller map.
    if len(query.weights) > len(doc.weights):
        query, doc = doc, query
    total = 0.0
    for k, qw in query.weights.items():
        dw = doc.weights.get(k)
        if dw is None:
            continue
        total += float(qw) * float(dw)
    return total


def topk_scores(
    *,
    query_vec: SparseVector,
    docs: dict[str, SparseVector],
    k: int,
) -> list[tuple[str, float]]:
    kk = max(0, int(k or 0))
    if kk <= 0 or not docs:
        return []
    scored: list[tuple[str, float]] = []
    for doc_id, dvec in docs.items():
        s = dot_product(query_vec, dvec)
        if s <= 0.0:
            continue
        scored.append((str(doc_id), s))
    scored.sort(key=lambda x: (-x[1], x[0]))
    return scored[:kk]


def ensure_str_keys(values: Iterable[object]) -> list[str]:
    out: list[str] = []
    for v in values:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            out.append(s)
    return out
