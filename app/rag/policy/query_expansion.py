"""
Deterministic query expansion for policy/manual clause references.

This is a "fast lane" meant to improve recall when users mention clause numbers
directly (e.g. "第十二条", "Section 3.2.1").

Constraints:
- No LLM calls
- Bounded output
- Deterministic and safe for logs/storage
"""

from __future__ import annotations

from app.rag.policy.clause_refs import extract_clause_refs


def build_clause_fastlane_queries(query: str, *, max_refs: int = 4) -> list[str]:
    raw = (query or "").strip()
    if not raw:
        return []

    refs = extract_clause_refs(raw)
    if not refs:
        return []

    out: list[str] = []
    for ref in refs:
        v = (ref or "").strip()
        if not v:
            continue
        out.append(v)
        if len(out) >= max_refs:
            break
    return out

