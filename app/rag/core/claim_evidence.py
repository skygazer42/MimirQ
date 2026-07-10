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
    r"(unable to answer|cannot determine|can't determine|insufficient evidence|not enough (?:info|information)|unknown|unsure|not sure|"
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


def _extract_span(text: str, terms: list[str], *, max_chars: int) -> tuple[int, int, str] | None:
    """
    Return (start, end, quote) span in `text` that best matches `terms`.
    """
    max_chars = max(80, int(max_chars or 0))
    raw = str(text or "")
    if not raw.strip() or not terms:
        return None

    folded = raw.casefold()
    best_idx: int | None = None
    for t in terms:
        if not t:
            continue
        if str(t).isascii():
            idx = folded.find(str(t).casefold())
        else:
            idx = raw.find(str(t))
        if idx < 0:
            continue
        if best_idx is None or idx < best_idx:
            best_idx = idx

    if best_idx is None:
        return None

    before = max_chars // 3
    after = max_chars - before
    base_start = max(0, best_idx - before)
    base_end = min(len(raw), best_idx + after)

    start = base_start
    end = base_end
    prev = _find_prev_boundary(raw, start=base_start, end=best_idx)
    if prev >= 0:
        start = min(max(base_start, prev + 1), len(raw))
    nxt = _find_next_boundary(raw, start=best_idx, end=base_end)
    if nxt is not None:
        end = min(max(start, nxt + 1), len(raw))

    quote_raw = raw[start:end]
    quote = _collapse_ws(quote_raw).strip() or _collapse_ws(raw[base_start:base_end])
    if start > 0:
        quote = "..." + quote
    if end < len(raw):
        quote = quote + "..."
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
            page_number = obj.get("page_number") if obj.get("page_number") is not None else meta.get("page_number") or meta.get("page")
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

    out: list[dict[str, Any]] = []
    for claim in claims:
        c = (claim or "").strip()
        if not c:
            continue

        if _UNCERTAINTY_RE.search(c):
            out.append({"claim": c, "evidence": []})
            continue

        c_tokens = _token_set(c)
        if not c_tokens or max_evidence_per_claim <= 0 or not chunks:
            out.append({"claim": c, "evidence": []})
            continue

        ranked: list[tuple[float, int, dict[str, Any]]] = []
        for ch in chunks:
            text = str(ch.get("text") or "")
            if not text.strip():
                continue
            if not is_claim_supported(
                c,
                text,
                verifier_mode=verifier_mode,
                verifier_enable_contradiction_check=verifier_enable_contradiction_check,
                use_nli_fallback=bool(use_nli_fallback),
                nli_provider=nli_provider,
                nli_model_name=nli_model_name,
                nli_timeout_sec=nli_timeout_sec,
            ):
                continue
            e_tokens = _token_set(text)
            shared = c_tokens.intersection(e_tokens)
            shared_n = len(shared)
            if shared_n <= 0:
                continue
            score = float(shared_n) / float(max(1, len(c_tokens)))
            ranked.append((score, shared_n, ch))

        ranked.sort(key=lambda x: (-x[0], -x[1], str(x[2].get("chunk_id") or "")))
        selected = ranked[:max_evidence_per_claim]

        evidence_out: list[dict[str, Any]] = []
        for score, _shared_n, ch in selected:
            text = str(ch.get("text") or "")
            terms = sorted(c_tokens, key=len, reverse=True)[:12]
            span = _extract_span(text, terms, max_chars=max_quote_chars)
            if span is not None:
                local_start, local_end, quote = span
                abs_start: int | None = None
                abs_end: int | None = None
                try:
                    base = ch.get("start_char")
                    base_i = int(base) if base is not None else None
                except Exception:
                    base_i = None
                if base_i is not None:
                    abs_start = base_i + int(local_start)
                    abs_end = base_i + int(local_end)
            else:
                quote = _collapse_ws(text)[:max_quote_chars]
                abs_start = None
                abs_end = None

            evidence_out.append(
                {
                    "document_id": ch.get("document_id"),
                    "chunk_id": ch.get("chunk_id"),
                    "start_char": abs_start,
                    "end_char": abs_end,
                    "quote": quote,
                    "score": round(float(score), 4),
                }
            )

        out.append({"claim": c, "evidence": evidence_out})

    return out


__all__ = ["build_claim_evidence_map"]
