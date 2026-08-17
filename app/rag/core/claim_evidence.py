"""
Deterministic claim → evidence mapping (no LLM dependency).

Goal:
- Given an assistant answer, split it into atomic claims.
- For each claim, find the best supporting retrieved chunks (if any).
- Produce span-level pointers (best-effort) so UIs can deep-link/highlight evidence.

Design constraints:
- Deterministic and bounded (safe for production, no extra network calls).
- Best-effort: do not fail the request if evidence mapping is imperfect.
"""

import re
from collections.abc import Iterable
from typing import Any

from app.rag.core.text import is_claim_supported, split_into_claims

_WS_RE = re.compile(r"\s+")
_CLAIM_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]+|[\u4e00-\u9fff]{2,}|\d+(?:\.\d+)?")
_UNCERTAINTY_RE = re.compile(
    r"(unable to answer|cannot determine|can't determine|"
    r"insufficient evidence|not enough (?:info|information)|unknown|unsure|not sure|"
    r"证据不足|材料不足|无法(确定|判断|回答)|不确定|未知)",
    flags=re.IGNORECASE,
)
_EN_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
_SENTENCE_BOUNDARIES = {"。", "！", "？", ".", "!", "?", "\n"}


def _collapse_ws(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").strip())


def _token_set(text: str) -> set[str]:
    tokens: set[str] = set()
    for m in _CLAIM_TOKEN_RE.finditer(text or ""):
        t = (m.group(0) or "").strip()
        if not t:
            continue
        if t.isascii():
            folded = t.casefold()
            if folded in _EN_STOPWORDS:
                continue
            tokens.add(folded)
        else:
            tokens.add(t)
    return tokens


def _find_prev_boundary(text: str, *, start: int, end: int) -> int:
    best = -1
    for ch in _SENTENCE_BOUNDARIES:
        pos = text.rfind(ch, start, end)
        if pos > best:
            best = pos
    return best


def _find_next_boundary(text: str, *, start: int, end: int) -> int | None:
    best: int | None = None
    for ch in _SENTENCE_BOUNDARIES:
        pos = text.find(ch, start, end)
        if pos < 0:
            continue
        if best is None or pos < best:
            best = pos
    return best


def _first_term_index(text: str, terms: list[str]) -> int | None:
    folded = text.casefold()
    best_index: int | None = None
    for term in terms:
        if not term:
            continue
        term_text = str(term)
        index = folded.find(term_text.casefold()) if term_text.isascii() else text.find(term_text)
        if index >= 0 and (best_index is None or index < best_index):
            best_index = index
    return best_index


def _sentence_span_bounds(text: str, *, match_index: int, max_chars: int) -> tuple[int, int, int, int]:
    before = max_chars // 3
    after = max_chars - before
    base_start = max(0, match_index - before)
    base_end = min(len(text), match_index + after)

    previous = _find_prev_boundary(text, start=base_start, end=match_index)
    start = min(max(base_start, previous + 1), len(text)) if previous >= 0 else base_start
    following = _find_next_boundary(text, start=match_index, end=base_end)
    end = min(max(start, following + 1), len(text)) if following is not None else base_end
    return start, end, base_start, base_end


def _display_span_quote(text: str, *, start: int, end: int, base_start: int, base_end: int) -> str:
    quote = _collapse_ws(text[start:end]).strip() or _collapse_ws(text[base_start:base_end])
    if start > 0:
        quote = "..." + quote
    if end < len(text):
        quote += "..."
    return quote


def _extract_span(text: str, terms: list[str], *, max_chars: int) -> tuple[int, int, str] | None:
    """
    Return (start, end, quote) span in `text` that best matches `terms`.
    """
    max_chars = max(80, int(max_chars or 0))
    raw = str(text or "")
    if not raw.strip() or not terms:
        return None

    best_idx = _first_term_index(raw, terms)
    if best_idx is None:
        return None
    start, end, base_start, base_end = _sentence_span_bounds(
        raw,
        match_index=best_idx,
        max_chars=max_chars,
    )
    quote = _display_span_quote(
        raw,
        start=start,
        end=end,
        base_start=base_start,
        base_end=base_end,
    )
    return int(start), int(end), quote


def _iter_chunks(evidence_chunks: Iterable[Any]) -> Iterable[dict[str, Any]]:
    for obj in evidence_chunks or []:
        if obj is None:
            continue

        if isinstance(obj, dict):
            meta = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
            text = obj.get("text")
            if text is None:
                text = obj.get("page_content")
            if text is None:
                text = obj.get("content")
            doc_id = obj.get("document_id") or meta.get("document_id")
            chunk_id = obj.get("chunk_id") or meta.get("chunk_id") or obj.get("id")
            start_char = obj.get("start_char") if obj.get("start_char") is not None else meta.get("start_char")
            end_char = obj.get("end_char") if obj.get("end_char") is not None else meta.get("end_char")
            page_number = (
                obj.get("page_number")
                if obj.get("page_number") is not None
                else meta.get("page_number") or meta.get("page")
            )
        else:
            meta = getattr(obj, "metadata", None)
            meta = meta if isinstance(meta, dict) else {}
            text = getattr(obj, "page_content", None)
            doc_id = meta.get("document_id")
            chunk_id = getattr(obj, "id", None) or meta.get("chunk_id")
            start_char = meta.get("start_char")
            end_char = meta.get("end_char")
            page_number = meta.get("page_number") or meta.get("page")

        out = {
            "document_id": str(doc_id) if doc_id is not None else None,
            "chunk_id": str(chunk_id) if chunk_id is not None else None,
            "text": str(text or ""),
            "start_char": start_char,
            "end_char": end_char,
            "page_number": page_number,
        }
        yield out


def _rank_claim_chunks(
    claim: str,
    *,
    claim_tokens: set[str],
    chunks: list[dict[str, Any]],
    verifier_options: dict[str, Any],
) -> list[tuple[float, int, dict[str, Any]]]:
    ranked: list[tuple[float, int, dict[str, Any]]] = []
    for chunk in chunks:
        text = str(chunk.get("text") or "")
        if not text.strip() or not is_claim_supported(claim, text, **verifier_options):
            continue
        shared_count = len(claim_tokens.intersection(_token_set(text)))
        if shared_count <= 0:
            continue
        score = float(shared_count) / float(max(1, len(claim_tokens)))
        ranked.append((score, shared_count, chunk))
    ranked.sort(key=lambda item: (-item[0], -item[1], str(item[2].get("chunk_id") or "")))
    return ranked


def _absolute_span(
    chunk: dict[str, Any],
    *,
    local_start: int,
    local_end: int,
) -> tuple[int | None, int | None]:
    try:
        base = chunk.get("start_char")
        base_index = int(base) if base is not None else None
    except Exception:
        base_index = None
    if base_index is None:
        return None, None
    return base_index + int(local_start), base_index + int(local_end)


def _ranked_evidence_entry(
    score: float,
    chunk: dict[str, Any],
    *,
    terms: list[str],
    max_quote_chars: int,
) -> dict[str, Any]:
    text = str(chunk.get("text") or "")
    span = _extract_span(text, terms, max_chars=max_quote_chars)
    if span is None:
        quote = _collapse_ws(text)[:max_quote_chars]
        absolute_start, absolute_end = None, None
    else:
        local_start, local_end, quote = span
        absolute_start, absolute_end = _absolute_span(
            chunk,
            local_start=local_start,
            local_end=local_end,
        )
    return {
        "document_id": chunk.get("document_id"),
        "chunk_id": chunk.get("chunk_id"),
        "start_char": absolute_start,
        "end_char": absolute_end,
        "quote": quote,
        "score": round(float(score), 4),
    }


def _claim_evidence_entry(
    claim: str,
    *,
    chunks: list[dict[str, Any]],
    max_evidence: int,
    max_quote_chars: int,
    verifier_options: dict[str, Any],
) -> dict[str, Any] | None:
    claim_text = (claim or "").strip()
    if not claim_text:
        return None
    if _UNCERTAINTY_RE.search(claim_text):
        return {"claim": claim_text, "evidence": []}

    claim_tokens = _token_set(claim_text)
    if not claim_tokens or max_evidence <= 0 or not chunks:
        return {"claim": claim_text, "evidence": []}
    ranked = _rank_claim_chunks(
        claim_text,
        claim_tokens=claim_tokens,
        chunks=chunks,
        verifier_options=verifier_options,
    )
    terms = sorted(claim_tokens, key=len, reverse=True)[:12]
    evidence = [
        _ranked_evidence_entry(
            score,
            chunk,
            terms=terms,
            max_quote_chars=max_quote_chars,
        )
        for score, _shared_count, chunk in ranked[:max_evidence]
    ]
    return {"claim": claim_text, "evidence": evidence}


def build_claim_evidence_map(
    answer: str,
    *,
    evidence_chunks: list[Any],
    max_claims: int = 24,
    max_evidence_per_claim: int = 2,
    max_quote_chars: int = 240,
    verifier_mode: str = "token_overlap",
    verifier_enable_contradiction_check: bool = True,
    use_nli_fallback: bool = False,
    nli_provider: str | None = None,
    nli_model_name: str | None = None,
    nli_timeout_sec: float | None = None,
) -> list[dict[str, Any]]:
    """
    Build a JSON-safe list of claim → evidence mappings.

    Output shape:
    [
      {
        "claim": str,
        "evidence": [
          {
            "document_id": str|None,
            "chunk_id": str|None,
            "start_char": int|None,
            "end_char": int|None,
            "quote": str,
            "score": float,
          },
          ...
        ]
      },
      ...
    ]
    """
    max_claims = max(1, int(max_claims or 0))
    max_evidence_per_claim = max(0, int(max_evidence_per_claim or 0))
    max_quote_chars = max(80, int(max_quote_chars or 0))

    claims = split_into_claims(answer or "", max_claims=max_claims)
    chunks = list(_iter_chunks(evidence_chunks or []))
    verifier_options = {
        "verifier_mode": verifier_mode,
        "verifier_enable_contradiction_check": verifier_enable_contradiction_check,
        "use_nli_fallback": bool(use_nli_fallback),
        "nli_provider": nli_provider,
        "nli_model_name": nli_model_name,
        "nli_timeout_sec": nli_timeout_sec,
    }
    out: list[dict[str, Any]] = []
    for claim in claims:
        entry = _claim_evidence_entry(
            claim,
            chunks=chunks,
            max_evidence=max_evidence_per_claim,
            max_quote_chars=max_quote_chars,
            verifier_options=verifier_options,
        )
        if entry is not None:
            out.append(entry)

    return out


__all__ = ["build_claim_evidence_map"]
