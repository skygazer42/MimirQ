"""
ColBERT-style ANN retrieval (production scaffold).

This module provides an *optional* retrieval channel that:
- builds a per-scope dense embedding index (persisted to disk, best-effort)
- retrieves top candidates using cosine similarity (optionally FAISS when available)
- is deterministic in unit tests via a hash-based embedder

Important:
- This is NOT a full ColBERT token-level index. It is an engineering scaffold that
  enables "ColBERT stack" experiments (candidate generation -> late-interaction rerank)
  without changing defaults.
"""

import contextlib
import hashlib
import io
import json
import re
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from app.rag.core.logging import get_logger

logger = get_logger(__name__)

_INDEX_SCHEMA_V1 = "mimirq.colbert_ann_index.v1"
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]+|[\u4e00-\u9fff]{2,}")
VALID_COLBERT_PROVIDERS = frozenset({"deterministic", "hf"})


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
        t = str(m.group(0) or "").strip()
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


class HFDenseEmbedder(DenseEmbedder):
    def __init__(
        self,
        *,
        model_name: str,
        device: str = "cpu",
        batch_size: int = 16,
        max_length: int = 256,
    ) -> None:
        self._model_name = str(model_name or "").strip()
        if not self._model_name:
            raise ValueError("HFDenseEmbedder requires model_name")

        dev = str(device or "cpu").strip().lower() or "cpu"
        if dev not in {"cpu", "cuda", "auto"}:
            dev = "cpu"
        self._device = dev
        self._batch_size = max(1, int(batch_size or 0))
        self._max_length = max(16, int(max_length or 0))

        self._lock = threading.Lock()
        self._tokenizer = None
        self._model = None
        self._torch_device = None

    def _ensure_loaded(self) -> None:
        if self._tokenizer is not None and self._model is not None:
            return
        with self._lock:
            if self._tokenizer is not None and self._model is not None:
                return

            import torch
            from transformers import AutoModel, AutoTokenizer

            device = self._device
            if device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"

            tok = AutoTokenizer.from_pretrained(self._model_name)
            model = AutoModel.from_pretrained(self._model_name)
            model.eval()
            model.to(device)

            self._tokenizer = tok
            self._model = model
            self._torch_device = device

    def encode_batch(self, texts: Sequence[str]) -> np.ndarray:
        raw = [str(t or "") for t in (texts or [])]
        if not raw:
            return np.zeros((0, 1), dtype=np.float32)

        self._ensure_loaded()
        tok = self._tokenizer
        model = self._model
        device = self._torch_device
        if tok is None or model is None or device is None:
            return np.zeros((len(raw), 1), dtype=np.float32)

        import torch

        vecs: list[np.ndarray] = []
        bs = self._batch_size
        for i in range(0, len(raw), bs):
            batch_texts = raw[i : i + bs]
            enc = tok(
                batch_texts,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=self._max_length,
            )
            enc = {k: v.to(device) for k, v in enc.items() if hasattr(v, "to")}
            attn = enc.get("attention_mask")
            with torch.no_grad():
                out = model(**enc)
                last = getattr(out, "last_hidden_state", None)
                if last is None:
                    vec = torch.zeros((len(batch_texts), 1), dtype=torch.float32, device=device)
                else:
                    if attn is None:
                        vec = torch.mean(last, dim=1)
                    else:
                        mask = attn.unsqueeze(-1).to(last.dtype)
                        denom = torch.clamp(mask.sum(dim=1), min=1.0)
                        vec = (last * mask).sum(dim=1) / denom
            vecs.append(vec.detach().cpu().numpy().astype(np.float32, copy=False))

        mat = np.concatenate(vecs, axis=0) if vecs else np.zeros((len(raw), 1), dtype=np.float32)
        return _l2_normalize(mat)


_EMBEDDER_LOCK = threading.Lock()
_EMBEDDER_CACHE: dict[str, DenseEmbedder] = {}
_FAISS_LOCK = threading.Lock()
_FAISS_MODULE: Any | None = None
_FAISS_IMPORT_ATTEMPTED = False


def get_dense_embedder(
    *,
    provider: str,
    model_name: str = "",
    device: str = "cpu",
    batch_size: int = 16,
    max_length: int = 256,
    deterministic_dim: int = 64,
) -> DenseEmbedder:
    p = str(provider or "").strip().lower() or "deterministic"
    if p not in {"deterministic", "hf"}:
        p = "deterministic"

    if p == "deterministic":
        key = f"deterministic:{int(deterministic_dim or 0)}"
        with _EMBEDDER_LOCK:
            cached = _EMBEDDER_CACHE.get(key)
            if cached is not None:
                return cached
            inst = DeterministicDenseEmbedder(dim=int(deterministic_dim or 0))
            _EMBEDDER_CACHE[key] = inst
            return inst

    key = f"hf:{model_name}:{device}:{batch_size}:{max_length}"
    with _EMBEDDER_LOCK:
        cached = _EMBEDDER_CACHE.get(key)
        if cached is not None:
            return cached
        inst = HFDenseEmbedder(
            model_name=model_name,
            device=device,
            batch_size=batch_size,
            max_length=max_length,
        )
        _EMBEDDER_CACHE[key] = inst
        return inst


