"""
RAGAS evaluation service.

- Supports conversation-based evaluation using stored chat messages + citations.
- Runs in FastAPI BackgroundTasks (sync function).
"""

import asyncio
import logging
import math
import re
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import AsyncExitStack, asynccontextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

import httpx
from fastapi import HTTPException
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

import app.services.datasets.management as dataset_service
from app.infrastructure.config import settings
from app.infrastructure.database.connection import SessionLocal
from app.infrastructure.http.environment import httpx_trust_env
from app.infrastructure.http.openai import normalize_openai_compatible_base_url
from app.models.conversations.chat import Conversation, Message
from app.models.documents.records import Document as DBDocument
from app.models.documents.records import DocumentChunk
from app.models.evaluation.results import (
    RagasEvaluationItem,
    RagasEvaluationRun,
    RagasRegressionCase,
    RagasRegressionItem,
    RagasRegressionRun,
)
from app.rag.embedding import create_langchain_embeddings_from_config
from app.rag.evaluation.judging.llm_judge import attach_llm_judge_to_eval_items
from app.rag.evaluation.regression.evidence_retrieve_gate import (
    build_retrieval_gate_summary,
    compute_retrieval_item_meta,
)
from app.rag.evaluation.regression.multimodal_slices import (
    classify_regression_case_multimodal_slice,
    summarize_multimodal_regression_slices,
)
from app.rag.evaluation.regression.regression_sample_builder import (
    _deterministic_faithfulness,
    _quote_verifiability,
    build_regression_item_meta,
    build_regression_sample,
)
from app.services.chat.conversation_access import ensure_conversation_access
from app.services.documents.read_scope import filter_allowed_document_ids, get_allowed_document_id_sets
from app.types.indexing import (
    DISPLAY_METADATA_KEY,
    EVALUABLE_METADATA_KEY,
    INDEXED_METADATA_KEY,
    RECORD_IDENTITY_METADATA_KEY,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger("app.rag.evaluation.ragas")
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9_]{2,}")
RAGAS_REGRESSION_METRICS = frozenset(
    {
        "faithfulness",
        "response_relevancy",
        "answer_relevancy",
        "answer_similarity",
        "answer_correctness",
        "context_recall",
        "context_precision",
        "id_based_context_recall",
        "id_based_context_precision",
        "llm_context_precision_without_reference",
    }
)

DETERMINISTIC_REGRESSION_METRICS = frozenset(
    {
        "faithfulness_det",
        "atomic_faithfulness",
        "hallucination_rate",
        "citation_accuracy",
        "citation_coverage",
        "retrieval_effective_context_rate",
        "retrieval_noise_rate",
        "quote_verifiability",
        "chunk_attribution",
        "chunk_utilization",
        "noise_sensitivity",
        "self_knowledge_ratio",
        "refusal_correctness",
        "retrieval_recall",
        "retrieval_mrr",
        "retrieval_ndcg_at_10",
        "retrieval_ndcg_at_20",
        "retrieval_hit_at_1",
        "retrieval_hit_at_3",
        "retrieval_hit_at_5",
        "retrieval_hit_at_10",
        "retrieval_hit_at_20",
        "expected_metadata_hit_rate",
        "expected_metadata_recall",
        "multihop_path_completeness",
        "multihop_order_consistency",
        "multihop_chain_hit_rate",
    }
)

_DETERMINISTIC_SCORE_META_KEYS = {
    "faithfulness_det": "faithfulness_det",
    "atomic_faithfulness": "atomic_faithfulness",
    "hallucination_rate": "hallucination_rate",
    "citation_accuracy": "citation_accuracy",
    "citation_coverage": "citation_coverage",
    "retrieval_effective_context_rate": "retrieval_effective_context_rate",
    "retrieval_noise_rate": "retrieval_noise_rate",
    "quote_verifiability": "quote_verifiability",
    "chunk_attribution": "chunk_attribution",
    "chunk_utilization": "chunk_utilization",
    "noise_sensitivity": "noise_sensitivity",
    "self_knowledge_ratio": "self_knowledge_ratio",
    "retrieval_recall": "retrieval_recall",
    "retrieval_mrr": "retrieval_mrr",
    "retrieval_ndcg_at_10": "retrieval_ndcg_at_10",
    "retrieval_ndcg_at_20": "retrieval_ndcg_at_20",
    "retrieval_hit_at_1": "retrieval_hit_at_1",
    "retrieval_hit_at_3": "retrieval_hit_at_3",
    "retrieval_hit_at_5": "retrieval_hit_at_5",
    "retrieval_hit_at_10": "retrieval_hit_at_10",
    "retrieval_hit_at_20": "retrieval_hit_at_20",
    "expected_metadata_recall": "expected_metadata_recall",
    "multihop_path_completeness": "multihop_path_completeness",
    "multihop_order_consistency": "multihop_order_consistency",
}


@dataclass(frozen=True)
class RegressionMetricSplit:
    ragas: list[str]
    deterministic: list[str]


@dataclass(frozen=True)
class CitationRecord:
    original: Any
    payload: dict[str, Any] | None
    chunk_id: UUID | None
    document_id: UUID | None
    fallback_text: str | None = None


@dataclass(frozen=True)
class RegressionRunMode:
    normalized_metric_names: list[str]
    metric_split: RegressionMetricSplit
    retrieval_only: bool
    deterministic_only: bool
    progress_mode: str


@dataclass(frozen=True)
class RagasExecutionResult:
    result: Any
    metric_keys: list[str]
    eval_prompt_tokens: int | None
    eval_completion_tokens: int | None
    eval_total_cost: float | None


@dataclass(frozen=True)
class RegressionCaseRoutingState:
    modality: str
    multimodal_router_meta: dict[str, Any]
    tag_meta: dict[str, Any]
    image_meta: dict[str, Any]
    injected_docs: list[Any]


def _normalized_metric_names(metric_names: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in metric_names or []:
        key = raw.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _split_normalized_regression_metrics(metric_names: list[str]) -> RegressionMetricSplit:
    ragas: list[str] = []
    deterministic: list[str] = []
    for key in metric_names:
        if key in DETERMINISTIC_REGRESSION_METRICS:
            deterministic.append(key)
        else:
            ragas.append(key)
    return RegressionMetricSplit(ragas=ragas, deterministic=deterministic)


def split_regression_metric_names(metric_names: list[str] | None) -> RegressionMetricSplit:
    return _split_normalized_regression_metrics(_normalized_metric_names(metric_names))


def _bool_score_from_meta(source: dict[str, Any], meta_key: str) -> float | None:
    value = source.get(meta_key)
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    return None


def _special_deterministic_score(key: str, source: dict[str, Any]) -> Any:
    if key == "refusal_correctness":
        return _bool_score_from_meta(source, "refusal_correct")
    if key == "multihop_chain_hit_rate":
        return _bool_score_from_meta(source, "multihop_chain_hit")
    if key == "expected_metadata_hit_rate":
        return _bool_score_from_meta(source, "expected_metadata_hit")
    if key == "atomic_faithfulness" and source.get("atomic_faithfulness") is None:
        return source.get("faithfulness_det")
    if key == "hallucination_rate" and source.get("hallucination_rate") is None:
        value = source.get("faithfulness_det")
        if value is not None:
            return round(1.0 - float(value), 4)
    return None


def _resolved_deterministic_score(key: str, source: dict[str, Any]) -> tuple[bool, Any]:
    special = _special_deterministic_score(key, source)
    if special is not None:
        return True, special

    meta_key = _DETERMINISTIC_SCORE_META_KEYS.get(key)
    if not meta_key:
        return False, None
    value = source.get(meta_key)
    return value is not None, value


def build_selected_deterministic_scores(metric_names: list[str] | None, meta: dict[str, Any] | None) -> dict[str, Any]:
    source = meta if isinstance(meta, dict) else {}
    scores: dict[str, Any] = {}
    for key in _normalized_metric_names(metric_names):
        resolved, value = _resolved_deterministic_score(key, source)
        if resolved:
            scores[key] = value
    return scores


def _build_regression_progress_summary(
    *,
    mode: str,
    processed_cases: int,
    total_cases: int,
    evaluable_items: int,
) -> dict[str, Any]:
    total = max(0, int(total_cases or 0))
    processed = max(0, min(int(processed_cases or 0), total)) if total else max(0, int(processed_cases or 0))
    percent = 1.0 if total <= 0 else round(float(processed) / float(total), 4)
    return {
        "mode": str(mode or "unknown"),
        "processed_cases": processed,
        "total_cases": total,
        "evaluable_items": max(0, int(evaluable_items or 0)),
        "percent": percent,
    }


def _commit_regression_progress(
    db: "Session",
    run: RagasRegressionRun,
    *,
    mode: str,
    processed_cases: int,
    total_cases: int,
    evaluable_items: int,
) -> None:
    try:
        summary = dict(run.summary or {})
        summary["progress"] = _build_regression_progress_summary(
            mode=mode,
            processed_cases=processed_cases,
            total_cases=total_cases,
            evaluable_items=evaluable_items,
        )
        run.summary = summary
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("Failed to persist regression progress: %s", exc, exc_info=True)


@asynccontextmanager
async def _evaluation_models(*, needs_embeddings: bool = True) -> AsyncIterator[tuple[Any, Any | None]]:
    """Own job clients and SDK tasks on this job's dedicated asyncio.run loop."""
    trust_env = httpx_trust_env(logger=logger)
    timeout = float(settings.LLM_TIMEOUT)
    async with AsyncExitStack() as resources:
        http_client = resources.enter_context(httpx.Client(trust_env=trust_env, timeout=timeout))
        http_async_client = await resources.enter_async_context(httpx.AsyncClient(trust_env=trust_env, timeout=timeout))
        try:
            yield _build_llm_and_embeddings(
                http_client=http_client,
                http_async_client=http_async_client,
                needs_embeddings=needs_embeddings,
            )
        finally:
            # Ragas 0.4.3 as_completed creates tasks without draining on cancellation.
            # This loop belongs only to this evaluation job, never the application loop.
            owner = asyncio.current_task()
            pending = [task for task in asyncio.all_tasks() if task is not owner]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)


def _pair_turns(messages: list[Message]) -> list[tuple[Message, Message]]:
    """
    Pair user -> assistant messages in order.
    Keeps the latest user message before an assistant reply.
    """
    turns: list[tuple[Message, Message]] = []
    pending_user: Message | None = None
    for msg in messages:
        if msg.role == "user":
            pending_user = msg
            continue
        if msg.role == "assistant":
            if pending_user is None:
                continue
            turns.append((pending_user, msg))
            pending_user = None
    return turns


def _coerce_uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None


def _normalize_citation_payload(item: Any) -> dict[str, Any] | None:
    if hasattr(item, "model_dump"):
        item = item.model_dump(mode="json")
    return item if isinstance(item, dict) else None


