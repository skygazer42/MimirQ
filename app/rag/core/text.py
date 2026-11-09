"""
Small text helpers shared across RAG modules.
"""

import re
from collections.abc import Iterator
from typing import Any, NotRequired, TypedDict

from app.core.token_utils import estimate_tokens as estimate_tokens
from app.rag.core.claim_nli_verifier import verify_claim_with_nli
from app.rag.core.claim_verifier import ClaimVerificationResult, verify_claim
from app.rag.core.json_text import parse_json_from_text as parse_json_from_text
from app.rag.core.retrieval_modes import normalize_retrieval_mode as normalize_retrieval_mode

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


def _append_word_fragment(out: list[str], buf: list[str]) -> None:
    if buf:
        out.append(" ".join(buf))
        buf.clear()


def _is_as_well_as(tokens: list[str], index: int) -> bool:
    return (
        index + 2 < len(tokens)
        and tokens[index].casefold() == "as"
        and tokens[index + 1].casefold() == "well"
        and tokens[index + 2].casefold() == "as"
    )


def _split_on_en_conjunctions(text: str) -> list[str]:
    """
    Split text on common English conjunctions without regex.
    """
    tokens = (text).split()
    if len(tokens) < 3:
        return [text] if text else []

    out: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        low = t.casefold()

        # "as well as" is treated as a conjunction splitter.
        if low == "as" and _is_as_well_as(tokens, i):
            _append_word_fragment(out, buf)
            i += 3
            continue

        if low in _DECOMPOSE_CONJ_SPLIT_EN_TOKENS:
            _append_word_fragment(out, buf)
            i += 1
            continue

        buf.append(t)
        i += 1

    _append_word_fragment(out, buf)
    return out or ([text] if text else [])


def _clean_decomposed_fragment(text: str) -> str:
    cleaned = (text).strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"^[-*•]\s+", "", cleaned)
    cleaned = re.sub(r"^\d+\s*[.)]\s+", "", cleaned)
    cleaned = cleaned.strip().strip('"').strip("'").strip()
    cleaned = _DECOMPOSE_LEADING_FILLER_RE.sub("", cleaned).strip()
    cleaned = cleaned.strip(_DECOMPOSE_TRAILING_PUNCT).strip()
    return " ".join(cleaned.split())


def _decomposition_fragments(raw: str) -> list[str]:
    fragments: list[str] = []
    for chunk in [c.strip() for c in _DECOMPOSE_STRONG_SPLIT_RE.split(raw) if c.strip()]:
        for frag_en in _split_on_en_conjunctions(chunk):
            for frag in _DECOMPOSE_CONJ_SPLIT_CN_RE.split(frag_en):
                cleaned = _clean_decomposed_fragment(frag)
                if cleaned:
                    fragments.append(cleaned)
    return fragments


def _is_useful_decomposed_fragment(fragment: str) -> bool:
    tokens = _QUERY_TOKEN_RE.findall(fragment)
    return not (len(fragment) < 8 and len(tokens) < 2)


