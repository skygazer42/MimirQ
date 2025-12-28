"""
Small text helpers shared across RAG modules.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Tuple


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", flags=re.IGNORECASE | re.DOTALL)
_SENTENCE_RE = re.compile(r"[^。！？.!?\n]+[。！？.!?\n]?", flags=re.S)
_QUERY_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]{1,}|[\u4e00-\u9fff]{2,}")
_AUTO_LIST_INTENT_RE = re.compile(r"(列举|有哪些|列表|对比|比较|分别|优缺点|差异|汇总|总结)", flags=re.IGNORECASE)
_AUTO_KEYWORD_HINT_RE = re.compile(
    r"(traceback|exception|stack\s*trace|error|http\s*\d{3}|0x[0-9a-f]{4,}|[a-z_][a-z0-9_]{2,}\(|\.\w{1,5}\b|/|\\\\|::)",
    flags=re.IGNORECASE,
)


def estimate_tokens(text: str) -> int:
    """Rough token estimate used for guards; not exact."""
    return max(1, len(text) // 4)


def parse_json_from_text(text: str) -> Tuple[Any | None, Dict[str, Any]]:
    """
    Best-effort JSON parser for LLM outputs.

    Returns: (data, meta) where meta contains ok/method/error.
    """
    raw = (text or "").strip()
    if not raw:
        return None, {"ok": False, "method": None, "error": "empty"}

    candidates: list[tuple[str, str]] = []

    fence = _JSON_FENCE_RE.search(raw)
    if fence:
        inner = (fence.group(1) or "").strip()
        if inner:
            candidates.append(("code_fence", inner))

    candidates.append(("raw", raw))

    obj_start = raw.find("{")
    obj_end = raw.rfind("}")
    if obj_start != -1 and obj_end != -1 and obj_end > obj_start:
        candidates.append(("first_last_brace", raw[obj_start : obj_end + 1].strip()))

    arr_start = raw.find("[")
    arr_end = raw.rfind("]")
    if arr_start != -1 and arr_end != -1 and arr_end > arr_start:
        candidates.append(("first_last_bracket", raw[arr_start : arr_end + 1].strip()))

    last_error: str | None = None
    for method, candidate in candidates:
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
            return data, {"ok": True, "method": method, "error": None}
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)[:200]
            continue

    return None, {"ok": False, "method": None, "error": last_error or "invalid_json"}


def extract_evidence_text(
    text: str,
    query: str,
    *,
    max_chars: int = 0,
    max_sentences: int = 6,
    min_sentence_chars: int = 10,
    max_terms: int = 12,
) -> str:
    """
    Lightweight context compressor: select the most query-relevant sentences/lines.

    This is a heuristic extractor (no LLM). Returns plain text.
    """
    raw = (text or "").strip()
    if not raw:
        return ""

    max_chars = max(0, int(max_chars or 0))
    max_sentences = max(0, int(max_sentences or 0))
    min_sentence_chars = max(0, int(min_sentence_chars or 0))
    max_terms = max(0, int(max_terms or 0))

    if max_chars and len(raw) <= max_chars:
        return raw
    if max_sentences <= 0:
        return (raw[:max_chars] + "...") if max_chars and len(raw) > max_chars else raw

    q = (query or "").strip()
    if not q:
        return (raw[:max_chars] + "...") if max_chars and len(raw) > max_chars else raw

    terms: list[str] = []
    for m in _QUERY_TOKEN_RE.finditer(q):
        t = (m.group(0) or "").strip()
        if not t:
            continue
        t_norm = t.casefold() if t.isascii() else t
        if t_norm in terms:
            continue
        terms.append(t_norm)
        if max_terms and len(terms) >= max_terms:
            break

    if not terms:
        return (raw[:max_chars] + "...") if max_chars and len(raw) > max_chars else raw

    sentences: list[str] = []
    for m in _SENTENCE_RE.finditer(raw):
        s = (m.group(0) or "").strip()
        if not s:
            continue
        if min_sentence_chars and len(s) < min_sentence_chars:
            continue
        sentences.append(s)

    if not sentences:
        return (raw[:max_chars] + "...") if max_chars and len(raw) > max_chars else raw

    ranked: list[tuple[int, int, int]] = []
    for idx, s in enumerate(sentences):
        score = 0
        folded = s.casefold()
        for t in terms:
            if not t:
                continue
            if str(t).isascii():
                if str(t).casefold() in folded:
                    score += 1
            else:
                if str(t) in s:
                    score += 1
        if score > 0:
            ranked.append((score, len(s), idx))

    if ranked:
        ranked.sort(key=lambda x: (-x[0], x[1], x[2]))
        picked_idx = sorted([idx for _, _, idx in ranked[:max_sentences]])
        picked = [sentences[i] for i in picked_idx]
    else:
        picked = sentences[:max_sentences]

    out = "\n".join(picked).strip()
    if max_chars and len(out) > max_chars:
        out = out[:max_chars] + "..."
    return out


def guess_retrieval_mode(query: str) -> str:
    """
    Heuristic retrieval mode router for `auto`.

    Returns one of: hybrid | keyword | mmr
    """
    q = (query or "").strip()
    if not q:
        return "hybrid"

    if _AUTO_LIST_INTENT_RE.search(q):
        return "mmr"

    q_lower = q.lower()
    if _AUTO_KEYWORD_HINT_RE.search(q_lower):
        return "keyword"

    cjk = sum(1 for ch in q if "\u4e00" <= ch <= "\u9fff")
    ascii_non_space = sum(1 for ch in q if ch.isascii() and not ch.isspace())
    if cjk == 0 and ascii_non_space > 0 and len(q) <= 40:
        return "keyword"

    return "hybrid"

