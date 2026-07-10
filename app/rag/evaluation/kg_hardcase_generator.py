"""
LLM hardcase generation for KG search diagnostics.

We generate two kinds of "hard" queries from baseline failures:
- knowledge_pressure: term/alias/ontology pressure (same evidence, harder phrasing)
- reasoning_pressure: multi-step constraints (still answerable by same evidence)

This module is designed to be unit-testable with a mocked LLM client.
"""


import re
from dataclasses import dataclass
from typing import Any, Literal

from app.rag.llm.models import LLMMessage, LLMRole

HardcaseKind = Literal["knowledge_pressure", "reasoning_pressure"]


@dataclass(frozen=True)
class Hardcase:
    kind: HardcaseKind
    question: str
    rationale: str | None = None


_WS_RE = re.compile(r"\s+")


def _collapse_ws(text: Any) -> str:
    return _WS_RE.sub(" ", str(text or "").strip())


def _normalize_kind(value: Any) -> HardcaseKind | None:
    s = str(value or "").strip().casefold()
    if s == "knowledge_pressure":
        return "knowledge_pressure"
    if s == "reasoning_pressure":
        return "reasoning_pressure"
    return None


def sanitize_hardcases(raw: Any, *, max_items: int, max_chars: int) -> list[Hardcase]:
    """
    Coerce + sanitize hardcases from an LLM result (or any loosely-shaped object).

    Rules:
    - Drop invalid kinds.
    - Drop empty questions.
    - Truncate question length.
    - Dedupe by normalized question (casefold + collapsed whitespace).
    - Preserve order and clamp to max_items.
    - If `raw` has the `{"raw": ...}` fallback shape (parse error), return [].
    """
    lim = max(0, int(max_items or 0))
    if lim <= 0:
        return []

    max_chars_i = max(20, int(max_chars or 0))

    if not raw:
        return []

    if isinstance(raw, dict) and "raw" in raw and "hardcases" not in raw:
        return []

    items = None
    if isinstance(raw, dict):
        items = raw.get("hardcases")

    if not isinstance(items, list) or not items:
        return []

    out: list[Hardcase] = []
    seen: set[str] = set()

    for item in items:
        if not isinstance(item, dict):
            continue

        kind = _normalize_kind(item.get("kind"))
        if kind is None:
            continue

        q = _collapse_ws(item.get("question"))
        if not q:
            continue

        if len(q) > max_chars_i:
            q = q[:max_chars_i]

        key = q.casefold()
        if key in seen:
            continue
        seen.add(key)

        rationale = _collapse_ws(item.get("rationale")) or None
        out.append(Hardcase(kind=kind, question=q, rationale=rationale))
        if len(out) >= lim:
            break

    return out


async def generate_hardcases_llm(
    *,
    llm_client: Any,
    question: str,
    evidence_snippets: list[str],
    entity_hints: list[str] | None = None,
    max_items: int,
    temperature: float,
) -> list[Hardcase]:
    """
    Generate hardcases via an LLM client compatible with `chat_with_schema(...)`.

    `llm_client` is intentionally typed as Any to keep this module import-light
    (it can be backed by `BaseLLMClient` or a unit-test fake).
    """
    q = _collapse_ws(question)
    if not q:
        return []

    lim = max(0, int(max_items or 0))
    if lim <= 0:
        return []

    hints = [h for h in (entity_hints or []) if _collapse_ws(h)]
    hints = hints[:12]

    ev_snips = [_collapse_ws(s) for s in (evidence_snippets or []) if _collapse_ws(s)]
    # Keep prompt bounded.
    ev_snips = [s[:800] for s in ev_snips][:2]

    schema = {
        "type": "object",
        "properties": {
            "hardcases": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string"},
                        "question": {"type": "string"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["kind", "question"],
                },
            }
        },
    }

    kind_split = max(1, lim // 2)
    prompt = (
        "You generate hard evaluation queries for a Knowledge Graph (KG) search system.\n"
        "The goal is to create queries that are strictly answerable using the SAME evidence snippets.\n"
        "\n"
        f"Original question:\n{q}\n\n"
        "Evidence snippets (ground truth):\n"
        + "\n".join([f"- {s}" for s in ev_snips])
        + "\n\n"
        + ("Entity hints (may help with terminology/aliases):\n" + ", ".join(hints) + "\n\n" if hints else "")
        + "Generate hardcases with two kinds:\n"
        "- knowledge_pressure: harder terminology / alias / ontology pressure, but same answerability\n"
        "- reasoning_pressure: multi-step constraints/comparisons, but same answerability\n"
        "\n"
        f"Constraints:\n- Return JSON only.\n- Generate at most {lim} total hardcases.\n"
        f"- Target about {kind_split} knowledge_pressure and {lim - kind_split} reasoning_pressure.\n"
        "- Do NOT introduce facts not present in the evidence snippets.\n"
        "- Keep each hardcase question concise.\n"
    )

    messages = [LLMMessage(role=LLMRole.USER, content=prompt)]

    try:
        result = await llm_client.chat_with_schema(
            messages,
            response_schema=schema,
            temperature=float(temperature),
        )
    except Exception:
        # Fail-open: diagnostics still useful without hardcases.
        return []

    # Keep hardcase questions bounded for API consumers.
    return sanitize_hardcases(result, max_items=lim, max_chars=350)


__all__ = ["Hardcase", "HardcaseKind", "generate_hardcases_llm", "sanitize_hardcases"]