def _bounded_unique_fragments(fragments: list[str], *, max_items: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for frag in fragments:
        if not _is_useful_decomposed_fragment(frag):
            continue
        key = frag.casefold() if frag.isascii() else frag
        if key in seen:
            continue
        seen.add(key)
        if len(frag) > 500:
            frag = frag[:500] + "..."
        out.append(frag)
        if len(out) >= max_items:
            break
    return out


def heuristic_decompose_query(query: str, *, max_subquestions: int = 3) -> list[str]:
    """
    Deterministic query decomposition helper (no LLM).

    Splits a multi-part question into <= N sub-questions using punctuation and
    common conjunctions. Designed as a safe fallback when LLM decomposition is
    unavailable.
    """

    max_subquestions = max(0, int(max_subquestions or 0))
    raw = (query).strip()
    if not raw or max_subquestions <= 0:
        return []

    out = _bounded_unique_fragments(_decomposition_fragments(raw), max_items=max_subquestions)
    if not out:
        return []

    # Avoid returning a single "decomposed" fragment that is identical to input.
    if len(out) == 1 and out[0] == " ".join(raw.split()):
        return []

    return out


def _truncate_with_ellipsis(text: str, *, max_chars: int) -> str:
    return (text[:max_chars] + "...") if max_chars and len(text) > max_chars else text


def _query_terms(query: str, *, max_terms: int) -> list[str]:
    terms: list[str] = []
    for match in _QUERY_TOKEN_RE.finditer(query):
        token = (match.group(0)).strip()
        if not token:
            continue
        normalized = token.casefold() if token.isascii() else token
        if normalized in terms:
            continue
        terms.append(normalized)
        if max_terms and len(terms) >= max_terms:
            break
    return terms


def _evidence_sentences(text: str, *, min_sentence_chars: int) -> list[str]:
    sentences: list[str] = []
    for match in _SENTENCE_RE.finditer(text):
        sentence = (match.group(0)).strip()
        if not sentence:
            continue
        if min_sentence_chars and len(sentence) < min_sentence_chars:
            continue
        sentences.append(sentence)
    return sentences


def _term_matches_sentence(term: str, sentence: str, folded_sentence: str) -> bool:
    return term.casefold() in folded_sentence if term.isascii() else term in sentence


def _sentence_relevance_score(sentence: str, terms: list[str]) -> int:
    folded = sentence.casefold()
    return sum(1 for term in terms if term and _term_matches_sentence(str(term), sentence, folded))


def _pick_evidence_sentences(sentences: list[str], *, terms: list[str], max_sentences: int) -> list[str]:
    ranked: list[tuple[int, int, int]] = []
    for idx, sentence in enumerate(sentences):
        score = _sentence_relevance_score(sentence, terms)
        if score > 0:
            ranked.append((score, len(sentence), idx))
    if not ranked:
        return sentences[:max_sentences]
    ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
    picked_idx = sorted([idx for _, _, idx in ranked[:max_sentences]])
    return [sentences[index] for index in picked_idx]


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
    raw = (text).strip()
    if not raw:
        return ""

    max_chars = max(0, int(max_chars or 0))
    max_sentences = max(0, int(max_sentences or 0))
    min_sentence_chars = max(0, int(min_sentence_chars or 0))
    max_terms = max(0, int(max_terms or 0))

    if max_chars and len(raw) <= max_chars:
        return raw
    if max_sentences <= 0:
        return _truncate_with_ellipsis(raw, max_chars=max_chars)

    q = (query).strip()
    if not q:
        return _truncate_with_ellipsis(raw, max_chars=max_chars)

    terms = _query_terms(q, max_terms=max_terms)
    if not terms:
        return _truncate_with_ellipsis(raw, max_chars=max_chars)

    sentences = _evidence_sentences(raw, min_sentence_chars=min_sentence_chars)
    if not sentences:
        return _truncate_with_ellipsis(raw, max_chars=max_chars)

    picked = _pick_evidence_sentences(sentences, terms=terms, max_sentences=max_sentences)
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
    q = (query).strip()
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
    q = (query).strip()
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
    q = (question).strip()
    if not q:
        return False
    short_len = max(1, int(short_len or 0))
    if len(q) <= short_len:
        return True
    return any(trigger in q for trigger in _QUERY_REWRITE_TRIGGER_SUBSTRINGS)


def _parse_claim_list_item(raw: str) -> str | None:
    text = (raw).lstrip()
    if not text:
        return None

    if text[0] in ("-", "*", "•"):
        return _parse_bullet_claim(text)

    marker_index = _numbered_claim_marker_index(text)
    if marker_index is None:
        return None
    return _claim_after_numbered_marker(text, marker_index)


def _parse_bullet_claim(text: str) -> str | None:
    if len(text) < 2 or not text[1].isspace():
        return None
    return text[1:].strip() or None


def _numbered_claim_marker_index(text: str) -> int | None:
    index = 0
    while index < len(text) and text[index].isdigit():
        index += 1
    while index < len(text) and text[index].isspace():
        index += 1
    if index <= 0 or index >= len(text) or text[index] not in (".", ")"):
        return None
    return index


def _claim_after_numbered_marker(text: str, marker_index: int) -> str | None:
    content_index = marker_index + 1
    if content_index >= len(text) or not text[content_index].isspace():
        return None
    return text[content_index:].strip() or None


def _flush_claim_paragraph(paragraph_lines: list[str], claims: list[str], *, max_claims: int) -> bool:
    if not paragraph_lines:
        return False
    paragraph = " ".join([line.strip() for line in paragraph_lines if line.strip()]).strip()
    paragraph_lines.clear()
    if not paragraph:
        return False
    for match in _SENTENCE_RE.finditer(paragraph):
        sentence = (match.group(0)).strip()
        if not sentence:
            continue
        claims.append(sentence)
        if len(claims) >= max_claims:
            return True
    return False


def split_into_claims(text: str, *, max_claims: int = 24) -> list[str]:
    """
    Split assistant answers into simple atomic claims for post-processing.

    Heuristics:
    - Sentence-level splitting for paragraphs
    - Markdown list items become individual claims
    - Preserve original order, drop empty claims, bound to `max_claims`
    """
    max_claims = max(1, int(max_claims or 0))
    raw = (text).strip()
    if not raw:
        return []

    claims: list[str] = []
    paragraph_lines: list[str] = []

    for raw_line in (text).splitlines():
        if _consume_claim_line(raw_line, paragraph_lines=paragraph_lines, claims=claims, max_claims=max_claims):
            break

    if len(claims) < max_claims:
        _flush_claim_paragraph(paragraph_lines, claims, max_claims=max_claims)

    return [c for c in claims if c.strip()][:max_claims]


def _consume_claim_line(
    raw_line: str,
    *,
    paragraph_lines: list[str],
    claims: list[str],
    max_claims: int,
) -> bool:
    line = (raw_line).strip()
    if not line:
        return _flush_claim_paragraph(paragraph_lines, claims, max_claims=max_claims)

    item = _parse_claim_list_item(raw_line)
    if item:
        return _append_claim_list_item(item, paragraph_lines=paragraph_lines, claims=claims, max_claims=max_claims)

    paragraph_lines.append(line)
    return False


def _append_claim_list_item(
    item: str,
    *,
    paragraph_lines: list[str],
    claims: list[str],
    max_claims: int,
) -> bool:
    if _flush_claim_paragraph(paragraph_lines, claims, max_claims=max_claims):
        return True
    claims.append(item)
    return len(claims) >= max_claims


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
) -> ClaimVerificationResult:
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
        "reason_code": nli_result.diagnostics["reason_code"],
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


