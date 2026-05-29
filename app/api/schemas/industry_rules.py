"""
Industry rules API schemas.

These mirror the response payloads of :mod:`app.api.v1.industry_rules` so the
endpoints can declare ``response_model`` and the frontend can consume generated
types instead of hand-written ones.

Note: the runtime payloads use a ``schema`` key (a versioned schema marker).
Because ``schema`` shadows a Pydantic ``BaseModel`` attribute, the field is named
``schema_`` with ``alias="schema"``; FastAPI serializes responses by alias so the
wire format stays ``schema``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class IndustryRulesetSummary(BaseModel):
    """Lightweight ruleset descriptor with section counts only."""

    name: str = Field(..., description="Ruleset identifier (tenant-scoped slug).")
    glossary_count: int = Field(..., description="Number of glossary term-mapping entries.")
    pattern_count: int = Field(..., description="Number of question-pattern entries.")
    intent_count: int = Field(..., description="Number of intent-classifier entries.")


class IndustryRulesetDetail(IndustryRulesetSummary):
    """Full ruleset payload including glossary / patterns / intents bodies."""

    glossary: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Term-mapping table: canonical term -> list of synonyms/variants.",
    )
    patterns: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Question-pattern rules (free-form objects, schema per ruleset).",
    )
    intents: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Intent-classifier rules (free-form objects, schema per ruleset).",
    )


class IndustryRulesetListResponse(BaseModel):
    """Response of GET /industry-rules/rulesets."""

    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(alias="schema", description="Versioned payload schema marker.")
    count: int = Field(..., description="Number of rulesets returned.")
    rulesets: list[IndustryRulesetSummary] = Field(default_factory=list)


class IndustryRulesetDetailResponse(BaseModel):
    """Response of GET /industry-rules/rulesets/{name}."""

    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(alias="schema", description="Versioned payload schema marker.")
    ruleset: IndustryRulesetDetail


class IndustryRulesUpdateResponse(BaseModel):
    """Response of the PUT glossary/patterns/intents endpoints."""

    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(alias="schema", description="Versioned payload schema marker.")
    ruleset: str = Field(..., description="Ruleset that was updated.")
    section: str = Field(..., description="Updated section: glossary | patterns | intents.")
    updated_count: int = Field(..., description="Number of entries written.")


class IndustryRulesRewritePreviewResponse(BaseModel):
    """Response of POST /industry-rules/preview-rewrite."""

    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(alias="schema", description="Versioned payload schema marker.")
    ruleset: str = Field(..., description="Ruleset used for the rewrite.")
    original_query: str = Field(..., description="Original user query.")
    expanded_query: str = Field(..., description="Query after glossary term expansion.")
    changed: bool = Field(..., description="Whether expansion changed the query.")


# --- Request payloads (moved here so the whole contract lives in one module) ---


class IndustryRulesRewritePreviewRequest(BaseModel):
    ruleset: str = Field(..., min_length=1, description="Ruleset to preview against.")
    query: str = Field(..., min_length=1, description="User query to expand.")


class IndustryRulesGlossaryUpdateRequest(BaseModel):
    glossary: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Full replacement glossary: canonical term -> synonyms/variants.",
    )


class IndustryRulesPatternsUpdateRequest(BaseModel):
    patterns: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Full replacement question-pattern list.",
    )


class IndustryRulesIntentsUpdateRequest(BaseModel):
    intents: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Full replacement intent-classifier list.",
    )


__all__ = [
    "IndustryRulesetSummary",
    "IndustryRulesetDetail",
    "IndustryRulesetListResponse",
    "IndustryRulesetDetailResponse",
    "IndustryRulesUpdateResponse",
    "IndustryRulesRewritePreviewResponse",
    "IndustryRulesRewritePreviewRequest",
    "IndustryRulesGlossaryUpdateRequest",
    "IndustryRulesPatternsUpdateRequest",
    "IndustryRulesIntentsUpdateRequest",
]
