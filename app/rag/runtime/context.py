"""Prepare retrieved documents for generation: excerpt, deduplicate, order and bound tokens."""

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import TypeVar

from langchain_core.documents import Document

from app.infrastructure.config import settings
from app.infrastructure.tokens import num_tokens_from_string
from app.rag.ingestion.governance.markup.boilerplate import remove_markdown_boilerplate
from app.rag.ingestion.governance.text.normalization import normalize_text
from app.rag.retrieval.evidence.excerpts import extract_evidence_text


def compress_context_docs(
    docs: Iterable[Document] | None,
    query: str | None = None,
    *,
    max_sentences: int = 3,
    min_sentence_chars: int = 10,
) -> list[Document]:
    """Compress docs into query-relevant text snippets while preserving metadata."""
    if not docs:
        return []

    out: list[Document] = []
    q = str(query or "").strip()
    for doc in docs:
        raw = doc.page_content.strip()
        if not raw:
            continue

        content = raw
        if q:
            content = extract_evidence_text(
                raw,
                q,
                max_sentences=max(1, int(max_sentences or 0)),
                min_sentence_chars=max(0, int(min_sentence_chars or 0)),
            )
        content = content.strip()
        if not content:
            continue

        out.append(
            Document(
                page_content=content,
                metadata=dict(doc.metadata),
                id=doc.id,
            )
        )
    return out


_WS_RE = re.compile(r"[ \t]+")


_BLANK_LINES_RE = re.compile(r"\n{3,}")


_JACCARD_TOKEN_RE = re.compile(r"\w+", flags=re.UNICODE)


def _normalize_for_signature(text: str) -> str:
    norm = normalize_text(text, normalize_line_endings=True, remove_control_chars=True)
    # Keep newlines, but normalize whitespace so "exact duplicates" are caught.
    norm = _WS_RE.sub(" ", norm)
    norm = _BLANK_LINES_RE.sub("\n\n", norm)
    norm = "\n".join([ln.rstrip() for ln in norm.splitlines()])
    return norm.strip()


def _clean_chunk_text(text: str) -> str:
    # Normalize common exporter artifacts first, then remove boilerplate blocks/lines.
    norm = _normalize_for_signature(text)
    if not norm:
        return ""
    return remove_markdown_boilerplate(norm).text.strip()


def _tokenize_for_jaccard(text: str) -> set[str]:
    norm = _normalize_for_signature(text)
    # For ASCII, ignore 1-char tokens (noise). For non-ASCII, allow 1-char tokens
    # so CJK-heavy text can still be deduped reasonably.
    min_len = 2 if norm.isascii() else 1
    return {token.casefold() for token in _JACCARD_TOKEN_RE.findall(norm) if len(token) >= min_len}


def _jaccard(a: set[str], b: set[str]) -> float:
    inter = len(a & b)
    if not inter:
        return 0.0
    return float(inter) / float(len(a) + len(b) - inter)


def _apply_per_doc_cap(docs: list[Document], *, max_per_doc: int) -> list[Document]:
    if max_per_doc <= 0:
        return docs
    counts: dict[str, int] = defaultdict(int)
    out: list[Document] = []
    for d in docs:
        document_id = d.metadata.get("document_id")
        gid = str(document_id) if document_id is not None else ""
        if gid:
            counts[gid] += 1
            if counts[gid] > max_per_doc:
                continue
        out.append(d)
    # A diversity cap cannot improve a prompt whose matches all come from one source.
    return docs if len(counts) == 1 and sum(counts.values()) == len(docs) else out


def _apply_exact_dedup(docs: list[Document]) -> list[Document]:
    seen: set[str] = set()
    out: list[Document] = []
    for d in docs:
        sig = _normalize_for_signature(d.page_content)
        key = sig.casefold() if sig.isascii() else sig
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(d)
    return out