def _visible_evidence_skip_keys() -> set[str]:
    return {
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


class _VisibleEvidenceMeta(TypedDict):
    strings_scrubbed: int
    strings_changed: int
    claims_total: int
    claims_removed: int
    claim_check_removed_reasons: list[dict[str, Any]]
    max_claims: int
    max_depth: int
    max_items: int
    visited_items: NotRequired[int]
    claims_remaining: NotRequired[int]


class _VisibleEvidenceState(TypedDict):
    evidence_text: str
    max_items: int
    meta: _VisibleEvidenceMeta
    nli_model_name: str | None
    nli_provider: str | None
    nli_timeout_sec: float | None
    remaining_claims: int
    skip_keys: set[str]
    use_nli_fallback: bool
    verifier_enable_contradiction_check: bool
    verifier_mode: str
    visited_items: int


def _visible_evidence_meta(*, max_claims: int, max_depth: int, max_items: int) -> _VisibleEvidenceMeta:
    return {
        "strings_scrubbed": 0,
        "strings_changed": 0,
        "claims_total": 0,
        "claims_removed": 0,
        "claim_check_removed_reasons": [],
        "max_claims": max_claims,
        "max_depth": max_depth,
        "max_items": max_items,
    }


def _append_removed_claim_reason(
    meta: _VisibleEvidenceMeta, claim: str, verification_result: ClaimVerificationResult
) -> None:
    reasons = meta["claim_check_removed_reasons"]
    if len(reasons) >= 64:
        return
    diagnostics = verification_result.diagnostics
    contradiction = diagnostics.get("contradiction_type")
    reasons.append(
        {
            "claim": claim[:300],
            "reason_code": str(diagnostics.get("reason_code") or diagnostics.get("reason") or "unsupported")[:120],
            "contradiction_type": str(contradiction)[:120] if contradiction is not None else None,
        }
    )


def _scrub_visible_evidence_string(
    raw: str,
    *,
    evidence_text: str,
    remaining_claims: int,
    meta: _VisibleEvidenceMeta,
    verifier_mode: str,
    verifier_enable_contradiction_check: bool,
    use_nli_fallback: bool,
    nli_provider: str | None,
    nli_model_name: str | None,
    nli_timeout_sec: float | None,
) -> tuple[str, int]:
    text = raw
    if not text.strip() or remaining_claims <= 0:
        return text, 0

    claims = split_into_claims(text, max_claims=remaining_claims)
    meta["claims_total"] += len(claims)

    kept: list[str] = []
    removed = 0
    for claim in claims:
        verification = verify_claim_with_fallback(
            claim,
            evidence_text,
            verifier_mode=verifier_mode,
            verifier_enable_contradiction_check=verifier_enable_contradiction_check,
            use_nli_fallback=bool(use_nli_fallback),
            nli_provider=nli_provider,
            nli_model_name=nli_model_name,
            nli_timeout_sec=nli_timeout_sec,
        )
        if bool(verification.supported):
            kept.append(claim)
            continue
        removed += 1
        _append_removed_claim_reason(meta, claim, verification)
    if removed:
        meta["claims_removed"] += removed
    return "\n".join(kept).strip(), len(claims)


def _walk_visible_evidence_dict(obj: dict[Any, Any], state: _VisibleEvidenceState, *, depth: int) -> dict[Any, Any]:
    skip_keys = state["skip_keys"]
    out: dict[Any, Any] = {}
    for key, value in obj.items():
        key_str = str(key)
        out[key] = value if key_str in skip_keys else _walk_visible_evidence(value, state, depth=depth - 1)
    return out


def _walk_visible_evidence_list(obj: list[Any], state: _VisibleEvidenceState, *, depth: int) -> list[Any]:
    out: list[Any] = []
    for item in obj:
        value = _walk_visible_evidence(item, state, depth=depth - 1)
        if isinstance(value, str) and not value.strip():
            continue
        out.append(value)
    return out


def _walk_visible_evidence(obj: Any, state: _VisibleEvidenceState, *, depth: int) -> Any:
    if state["visited_items"] >= state["max_items"]:
        return obj
    state["visited_items"] += 1

    if depth <= 0:
        return obj
    if isinstance(obj, dict):
        return _walk_visible_evidence_dict(obj, state, depth=depth)
    if isinstance(obj, list):
        return _walk_visible_evidence_list(obj, state, depth=depth)
    if not isinstance(obj, str):
        return obj

    meta = state["meta"]
    meta["strings_scrubbed"] += 1
    cleaned, consumed = _scrub_visible_evidence_string(
        obj,
        evidence_text=state["evidence_text"],
        remaining_claims=state["remaining_claims"],
        meta=meta,
        verifier_mode=state["verifier_mode"],
        verifier_enable_contradiction_check=state["verifier_enable_contradiction_check"],
        use_nli_fallback=state["use_nli_fallback"],
        nli_provider=state["nli_provider"],
        nli_model_name=state["nli_model_name"],
        nli_timeout_sec=state["nli_timeout_sec"],
    )
    state["remaining_claims"] -= consumed
    if cleaned != obj:
        meta["strings_changed"] += 1
    return cleaned


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
) -> tuple[Any, _VisibleEvidenceMeta]:
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
    meta = _visible_evidence_meta(max_claims=max_claims, max_depth=max_depth, max_items=max_items)
    state: _VisibleEvidenceState = {
        "evidence_text": evidence_text,
        "max_items": max_items,
        "meta": meta,
        "nli_model_name": nli_model_name,
        "nli_provider": nli_provider,
        "nli_timeout_sec": nli_timeout_sec,
        "remaining_claims": max_claims,
        "skip_keys": _visible_evidence_skip_keys(),
        "use_nli_fallback": bool(use_nli_fallback),
        "verifier_enable_contradiction_check": bool(verifier_enable_contradiction_check),
        "verifier_mode": verifier_mode,
        "visited_items": 0,
    }
    scrubbed = _walk_visible_evidence(data, state, depth=max_depth)
    meta["visited_items"] = state["visited_items"]
    meta["claims_remaining"] = state["remaining_claims"]
    return scrubbed, meta


