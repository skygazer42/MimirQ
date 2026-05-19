"""
Small text helpers shared across RAG modules.
"""

import json
import re
from typing import Any, Literal

from app.core.token_utils import estimate_tokens  # noqa: F401
from app.rag.core.claim_nli_verifier import verify_claim_with_nli
from app.rag.core.claim_verifier import verify_claim

_SENTENCE_RE = re.compile(r"[^。！？.!?\n]+[。！？.!?\n]?", flags=re.S)
_QUERY_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]+|[\u4e00-\u9fff]{2,}")
_AUTO_LIST_INTENT_RE = re.compile(r"(列举|有哪些|列表|对比|比较|分别|优缺点|差异|汇总|总结)", flags=re.IGNORECASE)
_AUTO_KEYWORD_HINT_RES = (
    re.compile(r"\b(?:traceback|exception|error)\b"),
    re.compile(r"stack\s*trace"),
    re.compile(r"http\s*\d{3}"),
    re.compile(r"0x[0-9a-f]{4,}"),
    re.compile(r"[a-z_][a-z0-9_]{2,}\("),
    re.compile(r"\.\w{1,5}\b"),
)
_RECALL_SCHEMA_HINT_RE = re.compile(r"(字段|column|columns|schema|表结构|ddl)", flags=re.IGNORECASE)
_RECALL_PROCEDURE_HINT_RE = re.compile(r"(如何|怎么|步骤|流程|how\s+to|steps?|procedure)", flags=re.IGNORECASE)
_RECALL_NUMERIC_HINT_RE = re.compile(r"(多少|总数|count|sum|avg|average|mean|max|min|最大|最小)", flags=re.IGNORECASE)
_RECALL_POLICY_HINT_RE = re.compile(r"(条例|规定|政策|条款|policy|regulation|compliance|law)", flags=re.IGNORECASE)
_RECALL_DEFINITION_HINT_RE = re.compile(r"(什么是|是什么|定义|define|meaning|what\s+is)", flags=re.IGNORECASE)
_QUERY_REWRITE_TRIGGER_SUBSTRINGS = (
    "它",
    "它们",
    "他",
    "他们",
    "她",
    "她们",
    "这个",
    "这段",
    "这部分",
    "这些",
    "那",
    "那个",
    "上述",
    "上面",
    "前面",
    "之前",
    "刚才",
    "上文",
    "下文",
    "这里",
    "那里",
    "继续",
    "同上",
    "同理",
)
_DECOMPOSE_STRONG_SPLIT_RE = re.compile(r"[?？。.!！;；\n]+")
# Split on common CN/EN conjunctions that often join multiple sub-questions.
# Keep this conservative (avoid single-char CN splitters like "和") to reduce false splits.
_DECOMPOSE_CONJ_SPLIT_EN_TOKENS = frozenset({"and", "or", "also", "plus", "then"})
_DECOMPOSE_CONJ_SPLIT_CN_RE = re.compile(r"(?:以及|并且|同时|另外|此外|还有|然后)")
_DECOMPOSE_LEADING_FILLER_RE = re.compile(
    r"^(?:and|or|also|then)\s+",
    flags=re.IGNORECASE,
)
_DECOMPOSE_TRAILING_PUNCT = " \t\r\n,，;；:：.!?。！？"


def _extract_json_fence(text: str) -> str | None:
    """
    Extract the first triple-backtick code fence content, limited to:
      ```json
      ...
      ```
    or:
      ```
      ...
      ```

    Implemented without regex to avoid catastrophic-backtracking hotspots.
    """
    raw = text or ""
    if not raw:
        return None
    lower = raw.lower()

    start = lower.find("```")
    while start != -1:
        # Determine the opening fence's info string (until newline/end).
        line_end = raw.find("\n", start + 3)
        if line_end == -1:
            line_end = len(raw)
        info = raw[start + 3 : line_end].strip().lower()
        if info not in ("", "json"):
            start = lower.find("```", start + 3)
            continue

        content_start = line_end + 1 if line_end < len(raw) else line_end
        end = lower.find("```", content_start)
        if end == -1:
            return None
        inner = raw[content_start:end].strip()
        return inner or None

    return None


def _split_on_en_conjunctions(text: str) -> list[str]:
    """
    Split text on common English conjunctions without regex.
    """
    tokens = (text or "").split()
    if len(tokens) < 3:
        return [text] if text else []

    out: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        low = t.casefold()

        # "as well as" is treated as a conjunction splitter.
        if (
            low == "as"
            and i + 2 < len(tokens)
            and tokens[i + 1].casefold() == "well"
            and tokens[i + 2].casefold() == "as"
        ):
            if buf:
                out.append(" ".join(buf))
                buf = []
            i += 3
            continue

        if low in _DECOMPOSE_CONJ_SPLIT_EN_TOKENS:
            if buf:
                out.append(" ".join(buf))
                buf = []
            i += 1
            continue

        buf.append(t)
        i += 1

    if buf:
        out.append(" ".join(buf))
    return out or ([text] if text else [])


