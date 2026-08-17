"""
Structured memory (Gap 8): entity memory + lightweight fact memory.

Scope of this v1 implementation:
- Per-conversation structured memory extracted from each assistant turn and stored in Message.message_metadata.
- Retrieval-time injection of a compact "memory context" as a system message (opt-in).

Why Message.message_metadata:
- Avoids schema migrations for a first iteration.
- Keeps write path cheap (single JSON blob per assistant message).
- Works for both streaming and non-streaming endpoints.

Important safety notes:
- Feature-flagged and request-opt-in.
- Best-effort; failures must never break chat.
- Conservative PII filtering: we avoid storing email/URLs/long numeric strings.
"""

import re
from typing import Any

_CJK_RE = re.compile(r"[\u4e00-\u9fff]{2,16}")
_ASCII_ENTITY_RE = re.compile(r"[A-Za-z][A-Za-z0-9][A-Za-z0-9_.:+/-]{0,48}")
_VERSION_RE = re.compile(r"\bv?\d+\.\d+(?:\.\d+)?\b", flags=re.IGNORECASE)

_EMAIL_RE = re.compile(r"(?i)\b[a-z0-9._%+-]{1,64}@[a-z0-9.-]{1,64}\.[a-z]{2,24}\b")
_URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)\S+\b")
_LONG_DIGITS_RE = re.compile(r"\b\d{6,}\b")

_STOPWORDS_EN = {
    "this",
    "that",
    "with",
    "from",
    "then",
    "when",
    "where",
    "what",
    "which",
    "will",
    "should",
    "could",
    "please",
    "thanks",
}
_STOPWORDS_ZH = {
    "这个",
    "那个",
    "我们",
    "你们",
    "他们",
    "然后",
    "现在",
    "继续",
    "可以",
    "问题",
    "需求",
    "方案",
    "任务",
}


def _stable_sig(s: str) -> str:
    s = str(s or "").strip()
    return s.casefold() if s.isascii() else s


def _is_pii_like(text: str) -> bool:
    t = str(text or "")
    if not t:
        return True
    if _EMAIL_RE.search(t):
        return True
    if _URL_RE.search(t):
        return True
    if _LONG_DIGITS_RE.search(t):
        return True
    return False


def _clean_token(tok: str) -> str:
    t = str(tok or "").strip()
    # Strip common punctuation around tokens.
    return t.strip(" \t\r\n\"'“”‘’`()[]{}<>.,;:!?，。；：！？")


def _iter_raw_entity_candidates(raw: str) -> list[str]:
    candidates: list[str] = []
    candidates.extend(_VERSION_RE.findall(raw))
    candidates.extend(_ASCII_ENTITY_RE.findall(raw))
    candidates.extend(_CJK_RE.findall(raw))
    return candidates


def _normalize_entity_candidate(candidate: str) -> tuple[str, str] | None:
    tok = _clean_token(candidate)
    if not tok or len(tok) < 2 or len(tok) > 64 or _is_pii_like(tok):
        return None
    if tok.isascii():
        low = tok.casefold()
        if low in _STOPWORDS_EN or (len(low) <= 2 and low.isalpha()):
            return None
        return low, tok
    if tok in _STOPWORDS_ZH:
        return None
    return tok, tok


def _collect_entity_token_counts(raw: str) -> tuple[dict[str, int], dict[str, str]]:
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    for candidate in _iter_raw_entity_candidates(raw):
        normalized = _normalize_entity_candidate(candidate)
        if normalized is None:
            continue
        sig, tok = normalized
        counts[sig] = int(counts.get(sig, 0) or 0) + 1
        display.setdefault(sig, tok)
    return counts, display


def extract_entity_tokens(*, text: str, max_entities: int) -> list[str]:
    """
    Extract lightweight entity tokens from text (deterministic heuristic).

    This is not NER. It is a pragmatic "entity-ish token" extractor for:
    - project names (CamelCase, hyphenated, code-like ids)
    - Chinese proper nouns (2-16 CJK chars)
    - versions (v0.5.2)
    """
    max_out = max(0, int(max_entities or 0))
    if max_out <= 0:
        return []

    raw = str(text or "")
    if not raw.strip():
        return []

    counts, display = _collect_entity_token_counts(raw)
    ranked = sorted(counts.items(), key=lambda t: (-int(t[1]), _stable_sig(t[0]), t[0]))
    out: list[str] = []
    for sig, _cnt in ranked:
        out.append(display.get(sig) or sig)
        if len(out) >= max_out:
            break
    return out