def _collect_citation_records(citations: Any) -> tuple[list[CitationRecord], list[UUID]]:
    records: list[CitationRecord] = []
    chunk_ids: list[UUID] = []
    seen_chunk_ids: set[UUID] = set()
    for item in citations or []:
        if item is None:
            continue
        payload = _normalize_citation_payload(item)
        if payload is None:
            records.append(CitationRecord(original=item, payload=None, chunk_id=None, document_id=None))
            continue
        chunk_id = _coerce_uuid(payload.get("chunk_id"))
        document_id = _coerce_uuid(payload.get("document_id"))
        raw_text = next(
            (payload[key] for key in ("chunk_content", "quote", "text") if payload.get(key) is not None), None
        )
        fallback_text = str(raw_text).strip() if raw_text is not None else None
        records.append(
            CitationRecord(
                original=item,
                payload=payload,
                chunk_id=chunk_id,
                document_id=document_id,
                fallback_text=fallback_text,
            )
        )
        if chunk_id and chunk_id not in seen_chunk_ids:
            seen_chunk_ids.add(chunk_id)
            chunk_ids.append(chunk_id)
    return records, chunk_ids


def _load_chunks_by_id(
    db: "Session",
    *,
    tenant_id: UUID,
    chunk_ids: list[UUID],
) -> dict[UUID, DocumentChunk]:
    if not chunk_ids:
        return {}
    chunks = (
        db.query(DocumentChunk)
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.id.in_(chunk_ids),
        )
        .all()
    )
    return {chunk.id: chunk for chunk in (chunks or [])}


def _filter_allowed_documents_for_dataset(
    db: "Session",
    *,
    tenant_id: UUID,
    allowed_set: set[UUID],
    dataset_id: UUID,
) -> set[UUID]:
    rows = (
        db.query(DBDocument.id, DBDocument.dataset_id)
        .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(list(allowed_set)))
        .all()
    )
    return {doc_id for doc_id, ds_id in rows if ds_id is not None and str(ds_id) == str(dataset_id)}


def _resolve_context_allowed_document_ids(
    db: "Session",
    *,
    tenant_id: UUID,
    account_id: str,
    records: list[CitationRecord],
    chunk_map: dict[UUID, DocumentChunk],
    allowed_document_ids: list[UUID] | None,
    dataset_id: UUID | None,
) -> set[UUID] | None:
    if allowed_document_ids is not None:
        allowed_set: set[UUID] | None = set(allowed_document_ids)
    else:
        candidate_doc_ids = {chunk.document_id for chunk in chunk_map.values() if chunk.document_id}
        candidate_doc_ids |= {record.document_id for record in records if record.document_id is not None}
        if candidate_doc_ids:
            allowed_ids, _missing = get_allowed_document_id_sets(
                db,
                tenant_id,
                account_id,
                list(candidate_doc_ids),
                check_member=True,
            )
            allowed_set = set(allowed_ids)
        else:
            allowed_set = set()
    if dataset_id is not None and allowed_set:
        return _filter_allowed_documents_for_dataset(
            db,
            tenant_id=tenant_id,
            allowed_set=allowed_set,
            dataset_id=dataset_id,
        )
    return allowed_set


def _build_contexts_from_citations(
    records: list[CitationRecord],
    *,
    chunk_map: dict[UUID, DocumentChunk],
    allowed_set: set[UUID] | None,
    max_context_chars: int,
) -> list[str]:
    contexts: list[str] = []
    seen_context_keys: set[str] = set()
    for record in records:
        chunk = chunk_map.get(record.chunk_id) if record.chunk_id else None
        doc_id = chunk.document_id if chunk is not None else record.document_id
        if allowed_set is not None and (doc_id is None or doc_id not in allowed_set):
            continue

        if chunk is None and record.fallback_text is None:
            continue
        content = chunk.content if chunk is not None else record.fallback_text
        if not content.strip():
            continue
        if max_context_chars and len(content) > max_context_chars:
            content = content[:max_context_chars] + "..."

        key = str(record.chunk_id) if record.chunk_id else f"text:{content[:64]}"
        if key in seen_context_keys:
            continue
        seen_context_keys.add(key)
        contexts.append(content)
    return contexts


def _extract_contexts(
    *,
    db: "Session",
    tenant_id: UUID,
    account_id: str,
    citations: Any,
    allowed_document_ids: list[UUID] | None = None,
    dataset_id: UUID | None = None,
    max_context_chars: int = 4000,
) -> list[str]:
    """
    Resolve full chunk contents from stored citations.
    """
    if not citations:
        return []

    records, chunk_ids = _collect_citation_records(citations)
    if not records:
        return []
    chunk_map = _load_chunks_by_id(db, tenant_id=tenant_id, chunk_ids=chunk_ids)
    allowed_set = _resolve_context_allowed_document_ids(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        records=records,
        chunk_map=chunk_map,
        allowed_document_ids=allowed_document_ids,
        dataset_id=dataset_id,
    )
    return _build_contexts_from_citations(
        records,
        chunk_map=chunk_map,
        allowed_set=allowed_set,
        max_context_chars=max_context_chars,
    )


_REGRESSION_CITATION_METADATA_VIEW_KEYS = (
    EVALUABLE_METADATA_KEY,
    INDEXED_METADATA_KEY,
    DISPLAY_METADATA_KEY,
    RECORD_IDENTITY_METADATA_KEY,
)

_REGRESSION_CITATION_METADATA_SCALAR_KEYS = (
    "pipeline_hash",
    "doc_pipeline_key",
    "chunk_strategy",
    "resolved_chunk_strategy",
    "chunk_python_plugin",
    "governance_python_plugin",
)


def _compact_chunk_metadata_for_regression(raw_metadata: Any) -> dict[str, Any]:
    """
    Keep regression citation metadata bounded and plugin-contract driven.

    Business-specific fields are supplied by plugins through metadata views; the
    platform only understands those generic views and a few pipeline identifiers.
    """
    if not isinstance(raw_metadata, dict):
        return {}

    out: dict[str, Any] = {}
    for view_key in _REGRESSION_CITATION_METADATA_VIEW_KEYS:
        view = raw_metadata.get(view_key)
        if not isinstance(view, dict):
            continue
        view_copy = _json_safe(view)
        out[view_key] = view_copy
        for key, value in view_copy.items():
            if key not in out:
                out[key] = value

    for key in _REGRESSION_CITATION_METADATA_SCALAR_KEYS:
        if key in raw_metadata and key not in out:
            out[key] = _json_safe(raw_metadata[key])

    return out


def _enrich_citations_with_chunk_metadata(
    *,
    db: "Session",
    tenant_id: UUID,
    account_id: str,
    citations: Any,
    allowed_document_ids: list[UUID] | None = None,
    dataset_id: UUID | None = None,
) -> Any:
    """
    Attach compact chunk metadata to retrieved citations for deterministic gates.

    Retrieval citations often carry only `chunk_id`/scores to keep chat payloads
    small. Regression expected_metadata checks need the plugin metadata contract,
    so evaluation hydrates it from DocumentChunk.doc_metadata just for run items.
    """
    if not isinstance(citations, list) or not citations:
        return citations

    records, chunk_ids = _collect_citation_records(citations)
    normalized_items = [record.payload if record.payload is not None else record.original for record in records]
    if not chunk_ids:
        return normalized_items

    chunk_map = _load_chunks_by_id(db, tenant_id=tenant_id, chunk_ids=chunk_ids)
    allowed_set = _resolve_context_allowed_document_ids(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        records=records,
        chunk_map=chunk_map,
        allowed_document_ids=allowed_document_ids,
        dataset_id=dataset_id,
    )

    enriched: list[Any] = []
    for record, item in zip(records, normalized_items, strict=False):
        if not isinstance(item, dict):
            enriched.append(item)
            continue

        out = dict(item)
        chunk = chunk_map.get(record.chunk_id) if record.chunk_id else None
        if chunk is None:
            enriched.append(out)
            continue

        doc_id = chunk.document_id
        if allowed_set is not None and (doc_id is None or doc_id not in allowed_set):
            enriched.append(out)
            continue

        compact = _compact_chunk_metadata_for_regression(chunk.doc_metadata)
        if compact:
            existing = out.get("metadata") if isinstance(out.get("metadata"), dict) else {}
            out["metadata"] = {**compact, **existing}
        enriched.append(out)

    return enriched


def _mean(values: Iterable[float]) -> float | None:
    vals = []
    for v in values:
        if v is None:
            continue
        try:
            fv = float(v)
        except (OverflowError, TypeError, ValueError):
            continue
        if not math.isfinite(fv):
            continue
        vals.append(fv)
    if not vals:
        return None
    return sum(vals) / len(vals)