def heuristic_decompose_query(query: str, *, max_subquestions: int = 3) -> list[str]:
    """
    Deterministic query decomposition helper (no LLM).

    Splits a multi-part question into <= N sub-questions using punctuation and
    common conjunctions. Designed as a safe fallback when LLM decomposition is
    unavailable.
    """

    max_subquestions = max(0, int(max_subquestions or 0))
    raw = (query or "").strip()
    if not raw or max_subquestions <= 0:
        return []

    def _clean_fragment(text: str) -> str:
        t = (text or "").strip()
        if not t:
            return ""
        # Strip common list prefixes.
        t = re.sub(r"^[-*•]\s+", "", t)
        t = re.sub(r"^\d+\s*[.)]\s+", "", t)
        t = t.strip().strip('"').strip("'").strip()
        t = _DECOMPOSE_LEADING_FILLER_RE.sub("", t).strip()
        # Light punctuation trimming on both ends.
        t = t.strip(_DECOMPOSE_TRAILING_PUNCT).strip()
        # Normalize whitespace.
        t = " ".join(t.split())
        return t

    # 1) Strong splits (sentence/question boundaries)
    chunks = [c.strip() for c in _DECOMPOSE_STRONG_SPLIT_RE.split(raw) if c.strip()]
    if not chunks:
        return []

    # 2) Conjunction splits within each chunk.
    fragments: list[str] = []
    for ch in chunks:
        for frag_en in _split_on_en_conjunctions(ch):
            for frag in _DECOMPOSE_CONJ_SPLIT_CN_RE.split(frag_en):
                cleaned = _clean_fragment(frag)
                if cleaned:
                    fragments.append(cleaned)

    if not fragments:
        return []

    raw_norm = " ".join(raw.split())
    out: list[str] = []
    seen: set[str] = set()

    for frag in fragments:
        # Filter "tiny" fragments that tend to be unhelpful for retrieval.
        tokens = _QUERY_TOKEN_RE.findall(frag)
        if len(frag) < 8 and len(tokens) < 2:
            continue

        key = frag.casefold() if frag.isascii() else frag
        if key in seen:
            continue
        seen.add(key)

        if len(frag) > 500:
            frag = frag[:500] + "..."
        out.append(frag)
        if len(out) >= max_subquestions:
            break

    if not out:
        return []

    # Avoid returning a single "decomposed" fragment that is identical to input.
    if len(out) == 1 and out[0] == raw_norm:
        return []

    return out


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
) -> tuple[Any | None, dict[str, Any]]:
    """
    Best-effort JSON parser for LLM outputs.

    Returns: (data, meta) where meta contains ok/method/error.
    """
    raw = (text or "").strip()
    if not raw:
        return None, {"ok": False, "method": None, "error": "empty"}

    candidates: list[tuple[str, str]] = []

    inner = _extract_json_fence(raw)
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
        except ValueError as exc:
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


def guess_recall_bucket(query: str) -> str:
    """
    Heuristic question-type classifier for recall routing.

    Returns one of:
    - schema | procedure | numeric | policy | definition | general
    """
    q = (query or "").strip()
    if not q:
        return "general"

    # Order matters: prefer narrower buckets over broad "definition".
    if _RECALL_SCHEMA_HINT_RE.search(q):
        return "schema"
    if _RECALL_POLICY_HINT_RE.search(q):
        return "policy"
    if _RECALL_NUMERIC_HINT_RE.search(q):
        return "numeric"
    if _RECALL_PROCEDURE_HINT_RE.search(q):
        return "procedure"
    if _RECALL_DEFINITION_HINT_RE.search(q):
        return "definition"
    return "general"


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
    if any(p.search(q_lower) for p in _AUTO_KEYWORD_HINT_RES) or "/" in q_lower or "\\" in q_lower or "::" in q_lower:
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
    return any(trigger in q for trigger in _QUERY_REWRITE_TRIGGER_SUBSTRINGS)


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


