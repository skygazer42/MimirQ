"""
Deterministic (no-LLM) hardcase generation for KG search diagnostics.

This is used by `/evaluations/kg/search/diagnostics` when `hardcase_mode=deterministic`.
The caller is responsible for sourcing KG-derived candidates (aliases/skills/tags).

Design goals:
- Deterministic (same inputs -> same outputs)
- Bounded (max_items, max_chars)
- Conservative (no new facts; queries are just rephrasings / alias pressure)
"""


import re
from collections.abc import Iterable, Sequence
from typing import Any

from app.rag.evaluation.kg_hardcase_generator import Hardcase
from app.rag.kg.extraction.alias import is_abbrev_token

_WS_RE = re.compile(r"\s+")


def _collapse_ws(text: Any) -> str:
    return _WS_RE.sub(" ", str(text or "").strip())


def _contains_cjk(text: str) -> bool:
    for ch in str(text or ""):
        code = ord(ch)
        if 0x4E00 <= code <= 0x9FFF:
            return True
    return False


def _truncate(text: str, *, max_chars: int) -> str:
    lim = max(0, int(max_chars or 0))
    if lim <= 0 or len(text) <= lim:
        return text
    return text[:lim]


def _dedupe_questions(items: Iterable[Hardcase], *, max_items: int) -> list[Hardcase]:
    lim = max(0, int(max_items or 0))
    if lim <= 0:
        return []

    out: list[Hardcase] = []
    seen: set[str] = set()
    for hc in items:
        q = _collapse_ws(hc.question)
        if not q:
            continue
        key = q.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(hc)
        if len(out) >= lim:
            break
    return out


def _replace_surface(question: str, *, src: str, dst: str) -> str | None:
    """
    Best-effort surface replacement.

    Rules:
    - Prefer exact substring replacement.
    - For ASCII src, also try case-insensitive replacement.
    """
    q = str(question or "")
    s = str(src or "")
    d = str(dst or "")
    if not q or not s or not d or s == d:
        return None

    if s in q:
        return q.replace(s, d)

    if s.isascii():
        try:
            pat = re.compile(re.escape(s), flags=re.IGNORECASE)
            if pat.search(q):
                return pat.sub(d, q)
        except Exception:
            return None

    return None


def _alias_direction(a: str, b: str) -> tuple[str, str]:
    """
    Return (alias, canonical) for two surface forms.
    """
    a_s = _collapse_ws(a)
    b_s = _collapse_ws(b)
    if not a_s:
        return b_s, a_s
    if not b_s:
        return a_s, b_s

    a_abbr = is_abbrev_token(a_s)
    b_abbr = is_abbrev_token(b_s)
    if a_abbr and not b_abbr:
        return a_s, b_s
    if b_abbr and not a_abbr:
        return b_s, a_s

    # Fallback: shorter surface is treated as the alias.
    if len(a_s) <= len(b_s):
        return a_s, b_s
    return b_s, a_s


def _generate_alias_hardcases(*, question: str, alias_pairs: Sequence[tuple[str, str]], max_items: int) -> list[Hardcase]:
    lim = max(0, int(max_items or 0))
    if lim <= 0:
        return []

    q = _collapse_ws(question)
    if not q:
        return []

    is_zh = _contains_cjk(q)

    out: list[Hardcase] = []
    seen_pairs: set[str] = set()
    for a, b in alias_pairs or []:
        a_s = _collapse_ws(a)
        b_s = _collapse_ws(b)
        if not a_s or not b_s or a_s.casefold() == b_s.casefold():
            continue
        key = "|".join(sorted([a_s.casefold(), b_s.casefold()]))
        if key in seen_pairs:
            continue
        seen_pairs.add(key)

        # Prefer swapping a surface in the original question.
        swapped = _replace_surface(q, src=a_s, dst=b_s)
        if swapped:
            out.append(Hardcase(kind="knowledge_pressure", question=swapped, rationale=f"alias swap: {a_s} -> {b_s}"))
        else:
            swapped2 = _replace_surface(q, src=b_s, dst=a_s)
            if swapped2:
                out.append(Hardcase(kind="knowledge_pressure", question=swapped2, rationale=f"alias swap: {b_s} -> {a_s}"))
            else:
                alias, canon = _alias_direction(a_s, b_s)
                tmpl = f"{alias} 是什么？" if is_zh else f"What is {alias}?"
                out.append(Hardcase(kind="knowledge_pressure", question=tmpl, rationale=f"alias_of: {alias} <-> {canon}"))

        if len(out) >= lim:
            break

    return _dedupe_questions(out, max_items=lim)


