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

    # Very conservative skip when obvious PII is present.
    if _EMAIL_RE.search(raw) or _URL_RE.search(raw):
        # We still allow extracting non-PII entities from the text, but we filter tokens aggressively below.
        pass

    candidates: list[str] = []
    candidates.extend(_VERSION_RE.findall(raw))
    candidates.extend(_ASCII_ENTITY_RE.findall(raw))
    candidates.extend(_CJK_RE.findall(raw))

    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    for c in candidates:
        tok = _clean_token(c)
        if not tok:
            continue
        if len(tok) < 2 or len(tok) > 64:
            continue
        if _is_pii_like(tok):
            continue
        if tok.isascii():
            low = tok.casefold()
            if low in _STOPWORDS_EN:
                continue
            # Drop common 1-2 letter noise.
            if len(low) <= 2 and low.isalpha():
                continue
            sig = low
        else:
            if tok in _STOPWORDS_ZH:
                continue
            sig = tok

        counts[sig] = int(counts.get(sig, 0) or 0) + 1
        # Preserve a representative surface form.
        display.setdefault(sig, tok)

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
            for e in ents:
                tok = _clean_token(str(e or ""))
                if not tok:
                    continue
                if _is_pii_like(tok):
                    continue
                sig = _stable_sig(tok)
                ent_counts[sig] = int(ent_counts.get(sig, 0) or 0) + 1
                ent_surface.setdefault(sig, tok)

        fs = rec.get("facts")
        if isinstance(fs, list):
            for f in fs:
                s = str(f or "").strip()
                if not s or _is_pii_like(s):
                    continue
                sig = _stable_sig(s)
                if sig in seen_fact:
                    continue
                seen_fact.add(sig)
                facts.append(s)

    ranked_entities = sorted(ent_counts.items(), key=lambda t: (-int(t[1]), _stable_sig(t[0]), t[0]))
    entities_out = [(ent_surface.get(sig) or sig) for sig, _cnt in ranked_entities][:max_e]
    facts_out = facts[:max_f]

    parts: list[str] = []
    if entities_out:
        parts.append("Entities mentioned recently:")
        parts.extend([f"- {e}" for e in entities_out])
    if facts_out:
        if parts:
            parts.append("")
        parts.append("Facts/preferences (user-provided):")
        parts.extend([f"- {f}" for f in facts_out])

    if not parts:
        return ""

    text = "[Structured Memory]\n" + "\n".join(parts).strip()
    if max_c and len(text) > max_c:
        text = text[:max_c].rstrip() + "..."
    return text


__all__ = [
    "build_structured_memory_context",
    "extract_entity_tokens",
    "extract_fact_sentences",
    "extract_structured_memory_for_turn",
]