def _build_regression_gate_summary(eval_items: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Compute non-LLM regression gate metrics from per-item meta.

    These are derived from the regression case's human-verified evidence pointers
    and the system's retrieved citations (chunk_id overlap), so they stay cheap and
    deterministic (usable even when RAGAS metrics are missing/partial).
    """

    metas: list[dict[str, Any]] = []
    for item in eval_items or []:
        if not isinstance(item, dict):
            continue
        meta = item.get("item_meta")
        metas.append(meta if isinstance(meta, dict) else {})

    out = _build_retrieval_metrics_summary(metas)

    out.update(_build_answer_quality_metrics_summary(metas))

    return out


def _mean_meta_float(metas: list[dict[str, Any]], key: str) -> float | None:
    return _mean(meta.get(key) for meta in metas)


def _update_answer_quality_faithfulness_summary(
    out: dict[str, Any],
    metas: list[dict[str, Any]],
) -> None:
    faith_det = _mean_meta_float(metas, "faithfulness_det")
    if faith_det is None:
        return
    out["faithfulness_det"] = faith_det
    out["atomic_faithfulness"] = faith_det
    out["hallucination_rate"] = round(1.0 - faith_det, 4)
    out["faithfulness"] = faith_det


def _update_answer_quality_average_summary(
    out: dict[str, Any],
    metas: list[dict[str, Any]],
    *,
    metric_keys: tuple[str, ...],
    suffix: str = "",
) -> None:
    for key in metric_keys:
        value = _mean_meta_float(metas, key)
        if value is not None:
            out[f"{key}{suffix}"] = value


def _build_refusal_quality_summary(metas: list[dict[str, Any]]) -> dict[str, Any]:
    labeled = 0
    correct = 0
    false_pos = 0
    false_neg = 0
    for meta in metas:
        expected_refusal = meta.get("expected_refusal")
        abstain_triggered = meta.get("abstain_triggered")
        if expected_refusal is None or abstain_triggered is None:
            continue
        labeled += 1
        expected_bool = bool(expected_refusal)
        abstain_bool = bool(abstain_triggered)
        if expected_bool == abstain_bool:
            correct += 1
            continue
        if (not expected_bool) and abstain_bool:
            false_pos += 1
        if expected_bool and (not abstain_bool):
            false_neg += 1
    if labeled <= 0:
        return {}
    return {
        "refusal_correctness": round(float(correct) / float(labeled), 4),
        "refusal_false_positive_rate": round(float(false_pos) / float(labeled), 4),
        "refusal_false_negative_rate": round(float(false_neg) / float(labeled), 4),
        "refusal_labeled_items": labeled,
    }


def _build_answer_quality_metrics_summary(metas: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Compute deterministic answer-quality summary metrics from regression item metadata.

    These are lightweight/no-LLM and designed to feed answer_quality_gate artifacts.
    """
    out: dict[str, Any] = {}
    _update_answer_quality_faithfulness_summary(out, metas)
    _update_answer_quality_average_summary(
        out,
        metas,
        metric_keys=(
            "citation_accuracy",
            "citation_coverage",
            "quote_verifiability",
            "chunk_utilization",
            "chunk_attribution",
            "noise_sensitivity",
            "self_knowledge_ratio",
        ),
    )
    _update_answer_quality_average_summary(
        out,
        metas,
        metric_keys=("citation_eval_limit", "citation_evaluated_count", "citation_total_count"),
        suffix="_avg",
    )
    out.update(_build_refusal_quality_summary(metas))
    return out


def _build_retrieval_metrics_summary(metas: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Compute retrieval-only metrics from a list of item_meta dicts.

    These stay cheap/deterministic (usable when RAGAS metrics are missing/partial).
    """

    def _mean_bool(key: str) -> float | None:
        vals: list[float] = []
        for m in metas:
            v = m.get(key)
            if v is None:
                continue
            vals.append(1.0 if bool(v) else 0.0)
        return _mean(vals)

    out = build_retrieval_gate_summary(metas)
    out.update(
        {
            "retrieval_effective_context_rate": _mean(m.get("retrieval_effective_context_rate") for m in metas),
            "retrieval_noise_rate": _mean(m.get("retrieval_noise_rate") for m in metas),
            "multihop_path_completeness": _mean(m.get("multihop_path_completeness") for m in metas),
            "multihop_order_consistency": _mean(m.get("multihop_order_consistency") for m in metas),
            "multihop_chain_hit_rate": _mean_bool("multihop_chain_hit"),
        }
    )
    return out


def _build_regression_slice_summaries(
    eval_items: list[dict[str, Any]],
    *,
    max_buckets: int = 20,
) -> dict[str, Any]:
    """
    Slice retrieval-only metrics by stable buckets (file_type/language/directory).

    Returns a JSON-safe dict meant for report exports (bounded).
    """
    max_buckets = max(0, min(int(max_buckets or 0), 200))

    metas: list[dict[str, Any]] = []
    for item in eval_items or []:
        if not isinstance(item, dict):
            continue
        meta = item.get("item_meta")
        metas.append(meta if isinstance(meta, dict) else {})

    def _bucketize(*, key: str) -> dict[str, Any]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for m in metas:
            raw = m.get(key)
            b = str(raw).strip().lower() or "unknown" if raw is not None else "unknown"
            if len(b) > 80:
                b = b[:80]
            groups.setdefault(b, []).append(m)

        rows: list[dict[str, Any]] = []
        for bucket, items in groups.items():
            summary = _build_retrieval_metrics_summary(items)
            rows.append({"key": bucket, "items": len(items), **summary})

        rows.sort(key=lambda o: (-o["items"], o["key"]))
        truncated = False
        if max_buckets > 0 and len(rows) > max_buckets:
            rows = rows[:max_buckets]
            truncated = True
        return {"buckets": rows, "truncated": truncated}

    return {
        "file_type": _bucketize(key="slice_file_type"),
        "language": _bucketize(key="slice_language"),
        "directory": _bucketize(key="slice_directory"),
        "access_mode": _bucketize(key="slice_access_mode"),
        "hit_type": _bucketize(key="slice_hit_type"),
        "quality": _bucketize(key="slice_quality_bucket"),
        "parse_quality": _bucketize(key="slice_parse_quality"),
        "chunk_quality": _bucketize(key="slice_chunk_quality"),
        "pipeline_hash": _bucketize(key="slice_pipeline_hash"),
    }


def _merge_summary_with_regression_gate(
    summary: dict[str, Any],
    *,
    eval_items: list[dict[str, Any]],
) -> dict[str, Any]:
    out = dict(summary or {})
    gate = _build_regression_gate_summary(eval_items)
    # Do not override existing summary keys (e.g. RAGAS metrics like "faithfulness").
    for k, v in gate.items():
        if k in out and out[k] is not None:
            continue
        out[k] = v
    out["retrieval_slices"] = _build_regression_slice_summaries(eval_items)
    return out


def _parse_uuid_list(raw_list: Any) -> list[UUID]:
    return [item_uuid for item in (raw_list or []) if (item_uuid := _coerce_uuid(item)) is not None]


def _json_safe(value: Any) -> Any:
    """Convert UUID and other types to JSON-serializable structure for JSONB storage."""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _resolve_case_scope(
    *,
    db: "Session",
    tenant_id: UUID,
    account_id: str,
    case: RagasRegressionCase,
) -> tuple[list[UUID] | None, UUID | None]:
    """
    Resolve retrieval scope for regression case:
    1) case.document_ids (priority)
    2) case.dataset_id -> dataset-scoped retrieval (no document_id enumeration)
    3) fallback: open-scope retrieval (tenant + ACL trimming)
    """
    if case.document_ids:
        raw_doc_ids = _parse_uuid_list(case.document_ids)
        if not raw_doc_ids:
            raise HTTPException(status_code=400, detail="Regression case has no valid document identifiers")
        allowed_doc_ids = filter_allowed_document_ids(db, tenant_id, account_id, raw_doc_ids)
        return allowed_doc_ids, None

    if case.dataset_id:
        ds = dataset_service.get_dataset(db, tenant_id, case.dataset_id)
        dataset_service.assert_dataset_readable(db, ds, account_id)
        return None, case.dataset_id

    return None, None


def _ragas_metric_factory_map() -> dict[str, Any]:
    from ragas.metrics import AnswerCorrectness as RagasAnswerCorrectness
    from ragas.metrics import AnswerSimilarity as RagasAnswerSimilarity
    from ragas.metrics import ContextPrecision as RagasContextPrecision
    from ragas.metrics import ContextRecall as RagasContextRecall
    from ragas.metrics import Faithfulness as RagasFaithfulness
    from ragas.metrics import IDBasedContextPrecision as RagasIDBasedContextPrecision
    from ragas.metrics import IDBasedContextRecall as RagasIDBasedContextRecall
    from ragas.metrics import LLMContextPrecisionWithoutReference as RagasLLMContextPrecisionWithoutReference
    from ragas.metrics import ResponseRelevancy as RagasResponseRelevancy

    return {
        "faithfulness": lambda: RagasFaithfulness(),
        "response_relevancy": lambda: RagasResponseRelevancy(strictness=_resolve_response_relevancy_strictness()),
        "answer_relevancy": lambda: RagasResponseRelevancy(strictness=_resolve_response_relevancy_strictness()),
        "answer_similarity": lambda: RagasAnswerSimilarity(),
        "answer_correctness": lambda: RagasAnswerCorrectness(),
        "context_recall": lambda: RagasContextRecall(),
        "context_precision": lambda: RagasContextPrecision(),
        "id_based_context_recall": lambda: RagasIDBasedContextRecall(),
        "id_based_context_precision": lambda: RagasIDBasedContextPrecision(),
        "llm_context_precision_without_reference": lambda: RagasLLMContextPrecisionWithoutReference(),
    }


def _resolve_metrics(metric_names: list[str]):
    """
    Map user-friendly names to RAGAS metric objects.
    Returns: list[Metric]
    """
    factory_map = _ragas_metric_factory_map()
    requested_names = metric_names or ["faithfulness", "response_relevancy"]
    resolved = []
    for name in requested_names:
        key = name.strip().lower()
        factory = factory_map.get(key)
        if factory is None:
            raise ValueError(f"Unsupported RAGAS metric: {name}")
        resolved.append(factory())
    return resolved


def _load_ragas_evaluation_runtime() -> tuple[Any, Any, Any, Any, Any]:
    from ragas import EvaluationDataset as RagasEvaluationDataset
    from ragas import SingleTurnSample as RagasSingleTurnSample
    from ragas import aevaluate as evaluate_fn
    from ragas.embeddings import LangchainEmbeddingsWrapper as RagasLangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper as RagasLangchainLLMWrapper

    return (
        RagasEvaluationDataset,
        RagasSingleTurnSample,
        evaluate_fn,
        RagasLangchainEmbeddingsWrapper,
        RagasLangchainLLMWrapper,
    )


def _resolve_response_relevancy_strictness() -> int:
    configured = int(settings.RAGAS_RESPONSE_RELEVANCY_STRICTNESS)
    if configured > 0:
        return max(1, min(configured, 10))

    if _eval_llm_uses_deepseek():
        return 1
    return 3


def _eval_llm_uses_deepseek() -> bool:
    llm_hint = f"{settings.LLM_API_BASE} {settings.LLM_MODEL}".lower()
    return "deepseek" in llm_hint


def _build_ragas_run_config():
    from ragas.run_config import RunConfig

    return RunConfig(
        timeout=max(5, int(settings.RAGAS_RUN_TIMEOUT_SEC)),
        max_retries=max(0, int(settings.RAGAS_RUN_MAX_RETRIES)),
        max_wait=max(1, int(settings.RAGAS_RUN_MAX_WAIT_SEC)),
        max_workers=max(1, int(settings.RAGAS_RUN_MAX_WORKERS)),
    )


def _should_use_conversation_deterministic_eval(metric_names: list[str]) -> bool:
    requested = _normalized_metric_names(metric_names) or ["faithfulness", "response_relevancy"]
    normalized = {"response_relevancy" if key == "answer_relevancy" else key for key in requested}
    supported = {"faithfulness", "response_relevancy"}
    if not normalized.issubset(supported):
        return False
    return bool(settings.RAGAS_CONVERSATION_DETERMINISTIC_MODE_ENABLED) or _eval_llm_uses_deepseek()


def _token_set(text: str) -> set[str]:
    return {match.group(0).casefold() for match in _TOKEN_RE.finditer(text)}


def _deterministic_response_relevancy(user_input: str, response: str) -> float | None:
    question_tokens = _token_set(user_input)
    if not question_tokens:
        return None
    response_tokens = _token_set(response)
    if not response_tokens:
        return 0.0
    return round(float(len(question_tokens & response_tokens)) / float(len(question_tokens)), 4)


def _build_conversation_deterministic_scores(
    *,
    user_input: str,
    response: str,
    retrieved_contexts: list[Any],
) -> dict[str, Any]:
    scores: dict[str, Any] = {}

    faithfulness_det = _deterministic_faithfulness(response, retrieved_contexts)
    if faithfulness_det is not None:
        scores["faithfulness_det"] = faithfulness_det
        scores["faithfulness"] = faithfulness_det
        scores["atomic_faithfulness"] = faithfulness_det
        scores["hallucination_rate"] = round(1.0 - faithfulness_det, 4)

    response_relevancy_det = _deterministic_response_relevancy(user_input, response)
    if response_relevancy_det is not None:
        scores["response_relevancy_det"] = response_relevancy_det
        scores["response_relevancy"] = response_relevancy_det

    quote_verifiability = _quote_verifiability(response, retrieved_contexts)
    if quote_verifiability is not None:
        scores["quote_verifiability"] = quote_verifiability

    return scores


def _persist_conversation_deterministic_result(
    *,
    db: "Session",
    run: RagasEvaluationRun,
    run_id: UUID,
    tenant_id: UUID,
    conversation_id: UUID,
    eval_items: list[dict[str, Any]],
    metric_names: list[str],
    max_turns: int,
    skip_empty_contexts: bool,
    reason: str,
    ragas_attempted: bool = False,
    fallback_error: str | None = None,
) -> None:
    score_rows: list[dict[str, Any]] = []
    db.query(RagasEvaluationItem).filter(
        RagasEvaluationItem.run_id == run_id,
        RagasEvaluationItem.tenant_id == tenant_id,
    ).delete(synchronize_session=False)

    for item in eval_items:
        scores = _build_conversation_deterministic_scores(
            user_input=item["user_input"],
            response=item["response"],
            retrieved_contexts=item["retrieved_contexts"],
        )
        score_rows.append(scores)
        db.add(
            RagasEvaluationItem(
                run_id=run_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                turn_index=item["turn_index"],
                user_message_id=item["user_message_id"],
                assistant_message_id=item["assistant_message_id"],
                user_input=item["user_input"],
                response=item["response"],
                retrieved_contexts=item["retrieved_contexts"],
                citations=item["citations"],
                scores=scores,
            )
        )

    metric_keys = _normalized_metric_names(metric_names) or ["faithfulness", "response_relevancy"]
    metric_keys = ["response_relevancy" if key == "answer_relevancy" else key for key in metric_keys]
    tracked_zero = 0 if not ragas_attempted else None
    tracked_cost_zero = 0.0 if not ragas_attempted else None
    summary: dict[str, Any] = {
        "items": len(eval_items),
        "mode": "deterministic_conversation",
        "ragas_skipped_reason": reason,
        "ragas_attempted": bool(ragas_attempted),
        "total_tokens": tracked_zero,
        "total_cost": tracked_cost_zero,
        "eval_llm_tokens_input_ragas": tracked_zero,
        "eval_llm_tokens_output_ragas": tracked_zero,
        "eval_estimated_cost_usd_ragas": tracked_cost_zero,
        "eval_llm_tokens_input": tracked_zero,
        "eval_llm_tokens_output": tracked_zero,
        "eval_estimated_cost_usd": tracked_cost_zero,
    }
    if fallback_error:
        summary["ragas_fallback_error"] = str(fallback_error)[:300]
    for key in (
        "faithfulness",
        "response_relevancy",
        "faithfulness_det",
        "response_relevancy_det",
        "atomic_faithfulness",
        "hallucination_rate",
        "quote_verifiability",
    ):
        value = _mean(row.get(key) for row in score_rows)
        if value is not None:
            summary[key] = value

    run.status = "completed"
    run.metrics = metric_keys
    run.params = {
        "requested_metrics": metric_names,
        "max_turns": max_turns,
        "skip_empty_contexts": skip_empty_contexts,
        "mode": "deterministic_conversation",
        "ragas_attempted": bool(ragas_attempted),
        "fallback_reason": reason,
    }
    run.summary = summary
    run.error_message = None
    run.finished_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()


def _build_llm_and_embeddings(
    *, http_client: httpx.Client, http_async_client: httpx.AsyncClient, needs_embeddings: bool = True
) -> tuple[Any, Any | None]:
    """
    Build LangChain LLM + embeddings compatible with RAGAS wrappers.
    """

    from app.infrastructure.model_policy import reject_retired_provider

    llm = ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=normalize_openai_compatible_base_url(settings.LLM_API_BASE),
        temperature=0.0,
        streaming=False,
        timeout=settings.LLM_TIMEOUT,
        max_retries=settings.LLM_MAX_RETRIES,
        http_client=http_client,
        http_async_client=http_async_client,
    )

    if not needs_embeddings:
        return llm, None

    provider = settings.EMBEDDING_PROVIDER.strip().lower()
    reject_retired_provider(provider, capability="embedding")

    if provider == "dashscope":
        embeddings = create_langchain_embeddings_from_config(
            provider="dashscope",
            model=settings.EMBEDDING_MODEL,
            api_key=settings.EMBEDDING_API_KEY or settings.LLM_API_KEY,
            base_url=settings.EMBEDDING_API_BASE or settings.LLM_API_BASE,
            dimension=None,
            http_client=http_client,
            http_async_client=http_async_client,
            use_cache=False,
        )
    else:
        api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
        base_url = normalize_openai_compatible_base_url(settings.EMBEDDING_API_BASE or settings.LLM_API_BASE)
        embeddings = OpenAIEmbeddings(
            model=settings.EMBEDDING_MODEL,
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
            http_async_client=http_async_client,
        )

    return llm, embeddings


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _mark_run_running(
    db: "Session", run: RagasEvaluationRun | RagasRegressionRun, *, clear_error: bool = False
) -> None:
    run.status = "running"
    run.started_at = _utc_now_naive()
    if clear_error:
        run.error_message = None
    db.commit()


def _mark_run_failed(db: "Session", run: RagasEvaluationRun | RagasRegressionRun, message: str) -> None:
    run.status = "failed"
    run.error_message = str(message)
    run.finished_at = _utc_now_naive()
    db.commit()


def _persist_run_failure(
    db: "Session",
    *,
    run_model: type[RagasEvaluationRun] | type[RagasRegressionRun],
    run_id: UUID,
    tenant_id: UUID,
    message: str,
) -> None:
    db.rollback()
    run = (
        db.query(run_model)
        .filter(
            run_model.id == run_id,
            run_model.tenant_id == tenant_id,
        )
        .first()
    )
    if run is not None:
        _mark_run_failed(db, run, message)


def _load_openai_callback_getter() -> Any:
    try:  # best-effort; works with LangChain OpenAI-compatible backends
        from langchain_community.callbacks.manager import (
            get_openai_callback as _get_openai_callback,  # type: ignore
        )

        return _get_openai_callback
    except ImportError:
        logger.debug("OpenAI token/cost callback is unavailable", exc_info=True)
        return None


async def _evaluate_ragas_dataset(
    *,
    evaluate_fn: Any,
    dataset: Any,
    metrics: list[Any],
    ragas_llm: Any,
    ragas_embeddings: Any,
    run_config: Any,
) -> tuple[Any, int | None, int | None, float | None]:
    get_openai_callback = _load_openai_callback_getter()
    callback_scope = get_openai_callback() if get_openai_callback is not None else nullcontext()
    with callback_scope as callback:
        result = await evaluate_fn(
            dataset=dataset,
            metrics=metrics,
            llm=ragas_llm,
            embeddings=ragas_embeddings,
            run_config=run_config,
            show_progress=False,
            raise_exceptions=False,
        )
    if get_openai_callback is None:
        return result, None, None, None
    return result, callback.prompt_tokens, callback.completion_tokens, callback.total_cost


def _load_conversation_for_evaluation(
    db: "Session",
    run: RagasEvaluationRun,
    *,
    tenant_id: UUID,
    account_id: str,
    conversation_id: UUID,
) -> tuple[Conversation | None, list[UUID] | None]:
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
        )
        .first()
    )
    if not conversation:
        _mark_run_failed(db, run, "Conversation not found")
        return None, []

    try:
        ensure_conversation_access(db, tenant_id, account_id, conversation)
    except HTTPException as exc:
        _mark_run_failed(db, run, str(exc.detail))
        return None, []

    requested_doc_ids = conversation.document_ids
    allowed_doc_ids = (
        filter_allowed_document_ids(db, tenant_id, account_id, requested_doc_ids) if requested_doc_ids else None
    )
    return conversation, allowed_doc_ids


def _build_conversation_eval_items(
    db: "Session",
    *,
    tenant_id: UUID,
    account_id: str,
    conversation_id: UUID,
    allowed_doc_ids: list[UUID] | None,
    max_turns: int,
    skip_empty_contexts: bool,
) -> list[dict[str, Any]]:
    messages = (
        db.query(Message)
        .filter(
            Message.conversation_id == conversation_id,
            Message.tenant_id == tenant_id,
        )
        .order_by(Message.created_at.asc())
        .all()
    )
    turns = _pair_turns(messages)
    if max_turns and max_turns > 0:
        turns = turns[-max_turns:]

    eval_items: list[dict[str, Any]] = []
    for idx, (user_msg, assistant_msg) in enumerate(turns, 1):
        contexts = _extract_contexts(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            allowed_document_ids=allowed_doc_ids,
            citations=assistant_msg.citations or [],
        )
        if skip_empty_contexts and not contexts:
            continue
        eval_items.append(
            {
                "turn_index": idx,
                "user_message_id": user_msg.id,
                "assistant_message_id": assistant_msg.id,
                "user_input": user_msg.content,
                "response": assistant_msg.content,
                "retrieved_contexts": contexts,
                "citations": assistant_msg.citations or [],
            }
        )
    return eval_items


def _run_conversation_ragas(
    *,
    eval_items: list[dict[str, Any]],
    metric_names: list[str],
) -> RagasExecutionResult:
    async def evaluate_owned() -> RagasExecutionResult:
        (
            ragas_evaluation_dataset,
            ragas_single_turn_sample,
            evaluate_fn,
            ragas_langchain_embeddings_wrapper,
            ragas_langchain_llm_wrapper,
        ) = _load_ragas_evaluation_runtime()
        async with _evaluation_models() as (llm, embeddings):
            ragas_llm = ragas_langchain_llm_wrapper(llm)
            ragas_embeddings = ragas_langchain_embeddings_wrapper(embeddings)
            metrics = _resolve_metrics(metric_names)
            metric_keys = [metric.name for metric in metrics]
            samples = [
                ragas_single_turn_sample(
                    user_input=item["user_input"],
                    response=item["response"],
                    retrieved_contexts=item["retrieved_contexts"],
                )
                for item in eval_items
            ]
            dataset = ragas_evaluation_dataset(samples=samples)
            run_config = _build_ragas_run_config()
            wall_timeout_sec = max(5.0, float(settings.RAGAS_CONVERSATION_WALL_TIMEOUT_SEC))
            result, prompt_tokens, completion_tokens, total_cost = await asyncio.wait_for(
                _evaluate_ragas_dataset(
                    evaluate_fn=evaluate_fn,
                    dataset=dataset,
                    metrics=metrics,
                    ragas_llm=ragas_llm,
                    ragas_embeddings=ragas_embeddings,
                    run_config=run_config,
                ),
                timeout=wall_timeout_sec,
            )
            return RagasExecutionResult(result, metric_keys, prompt_tokens, completion_tokens, total_cost)

    return asyncio.run(evaluate_owned())


def _normalize_ragas_scores(
    execution: RagasExecutionResult, *, expected_items: int
) -> tuple[list[dict[str, float | None]], dict[str, Any]]:
    raw_rows = execution.result.scores
    if len(raw_rows) != expected_items:
        raise ValueError("RAGAS score row count does not match evaluation samples")
    rows: list[dict[str, float | None]] = []
    availability = {key: {"valid": 0, "unavailable": 0} for key in execution.metric_keys}
    item_errors: list[dict[str, Any]] = []
    for index, raw_row in enumerate(raw_rows):
        row: dict[str, float | None] = {}
        errors: dict[str, str] = {}
        for key in execution.metric_keys:
            value = raw_row.get(key)
            try:
                score = float(value) if value is not None and not isinstance(value, bool) else None
            except (OverflowError, TypeError, ValueError):
                score = None
            if score is None or not math.isfinite(score):
                row[key] = None
                errors[key] = "metric_unavailable:RAGAS_returned_missing_or_nonfinite_score"
                availability[key]["unavailable"] += 1
            else:
                row[key] = score
                availability[key]["valid"] += 1
        rows.append(row)
        if errors:
            item_errors.append({"item_index": index, "metrics": errors})
    valid = sum(counts["valid"] for counts in availability.values())
    unavailable = sum(counts["unavailable"] for counts in availability.values())
    return rows, {
        "status": "failed" if valid == 0 else "partial" if unavailable else "completed",
        "valid_scores": valid,
        "unavailable_scores": unavailable,
        "metrics": availability,
        "item_errors": item_errors,
    }


def _persist_conversation_ragas_result(
    *,
    db: "Session",
    run: RagasEvaluationRun,
    run_id: UUID,
    tenant_id: UUID,
    conversation_id: UUID,
    eval_items: list[dict[str, Any]],
    metric_names: list[str],
    max_turns: int,
    skip_empty_contexts: bool,
    execution: RagasExecutionResult,
) -> None:
    score_rows, availability = _normalize_ragas_scores(execution, expected_items=len(eval_items))
    db.query(RagasEvaluationItem).filter(
        RagasEvaluationItem.run_id == run_id,
        RagasEvaluationItem.tenant_id == tenant_id,
    ).delete(synchronize_session=False)

    for idx, item in enumerate(eval_items):
        scores = score_rows[idx]
        db.add(
            RagasEvaluationItem(
                run_id=run_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                turn_index=item["turn_index"],
                user_message_id=item["user_message_id"],
                assistant_message_id=item["assistant_message_id"],
                user_input=item["user_input"],
                response=item["response"],
                retrieved_contexts=item["retrieved_contexts"],
                citations=item["citations"],
                scores=scores,
            )
        )

    summary: dict[str, Any] = {"items": len(eval_items)}
    for key in execution.metric_keys:
        summary[key] = _mean(row[key] for row in score_rows)
    summary["ragas_metrics"] = availability
    summary["total_tokens"] = (
        execution.eval_prompt_tokens + execution.eval_completion_tokens
        if execution.eval_prompt_tokens is not None and execution.eval_completion_tokens is not None
        else None
    )
    summary["total_cost"] = execution.eval_total_cost
    summary["eval_llm_tokens_input_ragas"] = execution.eval_prompt_tokens
    summary["eval_llm_tokens_output_ragas"] = execution.eval_completion_tokens
    summary["eval_estimated_cost_usd_ragas"] = (
        round(execution.eval_total_cost, 6) if execution.eval_total_cost is not None else None
    )
    summary["eval_llm_tokens_input"] = execution.eval_prompt_tokens
    summary["eval_llm_tokens_output"] = execution.eval_completion_tokens
    summary["eval_estimated_cost_usd"] = (
        round(execution.eval_total_cost, 6) if execution.eval_total_cost is not None else None
    )
    summary.update(_build_regression_gate_summary(eval_items))

    run.status = "failed" if availability["status"] == "failed" else "completed"
    run.error_message = "No RAGAS metric returned a usable score" if run.status == "failed" else None
    run.metrics = execution.metric_keys
    run.params = {
        "requested_metrics": metric_names,
        "max_turns": max_turns,
        "skip_empty_contexts": skip_empty_contexts,
    }
    run.summary = summary
    run.finished_at = _utc_now_naive()
    db.commit()


def run_conversation_ragas_evaluation(
    *,
    run_id: UUID,
    tenant_id: UUID,
    account_id: str,
    conversation_id: UUID,
    metric_names: list[str],
    max_turns: int,
    skip_empty_contexts: bool,
) -> None:
    """
    Background task entry: run RAGAS evaluation and persist results.
    """
    db = SessionLocal()
    try:
        run = (
            db.query(RagasEvaluationRun)
            .filter(
                RagasEvaluationRun.id == run_id,
                RagasEvaluationRun.tenant_id == tenant_id,
            )
            .first()
        )
        if not run:
            return

        _mark_run_running(db, run, clear_error=True)

        dataset_service.ensure_member(db, tenant_id, account_id)

        conversation, allowed_doc_ids = _load_conversation_for_evaluation(
            db,
            run,
            tenant_id=tenant_id,
            account_id=account_id,
            conversation_id=conversation_id,
        )
        if not conversation:
            return

        eval_items = _build_conversation_eval_items(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            conversation_id=conversation_id,
            allowed_doc_ids=allowed_doc_ids,
            max_turns=max_turns,
            skip_empty_contexts=skip_empty_contexts,
        )
        if not eval_items:
            _mark_run_failed(db, run, "No evaluatable turns (missing contexts/citations)")
            return

        if _should_use_conversation_deterministic_eval(metric_names):
            _persist_conversation_deterministic_result(
                db=db,
                run=run,
                run_id=run_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                eval_items=eval_items,
                metric_names=metric_names,
                max_turns=max_turns,
                skip_empty_contexts=skip_empty_contexts,
                reason="eval_llm_provider_compatibility",
            )
            return

        try:
            execution = _run_conversation_ragas(
                eval_items=eval_items,
                metric_names=metric_names,
            )
        except TimeoutError as exc:
            wall_timeout_sec = max(
                5.0,
                float(settings.RAGAS_CONVERSATION_WALL_TIMEOUT_SEC),
            )
            logger.warning(
                "Conversation RAGAS evaluation timed out after %.1fs; using deterministic fallback run_id=%s",
                wall_timeout_sec,
                run_id,
            )
            _persist_conversation_deterministic_result(
                db=db,
                run=run,
                run_id=run_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                eval_items=eval_items,
                metric_names=metric_names,
                max_turns=max_turns,
                skip_empty_contexts=skip_empty_contexts,
                reason="ragas_wall_timeout",
                ragas_attempted=True,
                fallback_error=str(exc),
            )
            return

        _persist_conversation_ragas_result(
            db=db,
            run=run,
            run_id=run_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            eval_items=eval_items,
            metric_names=metric_names,
            max_turns=max_turns,
            skip_empty_contexts=skip_empty_contexts,
            execution=execution,
        )
    except Exception as exc:
        _persist_run_failure(
            db,
            run_model=RagasEvaluationRun,
            run_id=run_id,
            tenant_id=tenant_id,
            message=str(exc),
        )
    finally:
        db.close()


def _build_regression_run_mode(metric_names: list[str]) -> RegressionRunMode:
    normalized_metric_names = _normalized_metric_names(metric_names)
    metric_split = _split_normalized_regression_metrics(normalized_metric_names)
    retrieval_only = not normalized_metric_names
    deterministic_only = (not retrieval_only) and bool(metric_split.deterministic) and not metric_split.ragas
    progress_mode = "retrieval_only" if retrieval_only else ("deterministic_gate" if deterministic_only else "ragas")
    return RegressionRunMode(
        normalized_metric_names=normalized_metric_names,
        metric_split=metric_split,
        retrieval_only=retrieval_only,
        deterministic_only=deterministic_only,
        progress_mode=progress_mode,
    )


def _normalize_regression_case_ids(case_ids: list[UUID]) -> list[UUID]:
    return list(dict.fromkeys(case_ids))


def _load_regression_cases(
    db: "Session",
    run: RagasRegressionRun,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    case_ids: list[UUID],
    max_cases: int,
) -> list[RagasRegressionCase] | None:
    query = db.query(RagasRegressionCase).filter(RagasRegressionCase.tenant_id == tenant_id)
    if dataset_id:
        query = query.filter(RagasRegressionCase.dataset_id == dataset_id)
    if case_ids:
        normalized_case_ids = _normalize_regression_case_ids(case_ids)
        query = query.filter(RagasRegressionCase.id.in_(normalized_case_ids))
        fetched = query.all()
        case_by_id = {case.id: case for case in fetched if case.id}
        missing = [case_id for case_id in normalized_case_ids if case_id not in case_by_id]
        if missing:
            _mark_run_failed(db, run, f"Missing regression cases: {len(missing)}")
            return None
        return [case_by_id[case_id] for case_id in normalized_case_ids]

    cases = query.order_by(RagasRegressionCase.updated_at.desc()).limit(max_cases).all()
    if not cases:
        _mark_run_failed(db, run, "No regression cases found")
        return None
    return cases


def _normalize_access_mode(value: object) -> str:
    if value is None:
        return "inherit"
    normalized = str(value).strip().lower()
    if not normalized or normalized == "inherit":
        return "inherit"
    if normalized in {"only_me", "partial_members", "all_team_members"}:
        return normalized
    return "unknown"


def _normalize_pipeline_hash(value: object) -> str:
    if value is None:
        return "unknown"
    normalized = str(value).strip()
    if not normalized:
        return "unknown"
    return normalized[:16]


def _stable_slice_bucket(values: set[str], *, default: str) -> str:
    cleaned = {value.strip().lower() for value in values if value.strip()}
    if not cleaned:
        return default
    if len(cleaned) == 1:
        return next(iter(cleaned))
    return "mixed"


def _collect_case_evidence_docs(
    cases: list[RagasRegressionCase],
) -> tuple[set[UUID], dict[UUID, list[UUID]]]:
    evidence_doc_ids: set[UUID] = set()
    case_to_evidence_docs: dict[UUID, list[UUID]] = {}
    for case in cases:
        doc_ids: list[UUID] = []
        seen: set[UUID] = set()
        for src in case.reference_sources or []:
            raw = src.get("document_id") if isinstance(src, dict) else getattr(src, "document_id", None)
            document_id = _coerce_uuid(raw)
            if document_id is None or document_id in seen:
                continue
            seen.add(document_id)
            doc_ids.append(document_id)
            evidence_doc_ids.add(document_id)
        if doc_ids:
            case_to_evidence_docs[case.id] = doc_ids
    return evidence_doc_ids, case_to_evidence_docs


def _parse_quality_bucket(meta_dict: dict[str, Any]) -> str:
    pq_bucket = "unknown"
    parse_quality = meta_dict.get("parse_quality")
    try:
        if isinstance(parse_quality, dict) and parse_quality.get("score") is not None:
            score = float(parse_quality.get("score") or 0.0)
            if score < 0.35:
                pq_bucket = "low"
            elif score < 0.7:
                pq_bucket = "mid"
            else:
                pq_bucket = "high"
    except Exception:
        pq_bucket = "unknown"
    return pq_bucket


def _chunk_quality_bucket(meta_dict: dict[str, Any]) -> str:
    gate = meta_dict.get("chunk_quality_gate")
    if not isinstance(gate, dict):
        return "unknown"
    raw_grade = gate.get("grade")
    if raw_grade is None:
        return "unknown"
    grade = str(raw_grade).strip().lower()
    if grade in {"pass", "warn", "fail"}:
        return grade
    if grade:
        return grade[:20]
    return "unknown"


def _load_evidence_document_attributes(
    db: "Session",
    *,
    tenant_id: UUID,
    evidence_doc_ids: set[UUID],
) -> dict[UUID, dict[str, str]]:
    if not evidence_doc_ids:
        return {}

    from app.services.datasets.profile import (
        directory_bucket_from_source_path,
        extract_language_bucket,
        quality_bucket_from_governance_quality,
    )
    from app.services.documents.pipeline_versions import get_active_pipeline_hash  # noqa: WPS433

    rows = (
        db.query(DBDocument.id, DBDocument.file_type, DBDocument.access_mode, DBDocument.doc_metadata)
        .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(list(evidence_doc_ids)))
        .all()
    )
    doc_attr: dict[UUID, dict[str, str]] = {}
    for doc_id, file_type, access_mode, meta in rows:
        meta_dict = meta if isinstance(meta, dict) else {}
        doc_attr[doc_id] = {
            "file_type": file_type.strip().lower() or "unknown",
            "language": extract_language_bucket(meta_dict),
            "directory": directory_bucket_from_source_path(meta_dict.get("source_path")),
            "pipeline_hash": _normalize_pipeline_hash(get_active_pipeline_hash(meta_dict)),
            "quality_bucket": quality_bucket_from_governance_quality(meta_dict.get("governance_quality")),
            "access_mode": _normalize_access_mode(access_mode),
            "parse_quality_bucket": _parse_quality_bucket(meta_dict),
            "chunk_quality_bucket": _chunk_quality_bucket(meta_dict),
        }
    return doc_attr


def _build_case_slice_meta(
    cases: list[RagasRegressionCase],
    *,
    case_to_evidence_docs: dict[UUID, list[UUID]],
    doc_attr: dict[UUID, dict[str, str]],
) -> dict[UUID, dict[str, str]]:
    slice_fields = (
        ("slice_file_type", "file_type", "unknown"),
        ("slice_language", "language", "unknown"),
        ("slice_directory", "directory", "root"),
        ("slice_access_mode", "access_mode", "inherit"),
        ("slice_pipeline_hash", "pipeline_hash", "unknown"),
        ("slice_quality_bucket", "quality_bucket", "unknown"),
        ("slice_parse_quality", "parse_quality_bucket", "unknown"),
        ("slice_chunk_quality", "chunk_quality_bucket", "unknown"),
    )
    case_slice_meta: dict[UUID, dict[str, str]] = {}
    for case in cases:
        document_attributes = [doc_attr.get(doc_id, {}) for doc_id in (case_to_evidence_docs.get(case.id) or [])]
        case_slice_meta[case.id] = {
            output: _stable_slice_bucket({attr.get(source, default) for attr in document_attributes}, default=default)
            for output, source, default in slice_fields
        }
    return case_slice_meta


def _resolve_case_modality(case: RagasRegressionCase) -> tuple[str, dict[str, Any]]:
    multimodal_router_meta: dict[str, Any] = {"enabled": True, "modality": "text", "reasons": []}
    extra = case.extra if isinstance(case.extra, dict) else {}
    override = extra.get("modality")
    if override is None:
        override = extra.get("query_modality")
    if isinstance(override, str):
        override = override.strip().lower()
    if override in ("text", "table", "image"):
        multimodal_router_meta["modality"] = override
        multimodal_router_meta["reasons"] = ["override"]
        return override, multimodal_router_meta

    try:
        from app.rag.policy.modality_router import classify_query_modality

        modality, reasons = classify_query_modality(case.question)
        normalized = str(modality or "text").strip().lower() or "text"
        multimodal_router_meta["modality"] = normalized
        multimodal_router_meta["reasons"] = reasons
        return normalized, multimodal_router_meta
    except Exception as exc:  # noqa: BLE001
        multimodal_router_meta["enabled"] = False
        multimodal_router_meta["modality"] = "text"
        multimodal_router_meta["reasons"] = [f"router_exception:{str(exc)[:80]}"]
        return "text", multimodal_router_meta


def _resolve_table_tag_context(
    db: "Session",
    *,
    tenant_id: UUID,
    account_id: str,
    case: RagasRegressionCase,
    scope_doc_ids: list[UUID] | None,
    scope_dataset_id: UUID | None,
) -> tuple[list[Any], dict[str, Any]]:
    try:
        from app.services.tables.chat_context import build_chat_tag_context_docs

        doc_ids_for_tag = list(scope_doc_ids or [])
        if not doc_ids_for_tag and scope_dataset_id is not None:
            max_doc_ids = int(settings.CHAT_TAG_MAX_DOC_IDS)
            candidate_rows = (
                db.query(DBDocument.id)
                .filter(
                    DBDocument.tenant_id == tenant_id,
                    DBDocument.dataset_id == scope_dataset_id,
                    DBDocument.status == "completed",
                )
                .order_by(DBDocument.updated_at.desc())
                .limit(max_doc_ids)
                .all()
            )
            candidate_ids = [row[0] for row in candidate_rows if row and row[0]]
            doc_ids_for_tag = filter_allowed_document_ids(db, tenant_id, account_id, candidate_ids)
        if not doc_ids_for_tag:
            return [], {"enabled": False, "used": False, "reason": "missing_document_scope"}
        tag_docs, tag_meta = build_chat_tag_context_docs(
            db,
            tenant_id=tenant_id,
            document_ids=doc_ids_for_tag,
            question=case.question,
        )
        return list(tag_docs or []), tag_meta
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return [], {"enabled": False, "used": False, "reason": f"tag_exception:{str(exc)[:120]}"}


def _prepare_regression_case_routing(
    db: "Session",
    *,
    tenant_id: UUID,
    account_id: str,
    case: RagasRegressionCase,
    scope_doc_ids: list[UUID] | None,
    scope_dataset_id: UUID | None,
) -> RegressionCaseRoutingState:
    modality, multimodal_router_meta = _resolve_case_modality(case)
    tag_meta: dict[str, Any] = {"enabled": False, "used": False, "reason": "not_run"}
    image_meta: dict[str, Any] = {"enabled": False, "used": False, "reason": "not_run"}
    injected_docs: list[Any] = []
    if modality == "table":
        tag_docs, tag_meta = _resolve_table_tag_context(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            case=case,
            scope_doc_ids=scope_doc_ids,
            scope_dataset_id=scope_dataset_id,
        )
        injected_docs.extend(tag_docs)
    return RegressionCaseRoutingState(
        modality=modality,
        multimodal_router_meta=multimodal_router_meta,
        tag_meta=tag_meta,
        image_meta=image_meta,
        injected_docs=injected_docs,
    )


def _build_regression_graph_state(
    *,
    db: "Session",
    tenant_id: UUID,
    account_id: str,
    case: RagasRegressionCase,
    scope_doc_ids: list[UUID] | None,
    scope_dataset_id: UUID | None,
    rag_params: dict[str, Any],
    routing_state: RegressionCaseRoutingState,
) -> dict[str, Any]:
    from app.rag.runtime.graph.state import build_rag_state

    state = build_rag_state(
        question=case.question,
        history=[],
        document_ids=scope_doc_ids,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=scope_dataset_id,
        retrieval_profile=rag_params.get("retrieval_profile"),
        enable_query_alias_expansion=rag_params.get("enable_query_alias_expansion"),
        query_alias_max_queries=rag_params.get("query_alias_max_queries"),
        enable_multi_query=rag_params.get("enable_multi_query"),
        multi_query_count=rag_params.get("multi_query_count"),
        multi_query_temperature=rag_params.get("multi_query_temperature"),
        multi_query_max_chars=rag_params.get("multi_query_max_chars"),
        enable_hyde=rag_params.get("enable_hyde"),
        enable_hierarchy_recall=rag_params.get("enable_hierarchy_recall"),
        hierarchy_family_collapse=rag_params.get("hierarchy_family_collapse"),
        hierarchy_family_aggregation=rag_params.get("hierarchy_family_aggregation"),
        hierarchy_tree_dedup=rag_params.get("hierarchy_tree_dedup"),
        hierarchy_parent_depth=rag_params.get("hierarchy_parent_depth"),
        hierarchy_sibling_window=rag_params.get("hierarchy_sibling_window"),
        hierarchy_overfetch_factor=rag_params.get("hierarchy_overfetch_factor"),
        enable_query_rewrite=rag_params.get("enable_query_rewrite"),
        query_rewrite_strategy=rag_params.get("query_rewrite_strategy"),
        query_rewrite_temperature=rag_params.get("query_rewrite_temperature"),
        query_rewrite_max_chars=rag_params.get("query_rewrite_max_chars"),
        top_k=int(rag_params.get("top_k", 5)),
        score_threshold=float(rag_params.get("score_threshold", 0.7)),
        retrieval_mode=str(rag_params.get("retrieval_mode", "hybrid")),
        alpha=float(rag_params.get("alpha", settings.RETRIEVAL_DEFAULT_ALPHA)),
        fusion_strategy=rag_params.get("fusion_strategy"),
        fusion_budgets=rag_params.get("fusion_budgets"),
        fusion_min_scores=rag_params.get("fusion_min_scores"),
        fusion_weights=rag_params.get("fusion_weights"),
        enable_weight_rerank=bool(rag_params.get("enable_weight_rerank", True)),
        vector_weight=float(rag_params.get("vector_weight", 0.6)),
        keyword_weight=float(rag_params.get("keyword_weight", 0.4)),
        mmr_lambda=float(rag_params.get("mmr_lambda", settings.RETRIEVAL_MMR_LAMBDA)),
        enable_reranker=bool(rag_params.get("enable_reranker", settings.ENABLE_RERANKER)),
        reranker_provider=rag_params.get("reranker_provider") or settings.RERANKER_PROVIDER,
        reranker_top_n=int(rag_params.get("reranker_top_n", settings.RERANKER_TOP_N)),
        structured_output=False,
        structured_preset=None,
        prompt_template_id=rag_params.get("prompt_template_id"),
        prompt_template_key=rag_params.get("prompt_template_key"),
        prompt_ab_experiment_key=rag_params.get("prompt_ab_experiment_key"),
        ab_user_key=account_id,
        db=db,
    )
    if routing_state.injected_docs:
        state["tag_docs"] = routing_state.injected_docs
    state["tag_meta"] = routing_state.tag_meta
    state["image_meta"] = routing_state.image_meta
    state["multimodal_router"] = routing_state.multimodal_router_meta
    return state


def _invoke_regression_graph(
    *,
    state: dict[str, Any],
    retrieval_only: bool,
    run_id: UUID,
    case_id: UUID,
) -> tuple[str, Any, dict[str, Any]]:
    from app.rag.runtime.graph.tasks import _retrieve_node
    from app.rag.runtime.graph.workflow import build_rag_graph, run_rag_workflow_functional

    if retrieval_only:
        graph_result = _retrieve_node(state) or {}
        return "", graph_result.get("citations") or [], graph_result

    thread_id = f"regression:{run_id}:{case_id}"
    use_functional_api = bool(settings.LANGGRAPH_USE_FUNCTIONAL_API)
    if use_functional_api:
        graph_result = run_rag_workflow_functional(state, thread_id=thread_id, context=None) or {}
    else:
        app = build_rag_graph()
        recursion_limit = max(1, int(settings.LANGGRAPH_RECURSION_LIMIT))
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": recursion_limit}
        graph_result = app.invoke(state, config=config, context=None) or {}
    return graph_result["answer"], (graph_result or {}).get("citations") or [], graph_result


def _resolve_citation_eval_limit(rag_params: dict[str, Any]) -> int:
    try:
        return max(1, int(rag_params.get("top_k") or 5))
    except (TypeError, ValueError):
        return 5


def _top_hit_type(citations: Any) -> str:
    if not isinstance(citations, list) or not citations:
        return "unknown"
    citation = citations[0]
    if isinstance(citation, dict):
        raw_hit_type = citation.get("hit_type")
        if isinstance(raw_hit_type, str):
            hit_type = raw_hit_type.strip().lower()
            if hit_type in {"vector", "keyword", "hybrid", "mmr", "tag", "image", "table"}:
                return hit_type
    return "unknown"


def _merge_regression_item_meta(
    case: RagasRegressionCase,
    *,
    item_meta: dict[str, Any],
    case_slice_meta: dict[UUID, dict[str, str]],
    routing_state: RegressionCaseRoutingState,
    citations: Any,
) -> dict[str, Any]:
    merged_meta = dict(item_meta or {})
    merged_meta.update(case_slice_meta.get(case.id) or {})
    merged_meta.setdefault("slice_modality", str(routing_state.multimodal_router_meta.get("modality") or "text"))
    merged_meta.setdefault("golden_multimodal_slice", classify_regression_case_multimodal_slice(case))
    merged_meta.setdefault("multimodal_router", dict(routing_state.multimodal_router_meta))
    merged_meta.setdefault("tag_meta", dict(routing_state.tag_meta))
    merged_meta.setdefault("image_meta", dict(routing_state.image_meta))
    merged_meta.setdefault("slice_hit_type", _top_hit_type(citations))
    return merged_meta


def _build_regression_eval_item(
    db: "Session",
    *,
    run_id: UUID,
    tenant_id: UUID,
    account_id: str,
    case: RagasRegressionCase,
    mode: RegressionRunMode,
    rag_params: dict[str, Any],
    case_slice_meta: dict[UUID, dict[str, str]],
    skip_empty_contexts: bool,
) -> dict[str, Any] | None:
    scope_doc_ids, scope_dataset_id = _resolve_case_scope(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        case=case,
    )
    routing_state = _prepare_regression_case_routing(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        case=case,
        scope_doc_ids=scope_doc_ids,
        scope_dataset_id=scope_dataset_id,
    )
    state = _build_regression_graph_state(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        case=case,
        scope_doc_ids=scope_doc_ids,
        scope_dataset_id=scope_dataset_id,
        rag_params=rag_params,
        routing_state=routing_state,
    )
    response, citations, graph_result = _invoke_regression_graph(
        state=state,
        retrieval_only=mode.retrieval_only,
        run_id=run_id,
        case_id=case.id,
    )
    citations = _enrich_citations_with_chunk_metadata(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        allowed_document_ids=scope_doc_ids,
        dataset_id=scope_dataset_id,
        citations=citations,
    )
    contexts = _extract_contexts(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        allowed_document_ids=scope_doc_ids,
        dataset_id=scope_dataset_id,
        citations=citations,
    )
    if skip_empty_contexts and not contexts:
        return None

    metrics_meta = (graph_result or {}).get("metrics") or {}
    eval_item: dict[str, Any] = {
        "case_id": case.id,
        "question": case.question,
        "response": response,
        "retrieved_contexts": contexts,
        "citations": citations,
        "citation_eval_limit": _resolve_citation_eval_limit(rag_params),
        "abstain_triggered": bool((graph_result or {}).get("abstain_triggered")),
        "abstain_reason": (graph_result or {}).get("abstain_reason"),
        "top_relevance_score": metrics_meta.get("top_relevance_score") if isinstance(metrics_meta, dict) else None,
    }
    sample_kwargs, item_meta = build_regression_sample(case, eval_item)
    if mode.retrieval_only:
        item_meta = compute_retrieval_item_meta(
            case=case,
            citations=citations,
            retrieval_metrics=metrics_meta,
            base_meta=item_meta,
        )
    eval_item["sample_kwargs"] = sample_kwargs
    eval_item["item_meta"] = _merge_regression_item_meta(
        case,
        item_meta=item_meta,
        case_slice_meta=case_slice_meta,
        routing_state=routing_state,
        citations=citations,
    )
    return eval_item


def _collect_regression_eval_items(
    db: "Session",
    run: RagasRegressionRun,
    *,
    run_id: UUID,
    tenant_id: UUID,
    account_id: str,
    cases: list[RagasRegressionCase],
    mode: RegressionRunMode,
    rag_params: dict[str, Any],
    skip_empty_contexts: bool,
    case_slice_meta: dict[UUID, dict[str, str]],
) -> list[dict[str, Any]]:
    eval_items: list[dict[str, Any]] = []
    total_cases = len(cases)
    for case_index, case in enumerate(cases, start=1):
        eval_item = _build_regression_eval_item(
            db,
            run_id=run_id,
            tenant_id=tenant_id,
            account_id=account_id,
            case=case,
            mode=mode,
            rag_params=rag_params,
            case_slice_meta=case_slice_meta,
            skip_empty_contexts=skip_empty_contexts,
        )
        if eval_item is not None:
            eval_items.append(eval_item)
        _commit_regression_progress(
            db,
            run,
            mode=mode.progress_mode,
            processed_cases=case_index,
            total_cases=total_cases,
            evaluable_items=len(eval_items),
        )
    return eval_items


def _maybe_attach_llm_judge(
    *,
    use_llm_judge: bool,
    retrieval_only: bool,
    eval_items: list[dict[str, Any]],
    db: "Session",
    tenant_id: UUID,
    account_id: str,
    rag_params: dict[str, Any],
    llm: Any,
) -> dict[str, Any]:
    if not use_llm_judge or retrieval_only:
        return {}
    try:
        llm_judge_summary = attach_llm_judge_to_eval_items(
            eval_items=eval_items,
            llm=llm,
            db=db,
            tenant_id=tenant_id,
            judge_prompt_template_id=rag_params.get("judge_prompt_template_id"),
            judge_prompt_template_key=rag_params.get("judge_prompt_template_key"),
            judge_prompt_ab_experiment_key=rag_params.get("judge_prompt_ab_experiment_key"),
            judge_ab_user_key=account_id,
        )
        return llm_judge_summary
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return {
            "llm_judge_items": 0,
            "llm_judge_error": f"{type(exc).__name__}:{str(exc)[:160]}",
        }


def _replace_regression_items(
    db: "Session",
    *,
    run_id: UUID,
    tenant_id: UUID,
    eval_items: list[dict[str, Any]],
    score_builder: Callable[[dict[str, Any], int], dict[str, Any]],
) -> None:
    db.query(RagasRegressionItem).filter(
        RagasRegressionItem.run_id == run_id,
        RagasRegressionItem.tenant_id == tenant_id,
    ).delete(synchronize_session=False)
    for idx, item in enumerate(eval_items):
        db.add(
            RagasRegressionItem(
                run_id=run_id,
                tenant_id=tenant_id,
                case_id=item["case_id"],
                question=item["question"],
                response=item["response"],
                retrieved_contexts=item["retrieved_contexts"],
                citations=item["citations"],
                scores=score_builder(item, idx),
                meta=build_regression_item_meta(
                    sample_kwargs=item.get("sample_kwargs"),
                    item_meta=item.get("item_meta"),
                ),
            )
        )


def _build_regression_summary_base(
    *,
    mode: str,
    total_cases: int,
    eval_items: list[dict[str, Any]],
    llm_judge_summary: dict[str, Any],
) -> dict[str, Any]:
    summary: dict[str, Any] = {"items": len(eval_items)}
    summary["progress"] = _build_regression_progress_summary(
        mode=mode,
        processed_cases=total_cases,
        total_cases=total_cases,
        evaluable_items=len(eval_items),
    )
    summary = _merge_summary_with_regression_gate(summary, eval_items=eval_items)
    summary["multimodal_slices"] = summarize_multimodal_regression_slices(eval_items)
    if llm_judge_summary:
        summary.update(llm_judge_summary)
    return summary


def _apply_judge_only_eval_cost_summary(
    summary: dict[str, Any],
    *,
    use_llm_judge: bool,
    llm_judge_summary: dict[str, Any],
) -> None:
    if use_llm_judge:
        judge_in = llm_judge_summary.get("llm_judge_tokens_input")
        judge_out = llm_judge_summary.get("llm_judge_tokens_output")
        judge_cost = llm_judge_summary.get("llm_judge_estimated_cost_usd")
        summary["eval_llm_tokens_input"] = int(judge_in) if judge_in is not None else None
        summary["eval_llm_tokens_output"] = int(judge_out) if judge_out is not None else None
        summary["eval_estimated_cost_usd"] = round(float(judge_cost), 6) if judge_cost is not None else None
        return
    summary["eval_llm_tokens_input"] = 0
    summary["eval_llm_tokens_output"] = 0
    summary["eval_estimated_cost_usd"] = 0.0


def _persist_retrieval_only_regression_result(
    *,
    db: "Session",
    run: RagasRegressionRun,
    run_id: UUID,
    tenant_id: UUID,
    eval_items: list[dict[str, Any]],
    skip_empty_contexts: bool,
    max_cases: int,
    rag_params: dict[str, Any],
    llm_judge_summary: dict[str, Any],
    total_cases: int,
) -> None:
    _replace_regression_items(
        db,
        run_id=run_id,
        tenant_id=tenant_id,
        eval_items=eval_items,
        score_builder=lambda _item, _idx: {},
    )
    summary = _build_regression_summary_base(
        mode="retrieval_only",
        total_cases=total_cases,
        eval_items=eval_items,
        llm_judge_summary=llm_judge_summary,
    )
    summary["eval_llm_tokens_input"] = 0
    summary["eval_llm_tokens_output"] = 0
    summary["eval_estimated_cost_usd"] = 0.0
    run.status = "completed"
    run.metrics = []
    run.params = {
        **(run.params or {}),
        "requested_metrics": [],
        "skip_empty_contexts": skip_empty_contexts,
        "max_cases": max_cases,
        "rag_params": _json_safe(rag_params),
        "mode": "retrieval_only",
    }
    run.summary = summary
    run.finished_at = _utc_now_naive()
    db.commit()


def _persist_deterministic_regression_result(
    *,
    db: "Session",
    run: RagasRegressionRun,
    run_id: UUID,
    tenant_id: UUID,
    eval_items: list[dict[str, Any]],
    skip_empty_contexts: bool,
    max_cases: int,
    rag_params: dict[str, Any],
    llm_judge_summary: dict[str, Any],
    total_cases: int,
    use_llm_judge: bool,
    mode: RegressionRunMode,
) -> None:
    _replace_regression_items(
        db,
        run_id=run_id,
        tenant_id=tenant_id,
        eval_items=eval_items,
        score_builder=lambda item, _idx: build_selected_deterministic_scores(
            mode.metric_split.deterministic,
            item.get("item_meta") if isinstance(item.get("item_meta"), dict) else {},
        ),
    )
    summary = _build_regression_summary_base(
        mode="deterministic_gate",
        total_cases=total_cases,
        eval_items=eval_items,
        llm_judge_summary=llm_judge_summary,
    )
    _apply_judge_only_eval_cost_summary(
        summary,
        use_llm_judge=use_llm_judge,
        llm_judge_summary=llm_judge_summary,
    )
    run.status = "completed"
    run.metrics = list(mode.normalized_metric_names)
    run.params = {
        **(run.params or {}),
        "requested_metrics": list(mode.normalized_metric_names),
        "skip_empty_contexts": skip_empty_contexts,
        "max_cases": max_cases,
        "rag_params": _json_safe(rag_params),
        "mode": "deterministic_gate",
    }
    run.summary = summary
    run.finished_at = _utc_now_naive()
    db.commit()


async def _run_regression_ragas(
    *,
    eval_items: list[dict[str, Any]],
    metric_names: list[str],
    shared_llm: Any,
    shared_embeddings: Any,
) -> RagasExecutionResult:
    (
        ragas_evaluation_dataset,
        ragas_single_turn_sample,
        evaluate_fn,
        ragas_langchain_embeddings_wrapper,
        ragas_langchain_llm_wrapper,
    ) = _load_ragas_evaluation_runtime()
    llm = shared_llm
    embeddings = shared_embeddings
    ragas_llm = ragas_langchain_llm_wrapper(llm)
    ragas_embeddings = ragas_langchain_embeddings_wrapper(embeddings)
    metrics = _resolve_metrics(metric_names)
    metric_keys = [metric.name for metric in metrics]
    samples = [ragas_single_turn_sample(**(item.get("sample_kwargs") or {})) for item in eval_items]
    dataset = ragas_evaluation_dataset(samples=samples)
    run_config = _build_ragas_run_config()
    result, eval_prompt_tokens, eval_completion_tokens, eval_total_cost = await _evaluate_ragas_dataset(
        evaluate_fn=evaluate_fn,
        dataset=dataset,
        metrics=metrics,
        ragas_llm=ragas_llm,
        ragas_embeddings=ragas_embeddings,
        run_config=run_config,
    )
    return RagasExecutionResult(
        result=result,
        metric_keys=metric_keys,
        eval_prompt_tokens=eval_prompt_tokens,
        eval_completion_tokens=eval_completion_tokens,
        eval_total_cost=eval_total_cost,
    )


def _apply_combined_eval_cost_summary(
    summary: dict[str, Any],
    *,
    execution: RagasExecutionResult,
    llm_judge_summary: dict[str, Any],
) -> None:
    summary["eval_llm_tokens_input_ragas"] = execution.eval_prompt_tokens
    summary["eval_llm_tokens_output_ragas"] = execution.eval_completion_tokens
    summary["eval_estimated_cost_usd_ragas"] = (
        round(execution.eval_total_cost, 6) if execution.eval_total_cost is not None else None
    )
    judge_in = llm_judge_summary.get("llm_judge_tokens_input")
    judge_out = llm_judge_summary.get("llm_judge_tokens_output")
    judge_cost = llm_judge_summary.get("llm_judge_estimated_cost_usd")
    token_in_known = (execution.eval_prompt_tokens is not None) or (judge_in is not None)
    token_out_known = (execution.eval_completion_tokens is not None) or (judge_out is not None)
    cost_known = (execution.eval_total_cost is not None) or (judge_cost is not None)
    summary["eval_llm_tokens_input"] = (
        (execution.eval_prompt_tokens or 0) + int(judge_in or 0) if token_in_known else None
    )
    summary["eval_llm_tokens_output"] = (
        (execution.eval_completion_tokens or 0) + int(judge_out or 0) if token_out_known else None
    )
    summary["eval_estimated_cost_usd"] = (
        round((execution.eval_total_cost or 0.0) + float(judge_cost or 0.0), 6) if cost_known else None
    )


def _persist_ragas_regression_result(
    *,
    db: "Session",
    run: RagasRegressionRun,
    run_id: UUID,
    tenant_id: UUID,
    eval_items: list[dict[str, Any]],
    metric_names: list[str],
    skip_empty_contexts: bool,
    max_cases: int,
    rag_params: dict[str, Any],
    llm_judge_summary: dict[str, Any],
    total_cases: int,
    mode: RegressionRunMode,
    execution: RagasExecutionResult,
) -> None:
    score_rows, availability = _normalize_ragas_scores(execution, expected_items=len(eval_items))
    for error in availability["item_errors"]:
        item = eval_items[error["item_index"]]
        item.setdefault("item_meta", {})["ragas_metric_errors"] = error["metrics"]
    _replace_regression_items(
        db,
        run_id=run_id,
        tenant_id=tenant_id,
        eval_items=eval_items,
        score_builder=lambda item, idx: {
            **score_rows[idx],
            **build_selected_deterministic_scores(
                mode.metric_split.deterministic,
                item.get("item_meta") if isinstance(item.get("item_meta"), dict) else {},
            ),
        },
    )
    summary = _build_regression_summary_base(
        mode="ragas",
        total_cases=total_cases,
        eval_items=eval_items,
        llm_judge_summary=llm_judge_summary,
    )
    for key in execution.metric_keys:
        summary[key] = _mean(row[key] for row in score_rows)
    summary["ragas_metrics"] = availability
    summary["total_tokens"] = (
        execution.eval_prompt_tokens + execution.eval_completion_tokens
        if execution.eval_prompt_tokens is not None and execution.eval_completion_tokens is not None
        else None
    )
    summary["total_cost"] = execution.eval_total_cost
    _apply_combined_eval_cost_summary(summary, execution=execution, llm_judge_summary=llm_judge_summary)
    run.status = "failed" if availability["status"] == "failed" else "completed"
    run.error_message = "No RAGAS metric returned a usable score" if run.status == "failed" else None
    run.metrics = [*execution.metric_keys, *mode.metric_split.deterministic]
    run.params = {
        **(run.params or {}),
        "requested_metrics": metric_names,
        "skip_empty_contexts": skip_empty_contexts,
        "max_cases": max_cases,
        "rag_params": _json_safe(rag_params),
    }
    run.summary = summary
    run.finished_at = _utc_now_naive()
    db.commit()


def run_regression_ragas_evaluation(
    *,
    run_id: UUID,
    tenant_id: UUID,
    account_id: str,
    case_ids: list[UUID],
    dataset_id: UUID | None,
    metric_names: list[str],
    use_llm_judge: bool = False,
    skip_empty_contexts: bool,
    max_cases: int,
    rag_params: dict[str, Any],
) -> None:
    """
    Background task entry: run RAGAS regression evaluation (case-based) and persist results.
    """
    db = SessionLocal()
    try:
        run = (
            db.query(RagasRegressionRun)
            .filter(RagasRegressionRun.id == run_id, RagasRegressionRun.tenant_id == tenant_id)
            .first()
        )
        if not run:
            return

        _mark_run_running(db, run)

        dataset_service.ensure_member(db, tenant_id, account_id)
        cases = _load_regression_cases(
            db,
            run,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            case_ids=case_ids,
            max_cases=max_cases,
        )
        if not cases:
            return

        mode = _build_regression_run_mode(metric_names)
        evidence_doc_ids, case_to_evidence_docs = _collect_case_evidence_docs(cases)
        doc_attr = _load_evidence_document_attributes(
            db,
            tenant_id=tenant_id,
            evidence_doc_ids=evidence_doc_ids,
        )
        case_slice_meta = _build_case_slice_meta(
            cases,
            case_to_evidence_docs=case_to_evidence_docs,
            doc_attr=doc_attr,
        )
        eval_items = _collect_regression_eval_items(
            db,
            run,
            run_id=run_id,
            tenant_id=tenant_id,
            account_id=account_id,
            cases=cases,
            mode=mode,
            rag_params=rag_params,
            skip_empty_contexts=skip_empty_contexts,
            case_slice_meta=case_slice_meta,
        )
        total_cases = len(cases)

        if not eval_items:
            _mark_run_failed(db, run, "No evaluatable cases (missing contexts/citations)")
            return

        async def run_model_phase() -> tuple[dict[str, Any], RagasExecutionResult | None]:
            async with _evaluation_models(needs_embeddings=not mode.deterministic_only) as (llm, embeddings):
                # The public entry runs on a synchronous BackgroundTasks worker.
                # Resolve prompt/Session work on that same thread before SDK tasks start.
                judge_summary = _maybe_attach_llm_judge(
                    use_llm_judge=use_llm_judge,
                    retrieval_only=mode.retrieval_only,
                    eval_items=eval_items,
                    db=db,
                    tenant_id=tenant_id,
                    account_id=account_id,
                    rag_params=rag_params,
                    llm=llm,
                )
                if mode.deterministic_only:
                    return judge_summary, None
                execution = await _run_regression_ragas(
                    eval_items=eval_items,
                    metric_names=mode.metric_split.ragas,
                    shared_llm=llm,
                    shared_embeddings=embeddings,
                )
                return judge_summary, execution

        if mode.retrieval_only or (mode.deterministic_only and not use_llm_judge):
            llm_judge_summary, execution = {}, None
        else:
            llm_judge_summary, execution = asyncio.run(run_model_phase())

        if mode.retrieval_only:
            _persist_retrieval_only_regression_result(
                db=db,
                run=run,
                run_id=run_id,
                tenant_id=tenant_id,
                eval_items=eval_items,
                skip_empty_contexts=skip_empty_contexts,
                max_cases=max_cases,
                rag_params=rag_params,
                llm_judge_summary=llm_judge_summary,
                total_cases=total_cases,
            )
            return

        if mode.deterministic_only:
            _persist_deterministic_regression_result(
                db=db,
                run=run,
                run_id=run_id,
                tenant_id=tenant_id,
                eval_items=eval_items,
                skip_empty_contexts=skip_empty_contexts,
                max_cases=max_cases,
                rag_params=rag_params,
                llm_judge_summary=llm_judge_summary,
                total_cases=total_cases,
                use_llm_judge=use_llm_judge,
                mode=mode,
            )
            return

        # The two modes without an SDK result returned above.
        execution = cast(RagasExecutionResult, execution)
        _persist_ragas_regression_result(
            db=db,
            run=run,
            run_id=run_id,
            tenant_id=tenant_id,
            eval_items=eval_items,
            metric_names=metric_names,
            skip_empty_contexts=skip_empty_contexts,
            max_cases=max_cases,
            rag_params=rag_params,
            llm_judge_summary=llm_judge_summary,
            total_cases=total_cases,
            mode=mode,
            execution=execution,
        )
    except Exception as exc:
        _persist_run_failure(
            db,
            run_model=RagasRegressionRun,
            run_id=run_id,
            tenant_id=tenant_id,
            message=str(exc),
        )
    finally:
        db.close()
