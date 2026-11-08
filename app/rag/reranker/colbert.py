"""
ColBERT-style late-interaction reranker (scaffold).

This implementation is intentionally lightweight:
- deterministic by default
- no external model downloads
- usable as an *optional* reranker provider for retrieval-first workloads

This retained implementation is for deterministic offline validation.
Neural ColBERT model loading has been retired from the API.
"""

import hashlib
import re
import threading
import time
from collections.abc import Sequence
from typing import Any, Protocol

import numpy as np

from app.core.model_execution import reject_retired_provider
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


_EMBEDDER_LOCK = threading.Lock()
_EMBEDDER_CACHE: dict[str, TokenEmbedder] = {}


def get_token_embedder(*, provider_name: str, deterministic_dim: int = 16) -> TokenEmbedder:
    reject_retired_provider(provider_name, capability="colbert")
    provider = str(provider_name or "").strip().lower() or "deterministic"
    if provider != "deterministic":
        raise ValueError(f"Unsupported ColBERT provider: {provider_name}")
    key = f"deterministic:{int(deterministic_dim or 0)}"
    with _EMBEDDER_LOCK:
        cached = _EMBEDDER_CACHE.get(key)
        if cached is not None:
            return cached
        inst = _DeterministicHashEmbedder(dim=deterministic_dim)
        _EMBEDDER_CACHE[key] = inst
        return inst


def check_colbert_provider_readiness(*, provider_name: str) -> dict[str, Any]:
    reject_retired_provider(provider_name, capability="colbert")
    provider = str(provider_name or "").strip().lower() or "deterministic"
    if provider != "deterministic":
        raise ValueError(f"Unsupported ColBERT provider: {provider_name}")
    return {"provider": provider, "ready": True, "reason": "none", "dependency_ok": True}


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
        deterministic_dim: int = 16,
        embedder: TokenEmbedder | None = None,
    ) -> None:
        provider = str(provider_name or "").strip().lower() or "deterministic"
        reject_retired_provider(provider, capability="colbert")
        if provider != "deterministic":
            raise ValueError(f"Unsupported ColBERT provider: {provider_name}")

        self.provider_name = provider
        self.deterministic_dim = max(2, int(deterministic_dim or 0))
        self._embedder = (
            embedder
            if embedder is not None
            else get_token_embedder(provider_name=self.provider_name, deterministic_dim=self.deterministic_dim)
        )

    def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        **kwargs: Any,
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
                model_used="deterministic_hash",
                stats={
                    "embedder_provider": self.provider_name,
                    "late_interaction": True,
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
            scores.append((cid, s))

        scores.sort(key=lambda x: (-x[1], x[0]))
        ordered_ids = [cid for cid, _s in scores]
        score_map = {cid: s for cid, s in scores}
        if top_n:
            ordered_ids = ordered_ids[:top_n]
            score_map = {cid: score_map[cid] for cid in ordered_ids if cid in score_map}
        return RerankResult(
            ordered_ids=ordered_ids,
            score_map=score_map,
            provider="colbert",
            model_used="deterministic_hash",
            stats={
                "embedder_provider": self.provider_name,
                "late_interaction": True,
                "query_tokens": len(q_tokens),
                "docs": len(score_map),
            },
            elapsed_sec=float(time.time() - start),
        )
