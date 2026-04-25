from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.rag.industry_rules.appliers.query_rewrite import expand_query_terms
from app.rag.industry_rules.loaders import (
    list_rulesets,
    load_ruleset,
    replace_ruleset_glossary,
    replace_ruleset_intents,
    replace_ruleset_patterns,
    ruleset_exists,
)

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)

_INDEX_SCHEMA = "mimirq.industry_rules_index.v1"
_RULESET_SCHEMA = "mimirq.industry_rules_ruleset.v1"
_PREVIEW_SCHEMA = "mimirq.industry_rules_preview.v1"
_UPDATE_SCHEMA = "mimirq.industry_rules_update.v1"


class RewritePreviewRequest(BaseModel):
    ruleset: str = Field(min_length=1)
    query: str = Field(min_length=1)


class GlossaryUpdateRequest(BaseModel):
    glossary: dict[str, list[str]] = Field(default_factory=dict)


class PatternsUpdateRequest(BaseModel):
    patterns: list[dict[str, Any]] = Field(default_factory=list)


class IntentsUpdateRequest(BaseModel):
    intents: list[dict[str, Any]] = Field(default_factory=list)


def _ruleset_summary(name: str) -> dict[str, Any]:
    ruleset = load_ruleset(name)
    return {
        "name": ruleset.name,
        "glossary_count": int(len(ruleset.glossary)),
        "pattern_count": int(len(ruleset.patterns)),
        "intent_count": int(len(ruleset.intents)),
    }


def _ruleset_detail(name: str) -> dict[str, Any]:
    ruleset = load_ruleset(name)
    return {
        "name": ruleset.name,
        "glossary_count": int(len(ruleset.glossary)),
        "pattern_count": int(len(ruleset.patterns)),
        "intent_count": int(len(ruleset.intents)),
        "glossary": dict(ruleset.glossary),
        "patterns": list(ruleset.patterns),
        "intents": list(ruleset.intents),
    }


def _require_ruleset(name: str) -> str:
    candidate = str(name or "").strip()
    if not ruleset_exists(candidate):
        raise HTTPException(status_code=404, detail=f"Unknown industry ruleset: {candidate or '<empty>'}")
    return candidate


@router.get("/rulesets", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_industry_rulesets() -> dict[str, Any]:
    names = list_rulesets()
    rows = [_ruleset_summary(name) for name in names]
    return {
        "schema": _INDEX_SCHEMA,
        "count": int(len(rows)),
        "rulesets": rows,
    }


@router.get("/rulesets/{name}", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_industry_ruleset(name: str) -> dict[str, Any]:
    candidate = _require_ruleset(name)
    return {
        "schema": _RULESET_SCHEMA,
        "ruleset": _ruleset_detail(candidate),
    }


@router.put("/rulesets/{name}/glossary", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def put_industry_ruleset_glossary(name: str, body: GlossaryUpdateRequest) -> dict[str, Any]:
    candidate = _require_ruleset(name)
    result = replace_ruleset_glossary(candidate, body.glossary)
    return {"schema": _UPDATE_SCHEMA, **result}


@router.put("/rulesets/{name}/patterns", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def put_industry_ruleset_patterns(name: str, body: PatternsUpdateRequest) -> dict[str, Any]:
    candidate = _require_ruleset(name)
    result = replace_ruleset_patterns(candidate, body.patterns)
    return {"schema": _UPDATE_SCHEMA, **result}


@router.put("/rulesets/{name}/intents", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def put_industry_ruleset_intents(name: str, body: IntentsUpdateRequest) -> dict[str, Any]:
    candidate = _require_ruleset(name)
    result = replace_ruleset_intents(candidate, body.intents)
    return {"schema": _UPDATE_SCHEMA, **result}


@router.post("/preview-rewrite", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def preview_industry_rules_rewrite(body: RewritePreviewRequest) -> dict[str, Any]:
    candidate = _require_ruleset(body.ruleset)
    ruleset = load_ruleset(candidate)
    original_query = str(body.query or "").strip()
    expanded_query = expand_query_terms(original_query, ruleset.glossary)
    return {
        "schema": _PREVIEW_SCHEMA,
        "ruleset": candidate,
        "original_query": original_query,
        "expanded_query": expanded_query,
        "changed": bool(expanded_query != original_query),
    }


__all__ = [
    "router",
    "get_industry_rulesets",
    "get_industry_ruleset",
    "put_industry_ruleset_glossary",
    "put_industry_ruleset_patterns",
    "put_industry_ruleset_intents",
    "preview_industry_rules_rewrite",
]
