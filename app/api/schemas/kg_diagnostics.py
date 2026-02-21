"""
KG (Knowledge Graph) diagnostics evaluation schemas.

This is intentionally DB-light (no new tables): the endpoint returns an on-demand
diagnostic report used to iteratively improve KG extraction/search quality for RAG.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

HardcaseMode = Literal["off", "deterministic", "llm"]
HardcaseKind = Literal["knowledge_pressure", "reasoning_pressure"]


class KGSearchDiagnosticsRequest(BaseModel):
    dataset_id: UUID
    case_ids: List[UUID] = Field(default_factory=list, description="Optional explicit case id list (else select by dataset)")
    max_cases: int = Field(default=50, ge=1, le=200, description="Max cases to evaluate (default: 50)")

    k: int = Field(default=10, ge=1, le=50, description="Hit@K and evaluation cutoff (default: 10)")

    auto_extract_kg: bool = Field(default=True, description="If true, ensure evidence documents have KG extracted")
    extract_skills: Optional[bool] = Field(default=None, description="Override KG skill extraction toggle")
    extract_relations: Optional[bool] = Field(default=None, description="Override KG relation extraction toggle")

    hardcase_mode: HardcaseMode = Field(default="llm", description="Hardcase generation strategy")
    hardcases_per_failed_case: int = Field(default=4, ge=0, le=20)
    max_failed_cases_for_hardcase: int = Field(default=20, ge=0, le=200)

    llm_temperature: float = Field(default=0.2, ge=0.0, le=2.0, description="Hardcase LLM temperature")


class KGSearchEventOut(BaseModel):
    id: str
    title: str = ""
    summary: str = ""
    content: str = ""
    document_id: Optional[str] = None
    chunk_id: Optional[str] = None
    score: float = 0.0


class KGSearchEntityOut(BaseModel):
    entity_id: str
    name: str = ""
    type: str = "unknown"
    weight: float = 0.0


class KGSearchRunMetrics(BaseModel):
    hit_at_k: bool = False
    mrr: float = 0.0
    recall: float = 0.0
    matched_evidence_chunks: int = 0
    total_evidence_chunks: int = 0
    k: int = 10


class KGSearchRunResult(BaseModel):
    query: str
    events: List[KGSearchEventOut] = Field(default_factory=list)
    entities: List[KGSearchEntityOut] = Field(default_factory=list)
    clues: List[Dict[str, Any]] = Field(default_factory=list)
    stats: Dict[str, Any] = Field(default_factory=dict)
    metrics: KGSearchRunMetrics = Field(default_factory=KGSearchRunMetrics)
    error: Optional[str] = None


class KGHardcaseOut(BaseModel):
    kind: HardcaseKind
    question: str
    rationale: Optional[str] = None
    run: Optional[KGSearchRunResult] = None


class KGEvalAttribution(BaseModel):
    primary_cause: str = "other"
    signals: Dict[str, Any] = Field(default_factory=dict)


class KGSearchDiagnosticsItem(BaseModel):
    case_id: UUID
    question: str
    tags: List[str] = Field(default_factory=list)

    evidence_chunk_ids: List[str] = Field(default_factory=list)
    ground_truth_event_ids: List[str] = Field(default_factory=list)

    baseline: KGSearchRunResult
    hardcases: List[KGHardcaseOut] = Field(default_factory=list)
    attribution: KGEvalAttribution = Field(default_factory=KGEvalAttribution)


class KGSearchDiagnosticsSummary(BaseModel):
    dataset_id: UUID
    cases_total: int = 0
    cases_evaluated: int = 0
    hardcases_generated: int = 0

    baseline_hit_rate: float = 0.0
    baseline_mrr: float = 0.0
    baseline_recall: float = 0.0

    hardcase_hit_rate: Optional[float] = None
    hardcase_mrr: Optional[float] = None
    hardcase_recall: Optional[float] = None

    failure_breakdown: Dict[str, int] = Field(default_factory=dict)
    preflight: Dict[str, Any] = Field(default_factory=dict)


class KGSearchDiagnosticsResponse(BaseModel):
    summary: KGSearchDiagnosticsSummary
    items: List[KGSearchDiagnosticsItem] = Field(default_factory=list)

