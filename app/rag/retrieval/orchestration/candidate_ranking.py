"""Own query-result fusion and its family/diversity outcomes."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from langchain_core.documents import Document

from app.rag.engine_support.doc_utils import DocUtilsMixin
from app.rag.retrieval.orchestration import hierarchy
from app.rag.retrieval.orchestration.common import _log_orchestrator_fallback
from app.rag.retrieval.orchestration.query_contract import HierarchyContractSettings


@dataclass(frozen=True)
class QueryCandidateGroup:
    kind: str
    documents: list[Document]


@dataclass(frozen=True)
class QueryFusionSettings:
    top_k: int
    rrf_k: int
    multi_query_enabled: bool
    multi_query_budget: int
    hierarchy: HierarchyContractSettings


@dataclass(frozen=True)
class QueryFusionFailure:
    stage: str
    error: Exception


@dataclass(frozen=True)
class MultiQueryDiversityOutcome:
    enabled: bool
    budget: int
    used: bool = False
    selected_non_mq: int = 0
    selected_mq: int = 0
    fill_from_fused: int = 0


@dataclass(frozen=True)
class FusedQueryCandidates:
    documents: list[Document]
    refill_documents: list[Document]
    family_metadata: dict[str, Any]
    diversity: MultiQueryDiversityOutcome
    failures: tuple[QueryFusionFailure, ...]


def _record_failure(failures: list[QueryFusionFailure], stage: str, exc: Exception) -> None:
    _log_orchestrator_fallback("run_retrieval", exc)
    failures.append(QueryFusionFailure(stage, exc))


def _family_features(
    groups: Sequence[QueryCandidateGroup], *, settings: QueryFusionSettings, failures: list[QueryFusionFailure]
) -> tuple[bool, dict[str, dict[str, Any]]]:
    enabled = settings.hierarchy.enabled and settings.hierarchy.family_collapse and len(groups) > 1
    if not enabled:
        return False, {}
    try:
        return True, hierarchy._build_hierarchy_family_features([group.documents for group in groups])
    except Exception as exc:
        _record_failure(failures, "family_features", exc)
        return True, {}


def _aggregate_families(
    documents: list[Document],
    *,
    enabled: bool,
    features: dict[str, dict[str, Any]],
    strategy: str,
    failures: list[QueryFusionFailure],
) -> tuple[list[Document], dict[str, Any]]:
    if not enabled:
        return documents, {"enabled": False, "reason": "not_run"}
    try:
        return hierarchy._apply_hierarchy_family_aggregation(documents, family_features=features, strategy=strategy)
    except Exception as exc:
        _record_failure(failures, "family_aggregation", exc)
        return documents, {"enabled": False, "reason": "exception"}


def _fuse(groups: list[list[Document]], *, rrf_k: int) -> list[Document]:
    if len(groups) <= 1:
        return groups[0] if groups else []
    return DocUtilsMixin.fuse_docs_rrf(groups, rrf_k=rrf_k, meta_prefix="query_expansion")


def _select_distinct(target: list[Document], keys: set[str], candidates: list[Document], *, limit: int) -> int:
    added = 0
    for document in candidates:
        if len(target) >= limit:
            break
        key = DocUtilsMixin._doc_key(document)
        if key in keys:
            continue
        keys.add(key)
        target.append(document)
        added += 1
    return added


def _diversify_queries(
    groups: Sequence[QueryCandidateGroup],
    documents: list[Document],
    *,
    settings: QueryFusionSettings,
    diversity: MultiQueryDiversityOutcome,
    family_enabled: bool,
    family_features: dict[str, dict[str, Any]],
    failures: list[QueryFusionFailure],
) -> tuple[list[Document], MultiQueryDiversityOutcome]:
    mq_groups = [group.documents for group in groups if group.kind == "mq"]
    other_groups = [group.documents for group in groups if group.kind != "mq"]
    if not mq_groups or not other_groups:
        return documents, diversity
    other_docs = _fuse(other_groups, rrf_k=settings.rrf_k)
    mq_docs = _fuse(mq_groups, rrf_k=settings.rrf_k)
    if family_enabled:
        try:
            other_docs, _ = hierarchy._apply_hierarchy_family_aggregation(
                other_docs, family_features=family_features, strategy=settings.hierarchy.family_aggregation
            )
            mq_docs, _ = hierarchy._apply_hierarchy_family_aggregation(
                mq_docs, family_features=family_features, strategy=settings.hierarchy.family_aggregation
            )
        except Exception as exc:
            _record_failure(failures, "diversity_family_aggregation", exc)
    selected: list[Document] = []
    selected_keys: set[str] = set()
    non_mq = _select_distinct(selected, selected_keys, other_docs, limit=max(1, settings.top_k - diversity.budget))
    mq = _select_distinct(selected, selected_keys, mq_docs, limit=len(selected) + diversity.budget)
    refill = _select_distinct(selected, selected_keys, documents, limit=settings.top_k)
    return selected, replace(diversity, used=True, selected_non_mq=non_mq, selected_mq=mq, fill_from_fused=refill)


def fuse_query_candidates(
    groups: Sequence[QueryCandidateGroup], *, settings: QueryFusionSettings
) -> FusedQueryCandidates:
    """Fuse query groups; optional hierarchy failure never becomes an empty primary result."""
    diversity = MultiQueryDiversityOutcome(
        settings.multi_query_enabled, max(0, min(settings.multi_query_budget, settings.top_k))
    )
    failures: list[QueryFusionFailure] = []
    family_enabled, features = _family_features(groups, settings=settings, failures=failures)
    documents = _fuse([group.documents for group in groups], rrf_k=settings.rrf_k)
    refill_documents = documents
    family_metadata: dict[str, Any] = {"enabled": False, "reason": "not_run"}
    if len(groups) > 1:
        documents, family_metadata = _aggregate_families(
            documents,
            enabled=family_enabled,
            features=features,
            strategy=settings.hierarchy.family_aggregation,
            failures=failures,
        )
        if diversity.enabled and diversity.budget > 0:
            documents, diversity = _diversify_queries(
                groups,
                documents,
                settings=settings,
                diversity=diversity,
                family_enabled=family_enabled,
                family_features=features,
                failures=failures,
            )
    return FusedQueryCandidates(documents, refill_documents, family_metadata, diversity, tuple(failures))
