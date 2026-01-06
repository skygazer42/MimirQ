"""
Small text helpers shared across RAG modules.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Tuple, Literal


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", flags=re.IGNORECASE | re.DOTALL)
_SENTENCE_RE = re.compile(r"[^。！？.!?\n]+[。！？.!?\n]?", flags=re.S)
_QUERY_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]{1,}|[\u4e00-\u9fff]{2,}")
_AUTO_LIST_INTENT_RE = re.compile(r"(列举|有哪些|列表|对比|比较|分别|优缺点|差异|汇总|总结)", flags=re.IGNORECASE)
_AUTO_KEYWORD_HINT_RE = re.compile(
    r"(traceback|exception|stack\s*trace|error|http\s*\d{3}|0x[0-9a-f]{4,}|[a-z_][a-z0-9_]{2,}\(|\.\w{1,5}\b|/|\\\\|::)",
    flags=re.IGNORECASE,
)
_QUERY_REWRITE_TRIGGER_RE = re.compile(
    r"(它们?|他(们)?|她(们)?|这个|这(段|部分|些)|那(个)?|上述|上面|前面|之前|刚才|上文|下文|这里|那里|继续|同上|同理)",
    flags=re.IGNORECASE,
)


def estimate_tokens(text: str) -> int:
    """Rough token estimate used for guards; not exact."""
    return max(1, len(text) // 4)


def _extract_string_items_from_lines(text: str, *, max_items: int = 12) -> list[str]:
    max_items = max(1, int(max_items or 0))
    items: list[str] = []
    seen: set[str] = set()
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Strip common list prefixes: "- ", "* ", "1. ", "1) ", "• ".
        line = re.sub(r"^[-*•]\s+", "", line)
        line = re.sub(r"^\d+\s*[.)]\s+", "", line)
        line = line.strip().strip('"').strip("'").strip()
        if not line:
            continue
        if line in seen:
            continue
        seen.add(line)
        items.append(line)
        if len(items) >= max_items:
            break
    return items


def parse_json_from_text(
    text: str,
    *,
    expected: Literal["any", "array", "object"] = "any",
) -> Tuple[Any | None, Dict[str, Any]]:
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
            if expected == "any":
                return data, {"ok": True, "method": method, "error": None}
            if expected == "object":
                if isinstance(data, dict):
                    return data, {"ok": True, "method": method, "error": None}
                last_error = f"expected_object_got_{type(data).__name__}"
                continue
            if expected == "array":
                if isinstance(data, list):
                    return data, {"ok": True, "method": method, "error": None}
                if isinstance(data, dict):
                    # Common LLM wrapper formats: {"items":[...]} / {"queries":[...]}.
                    for k in ("items", "queries", "data", "results"):
                        v = data.get(k)
                        if isinstance(v, list):
                            return v, {"ok": True, "method": f"{method}:wrapped:{k}", "error": None}
                    # Fall back: if there's exactly one list value, unwrap it.
                    list_values = [v for v in data.values() if isinstance(v, list)]
                    if len(list_values) == 1:
                        return list_values[0], {"ok": True, "method": f"{method}:wrapped:single_list", "error": None}
                last_error = f"expected_array_got_{type(data).__name__}"
                continue
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)[:200]
            continue

    if expected == "array":
        items = _extract_string_items_from_lines(raw, max_items=12)
        if items:
            return items, {"ok": True, "method": "lines", "error": None}

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


def should_rewrite_query(question: str, *, short_len: int = 12) -> bool:
    """
    Heuristic guard for Query Rewrite (reduce unnecessary LLM calls).

    - Always rewrite very short follow-ups (likely coreference)
    - Otherwise, rewrite only when we detect coreference-like triggers
    """
    q = (question or "").strip()
    if not q:
        return False
    short_len = max(1, int(short_len or 0))
    if len(q) <= short_len:
        return True
    return bool(_QUERY_REWRITE_TRIGGER_RE.search(q))


_VALID_RETRIEVAL_MODES = {"hybrid", "vector", "keyword", "mmr", "auto"}
_RETRIEVAL_MODE_ALIASES = {
    "fulltext": "keyword",
    "bm25": "keyword",
    "sparse": "keyword",
    "lexical": "keyword",
    "dense": "vector",
    "semantic": "vector",
}


def normalize_retrieval_mode(mode: str | None) -> str:
    """
    Normalize retrieval mode strings for API compatibility.

    Supported: auto | hybrid | vector | keyword | mmr
    Aliases: fulltext/bm25/sparse/lexical -> keyword, dense/semantic -> vector.
    """
    raw = (mode or "").strip().lower()
    if not raw:
        return "hybrid"
    mapped = _RETRIEVAL_MODE_ALIASES.get(raw, raw)
    if mapped in _VALID_RETRIEVAL_MODES:
        return mapped
    return "hybrid"
