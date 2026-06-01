"""
Sparse retrieval utilities (SPLADE-style scaffolding).

This module supports:
- a deterministic sparse encoder for unit/regression tests (no model downloads)
- an optional SPLADE provider (HF/transformers) for production experiments (opt-in)
- a small persisted sparse index format for caching per-scope sparse vectors on disk

Design constraints:
- No default behavior changes (providers are used only when enabled via settings).
- Lazy-loading for optional model-backed providers.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import threading
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.rag.core.logging import get_logger

logger = get_logger(__name__)

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]+|\d+|[\u4e00-\u9fff]{2,}")
_INDEX_SCHEMA_V1 = "mimirq.sparse_index.v1"
VALID_SPARSE_PROVIDERS = frozenset({"deterministic", "splade"})
_SPARSE_PROVIDER_ALIASES = {
    "det": "deterministic",
    "deterministic": "deterministic",
    "splade": "splade",
}
_SPARSE_STATUS_VALUES = frozenset({"ready", "disabled", "fallback"})
_SPARSE_REASON_VALUES = frozenset(
    {
        "none",
        "sparse_disabled",
        "provider_invalid",
        "splade_model_missing",
    }
)


def normalize_sparse_provider_name(provider: str | None) -> str:
    raw = str(provider or "").strip().lower()
    if not raw:
        return "deterministic"
    return _SPARSE_PROVIDER_ALIASES.get(raw, raw)


def resolve_sparse_provider_capability(
    *,
    requested_provider: str | None,
    sparse_enabled: bool,
    splade_model_name: str | None,
    default_provider: str = "deterministic",
) -> dict[str, Any]:
    """
    Resolve sparse provider capability and deterministic fallback status.

    Contract goals:
    - Keep provider normalization deterministic and low-cardinality.
    - Expose explicit fallback reasons for audit/debug/metrics.
    - Never require callers to guess whether runtime fell back to deterministic.
    """
    requested_raw = str(requested_provider or "").strip().lower()
    requested_norm = normalize_sparse_provider_name(requested_raw)
    default_norm = normalize_sparse_provider_name(default_provider)
    if default_norm not in VALID_SPARSE_PROVIDERS:
        default_norm = "deterministic"

    provider_supported = requested_norm in VALID_SPARSE_PROVIDERS
    model_required = requested_norm == "splade"
    model_configured = bool(str(splade_model_name or "").strip())

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
    elif model_required and not model_configured:
        status = "fallback"
        reason = "splade_model_missing"

    return {
        "requested_provider": requested_raw or "",
        "requested_provider_normalized": requested_norm,
        "effective_provider": effective_provider,
        "provider_supported": bool(provider_supported),
        "model_required": bool(model_required),
        "model_configured": bool(model_configured),
        "status": status if status in _SPARSE_STATUS_VALUES else "fallback",
        "reason": reason if reason in _SPARSE_REASON_VALUES else "provider_invalid",
    }


def _norm_token(t: str) -> str:
    tok = str(t or "").strip()
    if not tok:
        return ""
    return tok.casefold() if tok.isascii() else tok


def tokenize(text: str) -> list[str]:
    raw = str(text or "")
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
    text = str(raw or "").strip()
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
        self._synonyms = synonyms or {}
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
        return [self.encode(str(t or "")) for t in (texts or [])]


def _coerce_sparse_vector(obj: Any) -> SparseVector:
    """
    Best-effort coercion helper so unit tests can stub encoders cheaply.

    Accepts:
    - SparseVector
    - dict[token -> weight]
    """
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
                continue
        return SparseVector(weights=weights)
    return SparseVector(weights={})


class SpladeSparseEncoder:
    """
    SPLADE sparse encoder (HF/transformers, opt-in).

    This uses an MLM head and max-pooling over sequence to generate a sparse vector over vocabulary.
    """

    def __init__(
        self,
        *,
        model_name: str,
        device: str = "cpu",
        batch_size: int = 8,
        max_length: int = 256,
        top_k: int = 128,
        min_weight: float = 0.0,
    ) -> None:
        self._model_name = str(model_name or "").strip()
        if not self._model_name:
            raise ValueError("SpladeSparseEncoder requires model_name")

        dev = str(device or "cpu").strip().lower() or "cpu"
        if dev not in {"cpu", "cuda", "auto"}:
            dev = "cpu"
        self._device = dev
        self._batch_size = max(1, int(batch_size or 0))
        self._max_length = max(16, int(max_length or 0))
        self._top_k = max(0, int(top_k or 0))
        self._min_w = float(min_weight or 0.0)

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

            import torch  # local import: optional dependency
            from transformers import AutoModelForMaskedLM, AutoTokenizer  # local import: optional dependency

            device = self._device
            if device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"

            tok = AutoTokenizer.from_pretrained(self._model_name)
            model = AutoModelForMaskedLM.from_pretrained(self._model_name)
            model.eval()
            model.to(device)

            self._tokenizer = tok
            self._model = model
            self._torch_device = device

    def encode_batch(self, texts: Sequence[str]) -> list[SparseVector]:
        raw = [str(t or "") for t in (texts or [])]
        if not raw:
            return []

        self._ensure_loaded()
        tok = self._tokenizer
        model = self._model
        device = self._torch_device
        if tok is None or model is None or device is None:
            return [SparseVector(weights={}) for _ in raw]

        import torch

        out: list[SparseVector] = []
        bs = self._batch_size

        # Best-effort list of special ids to zero out.
        special_ids: list[int] = []
        try:
            special_ids = list(getattr(tok, "all_special_ids", []) or [])
        except Exception:
            special_ids = []

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

            with torch.no_grad():
                logits = model(**enc).logits  # [B, L, V]
                attn = enc.get("attention_mask")
                if attn is not None:
                    mask = attn.unsqueeze(-1).expand_as(logits)
                    logits = logits.masked_fill(mask == 0, -1e9)

                # SPLADE-style activation: log(1+relu(logits)) then max-pool over L.
                weights = torch.log1p(torch.relu(logits))
                weights = torch.max(weights, dim=1).values  # [B, V]
                if special_ids:
                    try:
                        weights[:, special_ids] = 0.0
                    except Exception as exc:
                        logger.debug("Ignoring SPLADE special-token zeroing failure: %s", exc)

                top_k = self._top_k if self._top_k > 0 else int(weights.shape[1])
                top_k = min(int(weights.shape[1]), int(top_k))
                vals, idxs = torch.topk(weights, k=top_k, dim=1)

                vals = vals.detach().cpu()
                idxs = idxs.detach().cpu()

            for row_vals, row_idxs in zip(vals, idxs, strict=False):
                m: dict[str, float] = {}
                ids = [int(x) for x in row_idxs.tolist()]
                tokens = tok.convert_ids_to_tokens(ids)
                for token, val in zip(tokens, row_vals.tolist(), strict=False):
                    try:
                        score = float(val)
                    except Exception:
                        continue
                    if score <= self._min_w:
                        continue
                    t = str(token or "").strip()
                    if not t or (t.startswith("[") and t.endswith("]")):
                        continue
                    m[t] = score
                out.append(SparseVector(weights=m))

        # Preserve 1:1 shape with input texts.
        if len(out) != len(raw):
            out.extend([SparseVector(weights={}) for _ in range(len(raw) - len(out))])
        return out


_ENCODER_LOCK = threading.Lock()
_ENCODER_CACHE: dict[str, SparseEncoder] = {}


def get_sparse_encoder(
    *,
    provider: str,
    synonyms: dict[str, set[str]] | None = None,
    synonyms_raw: str = "",
    model_name: str = "",
    device: str = "cpu",
    batch_size: int = 8,
    max_length: int = 256,
    top_k: int = 128,
    min_weight: float = 0.0,
) -> SparseEncoder:
    """
    Sparse encoder factory with a small in-process cache.

    Notes:
    - Caching is keyed by provider + config so repeated indexing is faster.
    - SPLADE is opt-in and requires a model name/path.
    """
    p = normalize_sparse_provider_name(provider)
    if p not in VALID_SPARSE_PROVIDERS:
        p = "deterministic"

    if p == "deterministic":
        key = f"deterministic:{synonyms_raw}"
        with _ENCODER_LOCK:
            cached = _ENCODER_CACHE.get(key)
            if cached is not None:
                return cached
            inst = DeterministicSparseEncoder(synonyms=synonyms or parse_synonyms(synonyms_raw))
            _ENCODER_CACHE[key] = inst
            return inst

    key = f"splade:{model_name}:{device}:{batch_size}:{max_length}:{top_k}:{min_weight}"
    with _ENCODER_LOCK:
        cached = _ENCODER_CACHE.get(key)
        if cached is not None:
            return cached
        inst = SpladeSparseEncoder(
            model_name=model_name,
            device=device,
            batch_size=batch_size,
            max_length=max_length,
            top_k=top_k,
            min_weight=min_weight,
        )
        _ENCODER_CACHE[key] = inst
        return inst


def _stable_key(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="ignore")).hexdigest()


def build_sparse_provider_config(
    *,
    provider: str,
    synonyms_raw: str = "",
    model_name: str = "",
    device: str = "cpu",
    batch_size: int = 8,
    max_length: int = 256,
    top_k: int = 128,
    min_weight: float = 0.0,
) -> dict[str, Any]:
    p = normalize_sparse_provider_name(provider)
    if p not in VALID_SPARSE_PROVIDERS:
        p = "deterministic"
    if p == "deterministic":
        return {"provider": p, "synonyms_raw": str(synonyms_raw or "")}
    return {
        "provider": p,
        "model_name": str(model_name or ""),
        "device": str(device or "cpu"),
        "batch_size": int(batch_size or 0),
        "max_length": int(max_length or 0),
        "top_k": int(top_k or 0),
        "min_weight": float(min_weight or 0.0),
    }


class SparseIndexStore:
    def __init__(self, *, base_dir: str) -> None:
        self._base = Path(str(base_dir or "").strip() or "./data/sparse_indexes")

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
        if str(obj.get("schema") or "") != _INDEX_SCHEMA_V1:
            return None
        if str(obj.get("corpus_fingerprint") or "") != str(expected_fingerprint or ""):
            return None
        expected_token = str(expected_version_token or "").strip()
        stored_token = str(obj.get("version_token") or "").strip()
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
            "provider": str(provider_config.get("provider") or ""),
            "provider_config": dict(provider_config),
            "corpus_fingerprint": str(corpus_fingerprint or ""),
            "version_token": str(version_token or "").strip(),
            "doc_count": int(len(vectors or {})),
            "vectors": {k: (v.weights if isinstance(v, SparseVector) else _coerce_sparse_vector(v).weights) for k, v in (vectors or {}).items()},
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
    return float(total)


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
        scored.append((str(doc_id), float(s)))
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