def build_colbert_provider_config(
    *,
    provider: str,
    model_name: str = "",
    device: str = "cpu",
    batch_size: int = 16,
    max_length: int = 256,
    deterministic_dim: int = 64,
) -> dict[str, Any]:
    p = str(provider or "").strip().lower() or "deterministic"
    if p == "deterministic":
        return {"provider": p, "deterministic_dim": int(deterministic_dim or 0)}
    return {
        "provider": p,
        "model_name": str(model_name or ""),
        "device": str(device or "cpu"),
        "batch_size": int(batch_size or 0),
        "max_length": int(max_length or 0),
    }


def resolve_colbert_ann_provider_capability(
    *,
    colbert_enabled: bool,
    requested_provider: str | None,
    model_name: str | None,
    device: str | None,
    docs_count: int,
    max_docs: int,
) -> dict[str, Any]:
    """
    Resolve ColBERT ANN provider readiness and bounded fallback metadata.

    Contract:
    - deterministic provider is always ready
    - invalid/unsupported providers fall back to deterministic
    - HF provider requires model_name + optional dependency checks
    - oversized corpus is gated before index build to keep memory bounded
    """
    requested_raw = str(requested_provider or "").strip().lower()
    requested_norm = requested_raw or "deterministic"
    provider_supported = requested_norm in VALID_COLBERT_PROVIDERS
    effective_provider = requested_norm if provider_supported else "deterministic"
    status = "ready"
    reason = "none"
    ready = True

    resolved_model_name = str(model_name or "").strip()
    resolved_device = str(device or "cpu").strip().lower() or "cpu"

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
    elif effective_provider == "hf":
        if not resolved_model_name:
            status = "fallback"
            reason = "hf_model_missing"
            effective_provider = "deterministic"
            ready = True
        elif resolved_device not in {"cpu", "cuda", "auto"}:
            status = "fallback"
            reason = "invalid_device"
            effective_provider = "deterministic"
            ready = True
        else:
            try:
                import torch  # noqa: PLC0415
                import transformers as transformers  # noqa: PLC0415
            except Exception:
                status = "fallback"
                reason = "dependency_missing"
                effective_provider = "deterministic"
                ready = True
            else:
                if resolved_device == "cuda" and not bool(torch.cuda.is_available()):
                    status = "fallback"
                    reason = "cuda_unavailable"
                    effective_provider = "deterministic"
                    ready = True

    return {
        "requested_provider": requested_raw,
        "requested_provider_normalized": requested_norm,
        "effective_provider": effective_provider,
        "provider_supported": bool(provider_supported),
        "status": status,
        "reason": reason,
        "ready": bool(ready),
        "model_name_configured": bool(resolved_model_name),
        "device": resolved_device,
        "docs_count": int(max(0, int(docs_count or 0))),
        "max_docs": int(max(0, int(max_docs or 0))),
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
                "doc_count": int(len(ids)),
                "dim": int(vecs.shape[1]) if vecs.ndim == 2 else 0,
            }
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception as exc:
            logger.debug("Ignoring ColBERT ANN metadata write failure: %s", exc)

        return npz_path, meta_path


def topk_cosine_scores(*, query_vec: np.ndarray, doc_vecs: np.ndarray, k: int) -> list[tuple[int, float]]:
    kk = max(0, int(k or 0))
    if kk <= 0:
        return []
    if query_vec.ndim != 1 or doc_vecs.ndim != 2:
        return []
    if doc_vecs.shape[0] <= 0:
        return []
    q = query_vec.astype(np.float32, copy=False)
    # doc_vecs is already L2-normalized; keep q normalized too.
    qn = q / (np.linalg.norm(q) + 1e-12)

    faiss = None
    global _FAISS_IMPORT_ATTEMPTED, _FAISS_MODULE
    if not _FAISS_IMPORT_ATTEMPTED:
        with _FAISS_LOCK:
            if not _FAISS_IMPORT_ATTEMPTED:
                try:
                    with contextlib.redirect_stderr(io.StringIO()):
                        import faiss as faiss_mod  # type: ignore

                    _FAISS_MODULE = faiss_mod
                except Exception:
                    _FAISS_MODULE = None
                finally:
                    _FAISS_IMPORT_ATTEMPTED = True
    faiss = _FAISS_MODULE

    try:
        if faiss is None:
            raise RuntimeError("faiss unavailable")
        # Build a temporary index (in-memory); persisted format stores vectors only.
        index = faiss.IndexFlatIP(int(doc_vecs.shape[1]))
        index.add(doc_vecs.astype(np.float32, copy=False))
        scores, idxs = index.search(qn.reshape(1, -1), kk)
        pairs = [(int(i), float(s)) for i, s in zip(idxs[0].tolist(), scores[0].tolist(), strict=False) if i >= 0]
        pairs.sort(key=lambda x: (-x[1], x[0]))
        return pairs
    except Exception:
        sims = doc_vecs @ qn
        kk = min(kk, int(sims.shape[0]))
        idx = np.argpartition(-sims, kk - 1)[:kk]
        idx = idx[np.argsort(-sims[idx], kind="mergesort")]
        return [(int(i), float(sims[i])) for i in idx.tolist()]