def _generate_skill_hardcases(
    *,
    question: str,
    skills: Sequence[str],
    tags: Sequence[str],
    max_items: int,
) -> list[Hardcase]:
    lim = max(0, int(max_items or 0))
    if lim <= 0:
        return []

    q = _collapse_ws(question)
    if not q:
        return []

    is_zh = _contains_cjk(q)

    skill_terms = [_collapse_ws(s) for s in (skills or []) if _collapse_ws(s)]
    tag_terms = [_collapse_ws(t) for t in (tags or []) if _collapse_ws(t)]

    out: list[Hardcase] = []

    # 1) Skill name queries (highest-signal).
    for s in skill_terms:
        tmpl = f"{s} 步骤是什么？" if is_zh else f"How to {s}?"
        out.append(Hardcase(kind="knowledge_pressure", question=tmpl, rationale=f"skill: {s}"))
        if len(out) >= lim:
            return _dedupe_questions(out, max_items=lim)

    # 2) Skill + tag combos (bounded).
    if skill_terms and tag_terms:
        s0 = skill_terms[0]
        for t in tag_terms[:2]:
            tmpl = f"{t} {s0} 步骤" if is_zh else f"How to {t} {s0}?"
            out.append(Hardcase(kind="knowledge_pressure", question=tmpl, rationale=f"skill+tag: {s0} + {t}"))
            if len(out) >= lim:
                return _dedupe_questions(out, max_items=lim)

    # 3) Tag-only queries (fallback).
    for t in tag_terms:
        tmpl = f"{t} 操作步骤" if is_zh else f"{t} steps"
        out.append(Hardcase(kind="knowledge_pressure", question=tmpl, rationale=f"tag: {t}"))
        if len(out) >= lim:
            return _dedupe_questions(out, max_items=lim)

    return _dedupe_questions(out, max_items=lim)


def generate_hardcases_deterministic(
    *,
    question: str,
    alias_pairs: Sequence[tuple[str, str]] | None = None,
    skills: Sequence[str] | None = None,
    tags: Sequence[str] | None = None,
    max_items: int,
    max_chars: int = 350,
) -> list[Hardcase]:
    """
    Generate deterministic hardcases from KG-derived candidates.

    Output is ordered as:
    - alias hardcases (up to alias quota)
    - skill hardcases (up to skill quota)
    - spillover from remaining alias/skill candidates until max_items
    """
    lim = max(0, int(max_items or 0))
    if lim <= 0:
        return []

    q = _collapse_ws(question)
    if not q:
        return []

    alias_quota = lim // 2
    skill_quota = lim - alias_quota

    alias_all = _generate_alias_hardcases(question=q, alias_pairs=list(alias_pairs or []), max_items=lim)
    skill_all = _generate_skill_hardcases(question=q, skills=list(skills or []), tags=list(tags or []), max_items=lim)

    out: list[Hardcase] = []
    out.extend(alias_all[:alias_quota])
    out.extend(skill_all[:skill_quota])

    if len(out) < lim:
        out.extend(alias_all[alias_quota:])
    if len(out) < lim:
        out.extend(skill_all[skill_quota:])

    # Final sanitize: collapse ws, truncate, dedupe, clamp.
    cleaned: list[Hardcase] = []
    for hc in out:
        q2 = _truncate(_collapse_ws(hc.question), max_chars=max_chars)
        if not q2:
            continue
        cleaned.append(Hardcase(kind=hc.kind, question=q2, rationale=_collapse_ws(hc.rationale) or None))

    return _dedupe_questions(cleaned, max_items=lim)


__all__ = ["generate_hardcases_deterministic"]