def _abstain_followup_options(citations: list[dict[str, Any]] | None, *, max_options: int) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    for citation in _iter_citation_dicts(citations):
        document_id = citation.get("document_id")
        name = citation.get("document_name") or citation.get("source")
        key = str(document_id or name or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        options.append(
            {
                "document_id": str(document_id) if document_id is not None else None,
                "document_name": str(name) if name is not None else None,
            }
        )
        if max_options and len(options) >= max_options:
            break
    return options


def _iter_citation_dicts(citations: list[dict[str, Any]] | None) -> Iterator[dict[str, Any]]:
    for citation in (citations or []) if isinstance(citations, list) else []:
        if isinstance(citation, dict):
            yield citation


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
    options = _abstain_followup_options(citations, max_options=max_options)
    r = str(reason or "").strip()
    if r == "citations_lt_min":
        return {
            "type": "refine_query",
            "question": (
                "No sufficient evidence was retrieved. Please refine the question or provide more relevant documents."
            ),
            "options": [],
        }
    if r == "out_of_scope":
        return {
            "type": "refine_query",
            "question": (
                "This question appears to be outside the current knowledge base. Please add relevant "
                "materials or narrow the scope."
            ),
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


def _followup_questions_from_options(raw_options: Any, *, limit: int) -> list[str]:
    followups: list[str] = []
    seen: set[str] = set()
    if not isinstance(raw_options, list):
        return followups
    for option in raw_options:
        if not isinstance(option, dict):
            continue
        label = str(option.get("document_name") or option.get("document_id") or "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
        followups.append(f'Ask specifically about "{label}".')
        if limit and len(followups) >= limit:
            break
    return followups


def derive_followup_questions(
    abstain_followup: dict[str, Any] | None,
    *,
    max_questions: int = 3,
) -> list[str]:
    """Derive deterministic user-facing follow-up questions from abstain metadata."""
    if not isinstance(abstain_followup, dict):
        return []

    limit = max(0, int(max_questions or 0))
    question = str(abstain_followup.get("question") or "").strip()
    followups = _followup_questions_from_options(abstain_followup.get("options"), limit=limit)
    if followups:
        return followups

    return [question] if question else []


def _extract_followup_tags(raw: str, *, max_items: int) -> tuple[list[str], list[str], bool]:
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
        question = " ".join(raw[start + len(open_tag) : end].split())
        key = question.casefold()
        if question and key not in seen and (not limit or len(questions) < limit):
            seen.add(key)
            questions.append(question)
        cursor = end + len(close_tag)

    return cleaned_parts, questions, found_tag


def _normalize_followup_body(cleaned_parts: list[str]) -> str:
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
    return "\n".join(normalized_lines).strip()


def extract_followup_questions_from_answer(
    answer: str | None,
    *,
    max_items: int = 3,
) -> tuple[str, list[str]]:
    """Extract repeated <followup> tags from an answer and return clean body + questions."""
    raw = str(answer or "")
    cleaned_parts, questions, found_tag = _extract_followup_tags(raw, max_items=max_items)
    if not found_tag:
        return raw, []

    return _normalize_followup_body(cleaned_parts), questions
