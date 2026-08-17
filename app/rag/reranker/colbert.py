"""
ColBERT-style late-interaction reranker (scaffold).

This implementation is intentionally lightweight:
- deterministic by default
- no external model downloads
- usable as an *optional* reranker provider for retrieval-first workloads

It provides the plumbing/integration point. A production-grade ColBERT model
can be wired in by implementing a TokenEmbedder that uses HF/torch.
"""

import hashlib
import re
import threading
import time
from collections.abc import Sequence
from typing import Any, Protocol

import numpy as np

from app.rag.reranker.base import BaseReranker
from app.rag.reranker.types import RerankCandidate, RerankResult

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]+|[\u4e00-\u9fff]{2,}")


def _tokenize(text: str) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    toks: list[str] = []
    for m in _TOKEN_RE.finditer(raw):
        t = (m.group(0) or "").strip()
        if not t:
            continue
        toks.append(t.casefold() if t.isascii() else t)
    return toks


class TokenEmbedder(Protocol):
    def encode(self, tokens: list[str]) -> np.ndarray:
        """Return float32 embeddings shaped [len(tokens), dim]."""


class _DeterministicHashEmbedder(TokenEmbedder):
    def __init__(self, *, dim: int = 16) -> None:
        self._dim = max(2, int(dim or 0))

    def _vec_for_token(self, token: str) -> np.ndarray:
        # Stable per-token pseudo-random vector based on sha256.
        h = hashlib.sha256(token.encode("utf-8", errors="ignore")).digest()
        # Expand digest to dim bytes by repetition.
        b = (h * ((self._dim // len(h)) + 1))[: self._dim]
        arr = (np.frombuffer(b, dtype=np.uint8).astype(np.float32) - 127.5) / 127.5
        return arr

    def encode(self, tokens: list[str]) -> np.ndarray:
        if not tokens:
            return np.zeros((0, self._dim), dtype=np.float32)
        rows = [self._vec_for_token(t) for t in tokens]
        return np.stack(rows, axis=0).astype(np.float32, copy=False)


class _HFTokenEmbedder(TokenEmbedder):
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
            raise ValueError("HF ColBERT reranker requires model_name")

        dev = str(device or "cpu").strip().lower() or "cpu"
        if dev not in {"cpu", "cuda", "auto"}:
            raise ValueError("HF ColBERT reranker device must be one of: cpu, cuda, auto")

        self._device = dev
        bs = int(batch_size or 0)
        if bs < 1 or bs > 256:
            raise ValueError("HF ColBERT reranker batch_size must be within [1, 256]")
        self._batch_size = bs

        ml = int(max_length or 0)
        if ml < 8 or ml > 2048:
            raise ValueError("HF ColBERT reranker max_length must be within [8, 2048]")
        self._max_length = ml
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

            tokenizer = AutoTokenizer.from_pretrained(self._model_name)
            model = AutoModel.from_pretrained(self._model_name)
            model.eval()
            model.to(device)

            self._tokenizer = tokenizer
            self._model = model
            self._torch_device = device

    def encode(self, tokens: list[str]) -> np.ndarray:
        raw = [str(t or "") for t in (tokens or []) if str(t or "").strip()]
        if not raw:
            return np.zeros((0, 1), dtype=np.float32)

        self._ensure_loaded()
        tokenizer = self._tokenizer
        model = self._model
        device = self._torch_device
        if tokenizer is None or model is None or device is None:
            return np.zeros((len(raw), 1), dtype=np.float32)

        import torch

        rows: list[np.ndarray] = []
        for i in range(0, len(raw), self._batch_size):
            batch_tokens = raw[i : i + self._batch_size]
            enc = tokenizer(
                batch_tokens,
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
                    pooled = torch.zeros((len(batch_tokens), 1), dtype=torch.float32, device=device)
                elif attn is None:
                    pooled = torch.mean(last, dim=1)
                else:
                    mask = attn.unsqueeze(-1).to(last.dtype)
                    denom = torch.clamp(mask.sum(dim=1), min=1.0)
                    pooled = (last * mask).sum(dim=1) / denom
            rows.append(pooled.detach().cpu().numpy().astype(np.float32, copy=False))

        return np.concatenate(rows, axis=0) if rows else np.zeros((len(raw), 1), dtype=np.float32)


_EMBEDDER_LOCK = threading.Lock()
_EMBEDDER_CACHE: dict[str, TokenEmbedder] = {}


def get_token_embedder(
    *,
    provider_name: str,
    model_name: str = "",
    device: str = "cpu",
    batch_size: int = 16,
    max_length: int = 256,
    deterministic_dim: int = 16,
) -> TokenEmbedder:
    provider = str(provider_name or "").strip().lower() or "deterministic"
    if provider not in {"deterministic", "hf"}:
        provider = "deterministic"

    if provider == "deterministic":
        key = f"deterministic:{int(deterministic_dim or 0)}"
        with _EMBEDDER_LOCK:
            cached = _EMBEDDER_CACHE.get(key)
            if cached is not None:
                return cached
            inst = _DeterministicHashEmbedder(dim=deterministic_dim)
            _EMBEDDER_CACHE[key] = inst
            return inst

    key = f"hf:{model_name}:{device}:{batch_size}:{max_length}"
    with _EMBEDDER_LOCK:
        cached = _EMBEDDER_CACHE.get(key)
        if cached is not None:
            return cached
        inst = _HFTokenEmbedder(
            model_name=model_name,
            device=device,
            batch_size=batch_size,
            max_length=max_length,
        )
        _EMBEDDER_CACHE[key] = inst
        return inst


def check_colbert_provider_readiness(
    *,
    provider_name: str,
    model_name: str = "",
    device: str = "cpu",
) -> dict[str, Any]:
    provider = str(provider_name or "").strip().lower() or "deterministic"
    if provider not in {"deterministic", "hf"}:
        provider = "deterministic"
    if provider == "deterministic":
        return {
            "provider": provider,
            "ready": True,
            "reason": "none",
            "dependency_ok": True,
            "model_name": "",
            "device": "cpu",
        }

    resolved_model = str(model_name or "").strip()
    resolved_device = str(device or "cpu").strip().lower() or "cpu"
    if not resolved_model:
        return {
            "provider": provider,
            "ready": False,
            "reason": "model_name_missing",
            "dependency_ok": False,
            "model_name": resolved_model,
            "device": resolved_device,
        }
    if resolved_device not in {"cpu", "cuda", "auto"}:
        return {
            "provider": provider,
            "ready": False,
            "reason": "invalid_device",
            "dependency_ok": False,
            "model_name": resolved_model,
            "device": resolved_device,
        }

    try:
        import torch  # noqa: PLC0415
        import transformers as transformers  # noqa: PLC0415
    except Exception:
        return {
            "provider": provider,
            "ready": False,
            "reason": "dependency_missing",
            "dependency_ok": False,
            "model_name": resolved_model,
            "device": resolved_device,
        }
    if resolved_device == "cuda" and not bool(torch.cuda.is_available()):
        return {
            "provider": provider,
            "ready": False,
            "reason": "cuda_unavailable",
            "dependency_ok": True,
            "model_name": resolved_model,
            "device": resolved_device,
        }

    return {
        "provider": provider,
        "ready": True,
        "reason": "none",
        "dependency_ok": True,
        "model_name": resolved_model,
        "device": resolved_device,
    }


def warmup_colbert_embedder(
    *,
    provider_name: str,
    model_name: str = "",
    device: str = "cpu",
    batch_size: int = 16,
    max_length: int = 256,
    deterministic_dim: int = 16,
) -> dict[str, Any]:
    provider = str(provider_name or "").strip().lower() or "deterministic"
    if provider not in {"deterministic", "hf"}:
        provider = "deterministic"
    if provider != "hf":
        return {"ok": True, "reason": "skipped_non_hf", "provider": provider}

    try:
        embedder = get_token_embedder(
            provider_name=provider,
            model_name=model_name,
            device=device,
            batch_size=batch_size,
            max_length=max_length,
            deterministic_dim=deterministic_dim,
        )
        out = embedder.encode(["warmup_probe"])
        rows = int(out.shape[0]) if isinstance(out, np.ndarray) and out.ndim == 2 else 0
        cols = int(out.shape[1]) if isinstance(out, np.ndarray) and out.ndim == 2 else 0
        if rows <= 0 or cols <= 0:
            return {
                "ok": False,
                "reason": "empty_embedding",
                "provider": provider,
                "rows": rows,
                "dim": cols,
            }
        return {
            "ok": True,
            "reason": "none",
            "provider": provider,
            "rows": rows,
            "dim": cols,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "reason": "warmup_exception",
            "provider": provider,
            "error": f"{exc.__class__.__name__}:{str(exc)[:160]}",
        }


def _l2_normalize(x: np.ndarray) -> np.ndarray:
    if x.size == 0:
        return x
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    norms = np.where(norms > 0.0, norms, 1.0)
    return x / norms


def late_interaction_score(*, query_emb: np.ndarray, doc_emb: np.ndarray) -> float:
    """
    ColBERT-style score: sum over query tokens of the max similarity to any doc token.

    We use cosine similarity via L2 normalization.
    """
    if query_emb.size == 0 or doc_emb.size == 0:
        return 0.0
    q = _l2_normalize(query_emb.astype(np.float32, copy=False))
    d = _l2_normalize(doc_emb.astype(np.float32, copy=False))
    # [Q, D] x [T, D]^T -> [Q, T]
    sim = q @ d.T
    max_per_q = np.max(sim, axis=1) if sim.size else np.zeros((q.shape[0],), dtype=np.float32)
    # Normalize by query length for stability across different query sizes.
    denom = float(max(1, int(q.shape[0])))
    return float(np.sum(max_per_q) / denom)


class ColBERTReranker(BaseReranker):
    """
    Late-interaction reranker.

    Provider id: "colbert" (see app.rag.reranker.factory.get_reranker)
    """

    def __init__(
        self,
        *,
        provider_name: str = "deterministic",
        model_name: str = "",
        device: str = "cpu",
        batch_size: int = 16,
        max_length: int = 256,
        deterministic_dim: int = 16,
        embedder: TokenEmbedder | None = None,
        provider_health: dict[str, Any] | None = None,
        warmup_status: dict[str, Any] | None = None,
    ) -> None:
        provider = str(provider_name or "").strip().lower() or "deterministic"
        if provider not in {"deterministic", "hf"}:
            provider = "deterministic"

        self.provider_name = provider
        self.model_name = str(model_name or "").strip()
        self.device = str(device or "cpu").strip() or "cpu"
        self.batch_size = max(1, int(batch_size or 0))
        self.max_length = max(8, int(max_length or 0))
        self.deterministic_dim = max(2, int(deterministic_dim or 0))
        self.provider_health = dict(provider_health or {})
        self.warmup_status = dict(warmup_status or {})
        self._embedder = embedder or get_token_embedder(
            provider_name=self.provider_name,
            model_name=self.model_name,
            device=self.device,
            batch_size=self.batch_size,
            max_length=self.max_length,
            deterministic_dim=self.deterministic_dim,
        )

    def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        **kwargs,
    ) -> RerankResult:
        start = time.time()
        top_n_raw = kwargs.get("top_n")
        try:
            top_n = int(top_n_raw) if top_n_raw is not None else None
        except Exception:
            top_n = None
        if top_n is not None:
            top_n = max(0, top_n)

        if not candidates:
            return RerankResult(
                ordered_ids=[],
                score_map={},
                provider="colbert",
                model_used=self.model_name or "deterministic_hash",
                stats={
                    "embedder_provider": self.provider_name,
                    "late_interaction": True,
                    "batch_size": int(self.batch_size),
                    "max_length": int(self.max_length),
                },
                elapsed_sec=0.0,
            )

        q_tokens = _tokenize(query)
        q_emb = self._embedder.encode(q_tokens)

        scores: list[tuple[str, float]] = []
        for c in candidates:
            cid = str(c.id or "").strip()
            if not cid:
                continue
            d_tokens = _tokenize(c.text or "")
            d_emb = self._embedder.encode(d_tokens)
            s = late_interaction_score(query_emb=q_emb, doc_emb=d_emb)
            scores.append((cid, float(s)))

        scores.sort(key=lambda x: (-x[1], x[0]))
        ordered_ids = [cid for cid, _s in scores]
        score_map = {cid: float(s) for cid, s in scores}
        if top_n:
            ordered_ids = ordered_ids[: int(top_n)]
            score_map = {cid: score_map[cid] for cid in ordered_ids if cid in score_map}
        return RerankResult(
            ordered_ids=ordered_ids,
            score_map=score_map,
            provider="colbert",
            model_used=self.model_name or "deterministic_hash",
            stats={
                "embedder_provider": self.provider_name,
                "late_interaction": True,
                "query_tokens": len(q_tokens),
                "docs": len(score_map),
                "batch_size": int(self.batch_size),
                "max_length": int(self.max_length),
            },
            elapsed_sec=float(time.time() - start),
        )
