"""
Sparse retrieval utilities (SPLADE-style scaffolding).

This module intentionally supports a *deterministic* sparse encoder that:
- requires no model downloads
- is suitable for unit/regression tests

Production SPLADE models (HF/transformers) can be added as an optional provider
later, but must be lazy-loaded and strictly opt-in.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{1,}|\d+|[\u4e00-\u9fff]{2,}")


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

