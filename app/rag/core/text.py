"""
Small text helpers shared across RAG modules.
"""


import json
import re
from typing import Any, Dict, Literal, Tuple

from app.core.token_utils import estimate_tokens  # noqa: F401
from app.rag.core.claim_verifier import verify_claim

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", flags=re.IGNORECASE | re.DOTALL)
_SENTENCE_RE = re.compile(r"[^。！？.!?\n]+[。！？.!?\n]?", flags=re.S)
_QUERY_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]{1,}|[\u4e00-\u9fff]{2,}")
_AUTO_LIST_INTENT_RE = re.compile(r"(列举|有哪些|列表|对比|比较|分别|优缺点|差异|汇总|总结)", flags=re.IGNORECASE)
_AUTO_KEYWORD_HINT_RE = re.compile(
    r"(traceback|exception|stack\s*trace|error|http\s*\d{3}|0x[0-9a-f]{4,}|[a-z_][a-z0-9_]{2,}\(|\.\w{1,5}\b|/|\\\\|::)",
    flags=re.IGNORECASE,
)
_RECALL_SCHEMA_HINT_RE = re.compile(r"(字段|column|columns|schema|表结构|ddl)", flags=re.IGNORECASE)
_RECALL_PROCEDURE_HINT_RE = re.compile(r"(如何|怎么|步骤|流程|how\s+to|steps?|procedure)", flags=re.IGNORECASE)
_RECALL_NUMERIC_HINT_RE = re.compile(r"(多少|总数|count|sum|avg|average|mean|max|min|最大|最小)", flags=re.IGNORECASE)
_RECALL_POLICY_HINT_RE = re.compile(r"(条例|规定|政策|条款|policy|regulation|compliance|law)", flags=re.IGNORECASE)
_RECALL_DEFINITION_HINT_RE = re.compile(r"(什么是|是什么|定义|define|meaning|what\s+is)", flags=re.IGNORECASE)
_QUERY_REWRITE_TRIGGER_RE = re.compile(
    r"(它们?|他(们)?|她(们)?|这个|这(段|部分|些)|那(个)?|上述|上面|前面|之前|刚才|上文|下文|这里|那里|继续|同上|同理)",
    flags=re.IGNORECASE,
)
_DECOMPOSE_STRONG_SPLIT_RE = re.compile(r"[?？。.!！;；\n]+")
# Split on common CN/EN conjunctions that often join multiple sub-questions.
# Keep this conservative (avoid single-char CN splitters like "和") to reduce false splits.
_DECOMPOSE_CONJ_SPLIT_RE = re.compile(
    r"(?:\s+(?:and|or|also|plus|then|as\s+well\s+as)\s+|(?:以及|并且|同时|另外|此外|还有|然后))",
    flags=re.IGNORECASE,
)
_DECOMPOSE_LEADING_FILLER_RE = re.compile(
    r"^(?:and|or|also|then)\s+",
    flags=re.IGNORECASE,
)
_DECOMPOSE_TRAILING_PUNCT = " \t\r\n,，;；:：.!?。！？"


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
        for frag in _DECOMPOSE_CONJ_SPLIT_RE.split(ch):
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


_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*•]|\d+\s*[.)])\s+(?P<item>.+?)\s*$")
_CLAIM_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]{1,}|[\u4e00-\u9fff]{2,}|\d+(?:\.\d+)?")
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

        m = _LIST_ITEM_RE.match(raw_line)
        if m:
            if _flush_paragraph():
                break
            item = (m.group("item") or "").strip()
            if item:
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


def is_claim_supported(
    claim: str,
    evidence: str,
    *,
    verifier_mode: str = "token_overlap",
    verifier_enable_contradiction_check: bool = True,
) -> bool:
    """
    Deterministic baseline: token-overlap check between a claim and evidence text.

    Notes:
    - Always keep "uncertainty/insufficient evidence" phrasing (do not delete refusals).
    - Heuristic only; designed to be safe and bounded.
    """
    result = verify_claim(
        claim,
        evidence,
        mode=verifier_mode,
        enable_contradiction_check=bool(verifier_enable_contradiction_check),
    )
    return bool(result.supported)


def scrub_structured_output_visible_evidence_only(
    data: Any,
    *,
    evidence_text: str,
    max_claims: int = 24,
    verifier_mode: str = "token_overlap",
    verifier_enable_contradiction_check: bool = True,
    max_depth: int = 6,
    max_items: int = 500,
) -> tuple[Any, Dict[str, Any]]:
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

    meta: Dict[str, Any] = {
        "strings_scrubbed": 0,
        "strings_changed": 0,
        "claims_total": 0,
        "claims_removed": 0,
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
            if is_claim_supported(
                c,
                evidence_text,
                verifier_mode=verifier_mode,
                verifier_enable_contradiction_check=verifier_enable_contradiction_check,
            ):
                kept.append(c)
            else:
                removed += 1
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

    # Default: show related docs (if any) and ask user to narrow scope.
    return {
        "type": "select_document" if options else "refine_query",
        "question": "I found related materials but not enough to answer confidently. Which document should I focus on?",
        "options": options,
    }
