"""
Deterministic dense candidate retrieval for ColBERT-stack experiments.

This module provides an *optional* retrieval channel that:
- builds a per-scope dense embedding index (persisted to disk, best-effort)
- retrieves top candidates with exact NumPy cosine scoring
- uses the retained deterministic hash-based embedder

Important:
- This is NOT a full ColBERT token-level index. It is an engineering scaffold that
  enables "ColBERT stack" experiments (candidate generation -> late-interaction rerank)
  without changing defaults.
"""

import hashlib
import json
import re
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from app.core.model_execution import reject_retired_provider
from app.rag.core.logging import get_logger

logger = get_logger(__name__)

_INDEX_SCHEMA_V1 = "mimirq.colbert_ann_index.v1"
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]+|[\u4e00-\u9fff]{2,}")
VALID_COLBERT_PROVIDERS = frozenset({"deterministic"})


def _stable_key(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="ignore")).hexdigest()


def _l2_normalize(x: np.ndarray) -> np.ndarray:
    if x.size == 0:
        return x
    denom = np.linalg.norm(x, axis=1, keepdims=True)
    denom = np.where(denom > 0.0, denom, 1.0)
    return x / denom


def _tokenize(text: str) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    out: list[str] = []
    for m in _TOKEN_RE.finditer(raw):
        t = (m.group(0) or "").strip()
        if not t:
            continue
        out.append(t.casefold() if t.isascii() else t)
    return out


class DenseEmbedder(Protocol):
    def encode_batch(self, texts: Sequence[str]) -> np.ndarray:
        """Return float32 array shaped [len(texts), dim]."""


