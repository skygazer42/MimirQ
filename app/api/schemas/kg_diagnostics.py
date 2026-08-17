"""
KG (Knowledge Graph) diagnostics evaluation schemas.

This is intentionally DB-light by default: the endpoint returns an on-demand
diagnostic report used to iteratively improve KG extraction/search quality for RAG.

Optionally, callers can persist a compact run snapshot (summary + per-case attribution)
to support metric diffs over time.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from .base import OrmModel

HardcaseMode = Literal["off", "deterministic", "llm"]
HardcaseKind = Literal["knowledge_pressure", "reasoning_pressure"]


class KGSearchDiagnosticsRequest(BaseModel):
    dataset_id: UUID
    case_ids: list[UUID] = Field(
        default_factory=list, description="Optional explicit case id list (else select by dataset)"
    )
    max_cases: int = Field(default=50, ge=1, le=200, description="Max cases to evaluate (default: 50)")

    k: int = Field(default=10, ge=1, le=50, description="Hit@K and evaluation cutoff (default: 10)")

    auto_extract_kg: bool = Field(default=True, description="If true, ensure evidence documents have KG extracted")
    extract_skills: bool | None = Field(default=None, description="Override KG skill extraction toggle")
    extract_relations: bool | None = Field(default=None, description="Override KG relation extraction toggle")

    hardcase_mode: HardcaseMode = Field(default="llm", description="Hardcase generation strategy")
    hardcases_per_failed_case: int = Field(default=4, ge=0, le=20)
    max_failed_cases_for_hardcase: int = Field(default=20, ge=0, le=200)

    llm_temperature: float = Field(default=0.2, ge=0.0, le=2.0, description="Hardcase LLM temperature")

    # Optional persistence for diffing/iteration.
    persist_run: bool = Field(default=False, description="Persist a compact run snapshot for diffing over time")


class KGSearchEventOut(BaseModel):
    id: str
    title: str = ""
    summary: str = ""
    content: str = ""
    document_id: str | None = None
    chunk_id: str | None = None
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
    ndcg: float = 0.0
    map: float = 0.0
    matched_evidence_chunks: int = 0
    total_evidence_chunks: int = 0
    k: int = 10


class KGSearchRunResult(BaseModel):
    query: str
    events: list[KGSearchEventOut] = Field(default_factory=list)
    entities: list[KGSearchEntityOut] = Field(default_factory=list)
    clues: list[dict[str, Any]] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)
    metrics: KGSearchRunMetrics = Field(default_factory=KGSearchRunMetrics)
    error: str | None = None


class KGHardcaseOut(BaseModel):
    kind: HardcaseKind
    question: str
    rationale: str | None = None
    run: KGSearchRunResult | None = None


class KGEvalAttribution(BaseModel):
    primary_cause: str = "other"
    signals: dict[str, Any] = Field(default_factory=dict)


class KGSearchDiagnosticsItem(BaseModel):
    case_id: UUID
    question: str
    tags: list[str] = Field(default_factory=list)

    evidence_chunk_ids: list[str] = Field(default_factory=list)
    ground_truth_event_ids: list[str] = Field(default_factory=list)

    baseline: KGSearchRunResult
    hardcases: list[KGHardcaseOut] = Field(default_factory=list)
    attribution: KGEvalAttribution = Field(default_factory=KGEvalAttribution)


class KGSearchDiagnosticsSummary(BaseModel):
    dataset_id: UUID
    cases_total: int = 0
    cases_evaluated: int = 0
    hardcases_generated: int = 0

    baseline_hit_rate: float = 0.0
    baseline_mrr: float = 0.0
    baseline_recall: float = 0.0
    baseline_ndcg: float = 0.0
    baseline_map: float = 0.0

    hardcase_hit_rate: float | None = None
    hardcase_mrr: float | None = None
    hardcase_recall: float | None = None
    hardcase_ndcg: float | None = None
    hardcase_map: float | None = None

    failure_breakdown: dict[str, int] = Field(default_factory=dict)
    preflight: dict[str, Any] = Field(default_factory=dict)


class KGSearchDiagnosticsResponse(BaseModel):
    run_id: UUID | None = Field(default=None, description="Run ID when persist_run=true (else null)")
    summary: KGSearchDiagnosticsSummary
    items: list[KGSearchDiagnosticsItem] = Field(default_factory=list)


class KGSearchDiagnosticsRunOut(OrmModel):
    id: UUID
    tenant_id: UUID
    account_id: str | None = None
    dataset_id: UUID
    status: str
    params: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class KGSearchDiagnosticsRunDetail(BaseModel):
    run: KGSearchDiagnosticsRunOut
    items: list[dict[str, Any]] = Field(default_factory=list)


class KGSearchDiagnosticsRunList(BaseModel):
    total: int
    items: list[KGSearchDiagnosticsRunOut] = Field(default_factory=list)
