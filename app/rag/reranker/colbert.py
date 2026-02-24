"""
ColBERT-style late-interaction reranker (scaffold).

This implementation is intentionally lightweight:
- deterministic by default
- no external model downloads
- usable as an *optional* reranker provider for retrieval-first workloads

It provides the plumbing/integration point. A production-grade ColBERT model
can be wired in by implementing a TokenEmbedder that uses HF/torch.
"""

from __future__ import annotations

import hashlib
import re
from typing import Protocol, Sequence

import numpy as np

from app.rag.reranker.base import BaseReranker
from app.rag.reranker.types import RerankCandidate, RerankResult

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{1,}|[\u4e00-\u9fff]{2,}")


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

    def __init__(self, *, embedder: TokenEmbedder | None = None) -> None:
        self._embedder = embedder or _DeterministicHashEmbedder(dim=16)

    def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        **_kwargs,
    ) -> RerankResult:
        if not candidates:
            return RerankResult(ordered_ids=[], score_map={}, provider="colbert")

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
        return RerankResult(
            ordered_ids=ordered_ids,
            score_map=score_map,
            provider="colbert",
            model_used="deterministic_hash",
        )

