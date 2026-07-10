"""
Versioned query rewrite strategies (PII-safe).

Why:
- Query rewrite is LLM-backed and prompt-tuned, so we need a stable, versioned identifier
  for evaluation gating and rollback.
- Downstream traces/config fingerprints MUST NOT embed raw prompt text.

This module exposes:
- a low-cardinality strategy_id (e.g. "kb_followup.v1")
- a stable strategy_hash derived from the strategy definition (prompt template, etc)
"""


import json
from functools import lru_cache

from app.rag.core.hashing import stable_hash

QUERY_REWRITE_STRATEGY_SPEC_SCHEMA_V1 = "mimirq.query_rewrite_strategy_spec.v1"

# Keep this low-cardinality; used as the fallback when config is missing/invalid.
DEFAULT_QUERY_REWRITE_STRATEGY_ID = "kb_followup.v1"


_KB_FOLLOWUP_V1_TEMPLATE = """You are a knowledge base retrieval assistant. Please rewrite the "Current Question" into a standalone, clear, retrieval-friendly query.
Requirements:
1) Resolve pronouns by incorporating conversation history (e.g., "it/this/mentioned above")
2) Retain key entities, time references, scope, and constraints
3) Only output the rewritten query, no explanations

[Conversation History]
{history}

[Current Question]
{question}

[Rewritten Retrieval Query]"""

_KB_FOLLOWUP_V2_TEMPLATE = """You are a knowledge base retrieval assistant. Rewrite the "Current Question" into a standalone, retrieval-friendly query.
Requirements:
1) Resolve pronouns and missing context using the conversation history
2) Keep key entities, time references, scope, and constraints
3) Do NOT add new facts or assumptions
4) Output the rewritten query only (no explanations, no quotes)

[Conversation History]
{history}

[Current Question]
{question}

[Rewritten Retrieval Query]"""


# Strategy registry: id -> template string (no side effects; safe to hash).
_STRATEGY_TEMPLATES: dict[str, str] = {
    "kb_followup.v1": _KB_FOLLOWUP_V1_TEMPLATE,
    "kb_followup.v2": _KB_FOLLOWUP_V2_TEMPLATE,
}


def _normalize_strategy_id(raw: str | None) -> str:
    sid = str(raw or "").strip()
    return sid


def resolve_query_rewrite_strategy_id(raw: str | None) -> str:
    """
    Resolve the configured strategy id to a known/registered identifier.

    Unknown ids fall back to DEFAULT_QUERY_REWRITE_STRATEGY_ID (safe behavior).
    """
    sid = _normalize_strategy_id(raw)
    if not sid:
        return DEFAULT_QUERY_REWRITE_STRATEGY_ID
    if sid in _STRATEGY_TEMPLATES:
        return sid
    return DEFAULT_QUERY_REWRITE_STRATEGY_ID


def get_query_rewrite_prompt_template(strategy_id: str | None) -> str:
    """
    Return the prompt template string for the resolved strategy id.

    The prompt is NOT meant to be persisted in traces; use build_query_rewrite_strategy_spec()
    when you need a PII-safe identifier.
    """
    sid = resolve_query_rewrite_strategy_id(strategy_id)
    return _STRATEGY_TEMPLATES.get(sid, _STRATEGY_TEMPLATES[DEFAULT_QUERY_REWRITE_STRATEGY_ID])


@lru_cache(maxsize=32)
def _strategy_hash_for_id(strategy_id: str) -> str:
    """
    Compute a stable hash for a strategy id + its definition.

    This is intentionally derived from the prompt template to ensure changes are measurable
    even if a human forgets to bump the strategy id.
    """
    tmpl = get_query_rewrite_prompt_template(strategy_id)
    payload = json.dumps(
        {"strategy_id": str(strategy_id), "template": str(tmpl)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return stable_hash(payload, length=16)


def build_query_rewrite_strategy_spec(strategy_id: str | None) -> dict[str, str]:
    """
    Build a PII-safe spec object for traces/fingerprints.

    Returns:
      {"schema": "...", "strategy_id": "...", "strategy_hash": "..."}
    """
    sid = resolve_query_rewrite_strategy_id(strategy_id)
    return {
        "schema": QUERY_REWRITE_STRATEGY_SPEC_SCHEMA_V1,
        "strategy_id": sid,
        "strategy_hash": _strategy_hash_for_id(sid),
    }


__all__ = [
    "DEFAULT_QUERY_REWRITE_STRATEGY_ID",
    "QUERY_REWRITE_STRATEGY_SPEC_SCHEMA_V1",
    "build_query_rewrite_strategy_spec",
    "get_query_rewrite_prompt_template",
    "resolve_query_rewrite_strategy_id",
]