def _apply_jaccard_dedup(
    docs: list[Document],
    *,
    threshold: float,
    max_compare: int,
) -> list[Document]:
    thr = float(threshold or 0.0)
    if not docs or thr <= 0.0:
        return docs

    max_cmp = int(max_compare or 0)
    if max_cmp < 0:
        max_cmp = 0

    out: list[Document] = []
    compare_sets: list[set[str]] = []
    for d in docs:
        tokens = _tokenize_for_jaccard(d.page_content)
        if not tokens:
            out.append(d)
            compare_sets.append(tokens)
            continue

        if max_cmp > 0:
            candidates = compare_sets[-max_cmp:]
        else:
            candidates = compare_sets

        is_dup = any(_jaccard(tokens, prev) >= thr for prev in candidates if prev)
        if is_dup:
            continue

        out.append(d)
        compare_sets.append(tokens)

    return out


def _apply_token_budget_trim(docs: list[Document], *, max_total_tokens: int) -> list[Document]:
    cap = int(max_total_tokens or 0)
    if cap <= 0 or not docs:
        return docs

    out: list[Document] = []
    used = 0
    for doc in docs:
        content = doc.page_content.strip()
        if not content:
            continue
        n = num_tokens_from_string(content)
        if out and (used + n) > cap:
            break
        out.append(doc)
        used += max(0, n)
    return out


def denoise_context_docs(docs: Iterable[Document] | None) -> list[Document]:
    """
    Clean and deduplicate retrieved context docs before prompt assembly.

    Applies:
    - boilerplate removal (conservative)
    - exact-duplicate dropping
    - near-duplicate dropping (jaccard)
    - per-document cap (stable)
    """
    if not docs:
        return []

    # 1) Clean page_content conservatively; keep metadata/id stable.
    cleaned: list[Document] = []
    for d in docs:
        if d is None:
            continue
        text = _clean_chunk_text(d.page_content)
        if not text:
            continue
        cleaned.append(Document(page_content=text, metadata=dict(d.metadata), id=d.id))

    if not cleaned:
        return []

    # 2) Drop duplicates before applying caps so we don't "waste" per-doc budget on repeats.
    cleaned = _apply_exact_dedup(cleaned)

    dedup_enabled = settings.RETRIEVAL_DEDUP_ENABLED
    if dedup_enabled:
        cleaned = _apply_jaccard_dedup(
            cleaned,
            threshold=settings.RETRIEVAL_DEDUP_JACCARD_THRESHOLD,
            max_compare=settings.RETRIEVAL_DEDUP_MAX_COMPARE,
        )

    # 3) Per-doc cap (reuse retrieval knob; prompt context needs the same diversity guard after injections).
    max_per_doc = settings.RETRIEVAL_MAX_CHUNKS_PER_DOC
    cleaned = _apply_per_doc_cap(cleaned, max_per_doc=max_per_doc)

    # 4) Optional lost-in-middle mitigation via deterministic interleaving.
    if settings.RAG_CONTEXT_LOST_IN_MIDDLE_REORDER_ENABLED:
        cleaned = reorder_docs_for_generation(cleaned)

    # 5) Optional token-budget-aware trim for pre-prompt context packing.
    if settings.RAG_CONTEXT_TOKEN_BUDGET_TRIM_ENABLED:
        cleaned = _apply_token_budget_trim(
            cleaned,
            max_total_tokens=settings.RAG_CONTEXT_DENOISE_MAX_TOTAL_TOKENS,
        )

    return cleaned


T = TypeVar("T")


def reorder_docs_for_generation(items: Sequence[T]) -> list[T]:
    """Interleave the ranked list so highly relevant items avoid clustering only at the front."""
    ordered = list(items)
    if len(ordered) < 3:
        return ordered
    front = ordered[::2]
    back = list(reversed(ordered[1::2]))
    return front + back


__all__ = ["compress_context_docs", "denoise_context_docs", "reorder_docs_for_generation"]