def extract_fact_sentences(*, text: str, max_facts: int) -> list[str]:
    """
    Extract lightweight "fact-like" sentences.

    This is intentionally conservative: store short sentences that likely encode preferences/config.
    """
    max_out = max(0, int(max_facts or 0))
    if max_out <= 0:
        return []

    raw = str(text or "")
    if not raw.strip():
        return []

    # Split into sentences (simple heuristic).
    parts = re.split(r"[。！？!?\\n]+", raw)
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        s = str(p or "").strip()
        if not s:
            continue
        if len(s) < 10 or len(s) > 220:
            continue
        if _is_pii_like(s):
            continue

        # "fact-like" patterns
        s_fold = s.casefold()
        if not (
            ("我" in s)
            or ("我们" in s)
            or ("配置" in s)
            or ("部署" in s)
            or ("数据库" in s)
            or ("docker" in s_fold)
            or ("k8s" in s_fold)
            or ("kubernetes" in s_fold)
            or ("tag" in s_fold)
            or ("branch" in s_fold)
        ):
            continue

        sig = _stable_sig(s)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(s)
        if len(out) >= max_out:
            break
    return out


def extract_structured_memory_for_turn(
    *,
    user_text: str,
    assistant_text: str,
    max_entities: int,
    max_facts: int,
) -> dict[str, Any]:
    """
    Build a structured-memory record for persistence in Message.message_metadata.
    """
    entities = extract_entity_tokens(text=f"{user_text}\n{assistant_text}".strip(), max_entities=max_entities)
    facts = extract_fact_sentences(text=user_text, max_facts=max_facts)
    return {
        "schema": "mimirq.structured_memory.v1",
        "entities": entities,
        "facts": facts,
        "stats": {
            "entities": int(len(entities)),
            "facts": int(len(facts)),
        },
    }


def _record_memory_entity(
    *,
    entity: Any,
    ent_counts: dict[str, int],
    ent_surface: dict[str, str],
) -> None:
    tok = _clean_token(str(entity or ""))
    if not tok or _is_pii_like(tok):
        return
    sig = _stable_sig(tok)
    ent_counts[sig] = int(ent_counts.get(sig, 0) or 0) + 1
    ent_surface.setdefault(sig, tok)


def _record_memory_fact(
    *,
    fact: Any,
    facts: list[str],
    seen_fact: set[str],
) -> None:
    text = str(fact or "").strip()
    if not text or _is_pii_like(text):
        return
    sig = _stable_sig(text)
    if sig in seen_fact:
        return
    seen_fact.add(sig)
    facts.append(text)


def _collect_structured_memory_records(
    records: list[dict[str, Any]],
) -> tuple[dict[str, int], dict[str, str], list[str]]:
    ent_counts: dict[str, int] = {}
    ent_surface: dict[str, str] = {}
    facts: list[str] = []
    seen_fact: set[str] = set()

    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        if str(rec.get("schema") or "") != "mimirq.structured_memory.v1":
            continue
        ents = rec.get("entities")
        if isinstance(ents, list):
            for entity in ents:
                _record_memory_entity(
                    entity=entity,
                    ent_counts=ent_counts,
                    ent_surface=ent_surface,
                )
        raw_facts = rec.get("facts")
        if isinstance(raw_facts, list):
            for fact in raw_facts:
                _record_memory_fact(
                    fact=fact,
                    facts=facts,
                    seen_fact=seen_fact,
                )
    return ent_counts, ent_surface, facts


def _render_structured_memory_context(*, entities: list[str], facts: list[str]) -> str:
    parts: list[str] = []
    if entities:
        parts.append("Entities mentioned recently:")
        parts.extend(f"- {entity}" for entity in entities)
    if facts:
        if parts:
            parts.append("")
        parts.append("Facts/preferences (user-provided):")
        parts.extend(f"- {fact}" for fact in facts)
    if not parts:
        return ""
    return "[Structured Memory]\n" + "\n".join(parts).strip()


def build_structured_memory_context(
    *,
    records: list[dict[str, Any]],
    max_entities: int,
    max_facts: int,
    max_chars: int,
) -> str:
    """
    Build an injection-friendly context string from stored structured-memory records.
    """
    max_e = max(0, int(max_entities or 0))
    max_f = max(0, int(max_facts or 0))
    max_c = max(0, int(max_chars or 0))

    ent_counts, ent_surface, facts = _collect_structured_memory_records(records)

    ranked_entities = sorted(ent_counts.items(), key=lambda t: (-int(t[1]), _stable_sig(t[0]), t[0]))
    entities_out = [(ent_surface.get(sig) or sig) for sig, _cnt in ranked_entities][:max_e]
    facts_out = facts[:max_f]

    text = _render_structured_memory_context(entities=entities_out, facts=facts_out)
    if max_c and len(text) > max_c:
        text = text[:max_c].rstrip() + "..."
    return text


__all__ = [
    "build_structured_memory_context",
    "extract_entity_tokens",
    "extract_fact_sentences",
    "extract_structured_memory_for_turn",
]