_CLAIM_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]+|[\u4e00-\u9fff]{2,}|\d+(?:\.\d+)?")
_CLAIM_UNCERTAINTY_RE = re.compile(
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


def split_into_claims(text: str, *, max_claims: int = 24) -> list[str]:
    """
    Split assistant answers into simple atomic claims for post-processing.

    Heuristics:
    - Sentence-level splitting for paragraphs
    - Markdown list items become individual claims
    - Preserve original order, drop empty claims, bound to `max_claims`
    """
    max_claims = max(1, int(max_claims or 0))
    raw = (text or "").strip()
    if not raw:
        return []

    claims: list[str] = []
    paragraph_lines: list[str] = []

    def _parse_list_item(raw: str) -> str | None:
        s = (raw or "").lstrip()
        if not s:
            return None

        # Bullets: - / * / •
        if s[0] in ("-", "*", "•"):
            i = 1
            if i >= len(s) or not s[i].isspace():
                return None
            while i < len(s) and s[i].isspace():
                i += 1
            item = s[i:].strip()
            return item or None

        # Ordered list: 1. / 1)
        i = 0
        while i < len(s) and s[i].isdigit():
            i += 1
        if i == 0:
            return None
        while i < len(s) and s[i].isspace():
            i += 1
        if i >= len(s) or s[i] not in (".", ")"):
            return None
        i += 1
        if i >= len(s) or not s[i].isspace():
            return None
        while i < len(s) and s[i].isspace():
            i += 1
        item = s[i:].strip()
        return item or None

    def _flush_paragraph() -> bool:
        if not paragraph_lines:
            return False
        paragraph = " ".join([ln.strip() for ln in paragraph_lines if ln.strip()]).strip()
        paragraph_lines.clear()
        if not paragraph:
            return False
        for m in _SENTENCE_RE.finditer(paragraph):
            s = (m.group(0) or "").strip()
            if not s:
                continue
            claims.append(s)
            if len(claims) >= max_claims:
                return True
        return False

    for raw_line in (text or "").splitlines():
        line = (raw_line or "").strip()
        if not line:
            if _flush_paragraph():
                break
            continue

        item = _parse_list_item(raw_line)
        if item:
            if _flush_paragraph():
                break
            claims.append(item)
            if len(claims) >= max_claims:
                break
            continue

        paragraph_lines.append(line)

    if len(claims) < max_claims:
        _flush_paragraph()

    return [c for c in claims if c.strip()][:max_claims]


def _claim_token_set(text: str) -> set[str]:
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


def verify_claim_with_fallback(
    claim: str,
    evidence: str,
    *,
    verifier_mode: str = "token_overlap",
    verifier_enable_contradiction_check: bool = True,
    use_nli_fallback: bool = False,
    nli_provider: str | None = None,
    nli_model_name: str | None = None,
    nli_timeout_sec: float | None = None,
):
    result = verify_claim(
        claim,
        evidence,
        mode=verifier_mode,
        enable_contradiction_check=bool(verifier_enable_contradiction_check),
    )
    if bool(result.supported) or not bool(use_nli_fallback):
        return result

    nli_result = verify_claim_with_nli(
        claim,
        evidence,
        enabled=True,
        provider=nli_provider,
        model_name=nli_model_name,
        timeout_sec=nli_timeout_sec,
    )
    diagnostics = dict(result.diagnostics or {})
    diagnostics["nli_fallback"] = {
        "available": bool(nli_result.available),
        "label": nli_result.label,
        "provider": dict(nli_result.provider_status or {}),
        "reason_code": str((nli_result.diagnostics or {}).get("reason_code") or ""),
    }
    if not bool(nli_result.available) or nli_result.supported is None:
        return result.__class__(supported=result.supported, mode=result.mode, diagnostics=diagnostics)

    diagnostics["reason"] = str((nli_result.diagnostics or {}).get("reason_code") or "nli_neutral")
    diagnostics["reason_code"] = str((nli_result.diagnostics or {}).get("reason_code") or "nli_neutral")
    diagnostics["contradiction_type"] = None
    return result.__class__(
        supported=bool(nli_result.supported),
        mode=f"{result.mode}+nli",
        diagnostics=diagnostics,
    )


def is_claim_supported(
    claim: str,
    evidence: str,
    *,
    verifier_mode: str = "token_overlap",
    verifier_enable_contradiction_check: bool = True,
    use_nli_fallback: bool = False,
    nli_provider: str | None = None,
    nli_model_name: str | None = None,
    nli_timeout_sec: float | None = None,
) -> bool:
    """
    Deterministic baseline: token-overlap check between a claim and evidence text.

    Notes:
    - Always keep "uncertainty/insufficient evidence" phrasing (do not delete refusals).
    - Heuristic only; designed to be safe and bounded.
    """
    result = verify_claim_with_fallback(
        claim,
        evidence,
        verifier_mode=verifier_mode,
        verifier_enable_contradiction_check=bool(verifier_enable_contradiction_check),
        use_nli_fallback=bool(use_nli_fallback),
        nli_provider=nli_provider,
        nli_model_name=nli_model_name,
        nli_timeout_sec=nli_timeout_sec,
    )
    return bool(result.supported)


def scrub_structured_output_visible_evidence_only(
    data: Any,
    *,
    evidence_text: str,
    max_claims: int = 24,
    verifier_mode: str = "token_overlap",
    verifier_enable_contradiction_check: bool = True,
    use_nli_fallback: bool = False,
    nli_provider: str | None = None,
    nli_model_name: str | None = None,
    nli_timeout_sec: float | None = None,
    max_depth: int = 6,
    max_items: int = 500,
) -> tuple[Any, dict[str, Any]]:
    """
    Best-effort structured-output scrubbing for strict grounding.

    This keeps the JSON shape, but removes unsupported natural-language claims inside string fields.
    It is deterministic and bounded (no extra model calls).

    Notes:
    - We intentionally do NOT scrub common identifier/citation keys (UUIDs, ids) because they are
      not "claims" and would almost always be removed by evidence checks.
    - We apply a global max_claims budget across all visited string fields to keep it bounded.
    """
    max_claims = max(1, int(max_claims or 0))
    max_depth = max(1, int(max_depth or 0))
    max_items = max(1, int(max_items or 0))

    # Keys that should not be treated as natural-language claims.
    skip_keys = {
        "citations",
        "document_id",
        "chunk_id",
        "page_number",
        "page",
        "relevance_score",
        "retrieval_score",
        "vector_score",
        "bm25_score",
        "keyword_score",
        "rerank_score",
        "reranker_provider",
        "rerank_model_used",
    }

    meta: dict[str, Any] = {
        "strings_scrubbed": 0,
        "strings_changed": 0,
        "claims_total": 0,
        "claims_removed": 0,
        "claim_check_removed_reasons": [],
        "max_claims": max_claims,
        "max_depth": max_depth,
        "max_items": max_items,
    }

    remaining_claims = max_claims
    visited_items = 0

    def _scrub_str(s: str) -> str:
        nonlocal remaining_claims
        raw = str(s or "")
        if not raw.strip():
            return raw
        if remaining_claims <= 0:
            return raw

        claims = split_into_claims(raw, max_claims=remaining_claims)
        remaining_claims -= len(claims)
        meta["claims_total"] = int(meta.get("claims_total", 0) or 0) + len(claims)

        kept: list[str] = []
        removed = 0
        for c in claims:
            vr = verify_claim_with_fallback(
                c,
                evidence_text,
                verifier_mode=verifier_mode,
                verifier_enable_contradiction_check=verifier_enable_contradiction_check,
                use_nli_fallback=bool(use_nli_fallback),
                nli_provider=nli_provider,
                nli_model_name=nli_model_name,
                nli_timeout_sec=nli_timeout_sec,
            )
            if bool(vr.supported):
                kept.append(c)
            else:
                removed += 1
                reasons = meta.get("claim_check_removed_reasons")
                if isinstance(reasons, list) and len(reasons) < 64:
                    diag = vr.diagnostics if isinstance(vr.diagnostics, dict) else {}
                    reasons.append(
                        {
                            "claim": str(c or "")[:300],
                            "reason_code": str(diag.get("reason_code") or diag.get("reason") or "unsupported")[:120],
                            "contradiction_type": (
                                str(diag.get("contradiction_type"))[:120]
                                if diag.get("contradiction_type") is not None
                                else None
                            ),
                        }
                    )
        if removed:
            meta["claims_removed"] = int(meta.get("claims_removed", 0) or 0) + removed

        cleaned = "\n".join(kept).strip()
        return cleaned

    def _walk(obj: Any, *, depth: int, parent_key: str | None) -> Any:
        nonlocal visited_items
        if visited_items >= max_items:
            return obj
        visited_items += 1

        if depth <= 0:
            return obj

        if isinstance(obj, dict):
            out: dict[Any, Any] = {}
            for k, v in obj.items():
                ks = str(k)
                if ks in skip_keys:
                    out[k] = v
                    continue
                out[k] = _walk(v, depth=depth - 1, parent_key=ks)
            return out

        if isinstance(obj, list):
            out_list: list[Any] = []
            for it in obj:
                v2 = _walk(it, depth=depth - 1, parent_key=parent_key)
                # Drop empty strings from arrays (common for bullets/qa pairs after scrubbing).
                if isinstance(v2, str) and not v2.strip():
                    continue
                out_list.append(v2)
            return out_list

        if isinstance(obj, str):
            meta["strings_scrubbed"] = int(meta.get("strings_scrubbed", 0) or 0) + 1
            cleaned = _scrub_str(obj)
            if cleaned != obj:
                meta["strings_changed"] = int(meta.get("strings_changed", 0) or 0) + 1
            return cleaned

        return obj

    scrubbed = _walk(data, depth=max_depth, parent_key=None)
    meta["visited_items"] = visited_items
    meta["claims_remaining"] = remaining_claims
    return scrubbed, meta


def build_abstain_followup(
    *,
    reason: str | None,
    citations: list[dict[str, Any]] | None = None,
    max_options: int = 3,
) -> dict[str, Any]:
    """Build deterministic follow-up guidance for abstain responses.

    PII-safety constraints:
    - Only expose doc identifiers/names (no raw chunk text).
    - Do not do any extra network/model calls.
    """
    max_options = max(0, int(max_options or 0))

    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    for c in (citations or []) if isinstance(citations, list) else []:
        if not isinstance(c, dict):
            continue
        did = c.get("document_id")
        name = c.get("document_name") or c.get("source")
        key = str(did or name or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        options.append(
            {
                "document_id": str(did) if did is not None else None,
                "document_name": str(name) if name is not None else None,
            }
        )
        if max_options and len(options) >= max_options:
            break

    r = str(reason or "").strip()
    if r == "citations_lt_min":
        return {
            "type": "refine_query",
            "question": "No sufficient evidence was retrieved. Please refine the question or provide more relevant documents.",
            "options": [],
        }
    if r == "out_of_scope":
        return {
            "type": "refine_query",
            "question": "This question appears to be outside the current knowledge base. Please add relevant materials or narrow the scope.",
            "options": [],
        }

    # Default: show related docs (if any) and ask user to narrow scope.
    return {
        "type": "select_document" if options else "refine_query",
        "question": "I found related materials but not enough to answer confidently. Which document should I focus on?",
        "options": options,
    }


def build_abstain_answer_message(reason: str | None) -> str:
    if str(reason or "").strip() == "out_of_scope":
        return "This question appears to be outside the current knowledge base."
    return "Unable to answer this question based on the available materials."


def derive_followup_questions(
    abstain_followup: dict[str, Any] | None,
    *,
    max_questions: int = 3,
) -> list[str]:
    """Derive deterministic user-facing follow-up questions from abstain metadata."""
    if not isinstance(abstain_followup, dict):
        return []

    limit = max(0, int(max_questions or 0))
    raw_options = abstain_followup.get("options")
    question = str(abstain_followup.get("question") or "").strip()

    followups: list[str] = []
    seen: set[str] = set()
    if isinstance(raw_options, list):
        for option in raw_options:
            if not isinstance(option, dict):
                continue
            label = str(option.get("document_name") or option.get("document_id") or "").strip()
            if not label or label in seen:
                continue
            seen.add(label)
            followups.append(f'Ask specifically about "{label}".')
            if limit and len(followups) >= limit:
                return followups

    if followups:
        return followups

    return [question] if question else []


def extract_followup_questions_from_answer(
    answer: str | None,
    *,
    max_items: int = 3,
) -> tuple[str, list[str]]:
    """Extract repeated <followup> tags from an answer and return clean body + questions."""
    raw = str(answer or "")
    open_tag = "<followup>"
    close_tag = "</followup>"
    lower = raw.lower()
    limit = max(0, int(max_items or 0))

    questions: list[str] = []
    seen: set[str] = set()
    cleaned_parts: list[str] = []
    cursor = 0
    found_tag = False
    while True:
        start = lower.find(open_tag, cursor)
        if start == -1:
            cleaned_parts.append(raw[cursor:])
            break

        end = lower.find(close_tag, start + len(open_tag))
        if end == -1:
            cleaned_parts.append(raw[cursor:])
            break

        found_tag = True
        cleaned_parts.append(raw[cursor:start])
        question = " ".join(raw[start + len(open_tag):end].split())
        key = question.casefold()
        if question and key not in seen and (not limit or len(questions) < limit):
            seen.add(key)
            questions.append(question)
        cursor = end + len(close_tag)

    if not found_tag:
        return raw, []

    normalized_lines: list[str] = []
    pending_blank = False
    for line in "".join(cleaned_parts).splitlines():
        stripped = line.strip()
        if stripped:
            if pending_blank and normalized_lines:
                normalized_lines.append("")
            normalized_lines.append(stripped)
            pending_blank = False
        else:
            pending_blank = True

    cleaned = "\n".join(normalized_lines).strip()
    return cleaned, questions