class DeterministicDenseEmbedder(DenseEmbedder):
    def __init__(self, *, dim: int = 64) -> None:
        self._dim = max(8, int(dim or 0))

    def _vec_for_token(self, token: str) -> np.ndarray:
        h = hashlib.sha256(token.encode("utf-8", errors="ignore")).digest()
        b = (h * ((self._dim // len(h)) + 1))[: self._dim]
        arr = (np.frombuffer(b, dtype=np.uint8).astype(np.float32) - 127.5) / 127.5
        return arr

    def encode_batch(self, texts: Sequence[str]) -> np.ndarray:
        rows: list[np.ndarray] = []
        for t in texts or []:
            toks = _tokenize(str(t or ""))
            if not toks:
                rows.append(np.zeros((self._dim,), dtype=np.float32))
                continue
            vec = np.zeros((self._dim,), dtype=np.float32)
            for tok in toks:
                vec += self._vec_for_token(tok)
            rows.append(vec)
        mat = np.stack(rows, axis=0).astype(np.float32, copy=False)
        return _l2_normalize(mat)


_EMBEDDER_LOCK = threading.Lock()
_EMBEDDER_CACHE: dict[str, DenseEmbedder] = {}


def get_dense_embedder(*, provider: str, deterministic_dim: int = 64) -> DenseEmbedder:
    reject_retired_provider(provider, capability="colbert")
    p = str(provider or "").strip().lower() or "deterministic"
    if p != "deterministic":
        raise ValueError(f"Unsupported ColBERT provider: {provider}")
    key = f"deterministic:{int(deterministic_dim or 0)}"
    with _EMBEDDER_LOCK:
        cached = _EMBEDDER_CACHE.get(key)
        if cached is not None:
            return cached
        inst = DeterministicDenseEmbedder(dim=int(deterministic_dim or 0))
        _EMBEDDER_CACHE[key] = inst
        return inst


def build_colbert_provider_config(*, provider: str, deterministic_dim: int = 64) -> dict[str, Any]:
    reject_retired_provider(provider, capability="colbert")
    p = str(provider or "").strip().lower() or "deterministic"
    if p != "deterministic":
        raise ValueError(f"Unsupported ColBERT provider: {provider}")
    return {"provider": p, "deterministic_dim": int(deterministic_dim or 0)}


def resolve_colbert_retrieval_capability(
    *,
    colbert_enabled: bool,
    requested_provider: str | None,
    docs_count: int,
    max_docs: int,
) -> dict[str, Any]:
    """
    Resolve dense-candidate provider readiness and bounded fallback metadata.

    Contract:
    - deterministic provider is always ready
    - invalid/unsupported providers fall back to deterministic
    - oversized corpus is gated before index build to keep memory bounded
    """
    reject_retired_provider(requested_provider, capability="colbert")
    requested_raw = str((requested_provider if requested_provider is not None else "")).strip().lower()
    requested_norm = requested_raw or "deterministic"
    provider_supported = requested_norm in VALID_COLBERT_PROVIDERS
    effective_provider = requested_norm if provider_supported else "deterministic"
    status = "ready"
    reason = "none"
    ready = True

    if not bool(colbert_enabled):
        status = "disabled"
        reason = "colbert_disabled"
        ready = False
    elif int(max_docs or 0) > 0 and int(docs_count or 0) > int(max_docs or 0):
        status = "fallback"
        reason = "too_many_docs"
        ready = False
    elif not provider_supported:
        status = "fallback"
        reason = "provider_invalid"
        effective_provider = "deterministic"
        ready = True

    return {
        "requested_provider": requested_raw,
        "requested_provider_normalized": requested_norm,
        "effective_provider": effective_provider,
        "provider_supported": provider_supported,
        "status": status,
        "reason": reason,
        "ready": ready,
        "model_name_configured": False,
        "device": "cpu",
        "docs_count": max(0, int(docs_count or 0)),
        "max_docs": max(0, int(max_docs or 0)),
    }


@dataclass(frozen=True)
class ColbertAnnIndex:
    doc_ids: list[str]
    vectors: np.ndarray  # shape [N, dim], float32, L2-normalized
    corpus_fingerprint: str
    provider_config: dict[str, Any]


class ColbertAnnIndexStore:
    def __init__(self, *, base_dir: str) -> None:
        self._base = Path(str(base_dir or "").strip() or "./data/colbert_indexes")

    def _paths(self, *, cache_key: str, provider_config: dict[str, Any]) -> tuple[Path, Path]:
        key = f"{cache_key}|{json.dumps(provider_config, sort_keys=True, ensure_ascii=True)}"
        digest = _stable_key(key)[:24]
        provider = str(provider_config.get("provider") or "deterministic").strip().lower() or "deterministic"
        sub = self._base / provider
        return sub / f"index_{digest}.npz", sub / f"index_{digest}.json"

    def load(
        self,
        *,
        cache_key: str,
        provider_config: dict[str, Any],
        expected_fingerprint: str,
    ) -> ColbertAnnIndex | None:
        npz_path, meta_path = self._paths(cache_key=cache_key, provider_config=provider_config)
        if not npz_path.exists() or not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(meta, dict) or str(meta.get("schema") or "") != _INDEX_SCHEMA_V1:
            return None
        if str(meta.get("corpus_fingerprint") or "") != str(expected_fingerprint or ""):
            return None
        try:
            data = np.load(npz_path, allow_pickle=False)
            vecs = np.asarray(data["vectors"], dtype=np.float32)
            ids = [str(x) for x in data["doc_ids"].tolist()]
        except Exception:
            return None
        if vecs.ndim != 2 or not ids or len(ids) != int(vecs.shape[0]):
            return None
        return ColbertAnnIndex(
            doc_ids=ids,
            vectors=_l2_normalize(vecs),
            corpus_fingerprint=str(expected_fingerprint or ""),
            provider_config=dict(provider_config),
        )

    def save(
        self,
        *,
        cache_key: str,
        provider_config: dict[str, Any],
        corpus_fingerprint: str,
        doc_ids: list[str],
        vectors: np.ndarray,
    ) -> tuple[Path, Path]:
        npz_path, meta_path = self._paths(cache_key=cache_key, provider_config=provider_config)
        try:
            npz_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            return npz_path, meta_path

        vecs = _l2_normalize(np.asarray(vectors, dtype=np.float32))
        ids = [str(x) for x in (doc_ids or [])]

        try:
            np.savez_compressed(npz_path, vectors=vecs, doc_ids=np.asarray(ids, dtype=str))
        except Exception as exc:
            logger.debug("Ignoring ColBERT ANN vector index write failure: %s", exc)
        try:
            meta = {
                "schema": _INDEX_SCHEMA_V1,
                "provider_config": dict(provider_config),
                "corpus_fingerprint": str(corpus_fingerprint or ""),
                "doc_count": len(ids),
                "dim": int(vecs.shape[1]) if vecs.ndim == 2 else 0,
            }
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception as exc:
            logger.debug("Ignoring ColBERT ANN metadata write failure: %s", exc)

        return npz_path, meta_path


def topk_cosine_scores(*, query_vec: np.ndarray, doc_vecs: np.ndarray, k: int) -> list[tuple[int, float]]:
    kk = max(0, int(k or 0))
    if kk <= 0 or query_vec.ndim != 1 or doc_vecs.ndim != 2 or doc_vecs.shape[0] <= 0:
        return []
    q = query_vec.astype(np.float32, copy=False)
    qn = q / (np.linalg.norm(q) + 1e-12)
    sims = doc_vecs @ qn
    kk = min(kk, int(sims.shape[0]))
    idx = np.argpartition(-sims, kk - 1)[:kk]
    idx = idx[np.argsort(-sims[idx], kind="mergesort")]
    return [(int(i), float(sims[i])) for i in idx.tolist()]
