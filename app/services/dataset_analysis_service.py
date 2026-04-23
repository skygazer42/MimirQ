from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.chat import Conversation, Message
from app.models.feedback import MessageFeedback
from app.rag.evaluation.poc_runner.attribution_classifier import classify_feedback_records
from app.rag.evaluation.poc_runner.coverage_heatmap import build_document_heatmap
from app.rag.evaluation.poc_runner.metrics import compute_feedback_metrics
from app.rag.evaluation.poc_runner.png_tasks import (
    complete_png_export_task,
    create_png_export_task,
    fail_png_export_task,
    get_png_export_task,
    get_png_export_task_result,
)
from app.rag.evaluation.poc_runner.query_pattern_miner import mine_query_patterns
from app.rag.evaluation.poc_runner.reports.attribution_report import build_dataset_analysis_report
from app.rag.evaluation.poc_runner.reports.html_renderer import render_dataset_analysis_html
from app.rag.evaluation.poc_runner.reports.png_renderer import render_dataset_analysis_png
from app.rag.evaluation.poc_runner.reports.umap_scatter import build_umap_scatter
from app.rag.evaluation.poc_runner.source_builder import build_dataset_analysis_sources
from app.rag.evaluation.poc_runner.telemetry import build_poc_interaction_rows
from app.rag.industry_rules.loaders import write_glossary_candidates
from app.services.rag_trace_service import list_rag_traces

_SUMMARY_SCHEMA = "mimirq.dataset_analysis.summary.v1"
_EXAMPLES_SCHEMA = "mimirq.dataset_analysis.examples.v1"
_EXPORT_SCHEMA = "mimirq.dataset_analysis.export.v1"
_GLOSSARY_WRITEBACK_SCHEMA = "mimirq.dataset_analysis.glossary_writeback.v1"


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _coerce_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        try:
            return dict(value.model_dump(mode="json"))
        except Exception:
            return {}
    out: dict[str, Any] = {}
    for key in dir(value):
        if key.startswith("_"):
            continue
        try:
            current = getattr(value, key)
        except Exception:
            continue
        if callable(current):
            continue
        out[key] = current
    return out


def _base_filters_dict(
    *,
    dataset_id: UUID,
    from_ts: str | None,
    to_ts: str | None,
    feedback_polarity: str | None,
    category: str | None,
    limit: int | None = None,
) -> dict[str, Any]:
    payload = {
        "dataset_id": str(dataset_id),
        "from_ts": from_ts,
        "to_ts": to_ts,
        "feedback_polarity": feedback_polarity,
        "category": category,
    }
    if limit is not None:
        payload["limit"] = int(limit)
    return payload


def _definitions() -> dict[str, str]:
    return {
        "all_interactions": "All trace-backed interactions in the selected dataset scope after base filters.",
        "feedback_interactions": "Interactions in scope that have feedback attached.",
        "attributable_feedback_interactions": "Negative-feedback interactions eligible for attribution.",
    }


def _scope_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    feedback_interactions = len([row for row in rows if bool(row.get("has_feedback"))])
    attributable = len([row for row in rows if bool(row.get("attributable_feedback_eligible"))])
    return {
        "all_interactions": len(rows),
        "feedback_interactions": feedback_interactions,
        "attributable_feedback_interactions": attributable,
    }


def _load_dataset_scope_rows(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID,
    from_ts: str | None,
    to_ts: str | None,
    feedback_polarity: str | None,
) -> list[dict[str, Any]]:
    conversations = (
        db.query(Conversation)
        .filter(Conversation.tenant_id == tenant_id, Conversation.dataset_id == dataset_id)
        .all()
    )
    if not conversations:
        return []

    conversation_ids = [conv.id for conv in conversations]
    messages = (
        db.query(Message)
        .filter(Message.tenant_id == tenant_id, Message.conversation_id.in_(conversation_ids))
        .all()
    )
    feedback_rows = (
        db.query(MessageFeedback)
        .filter(MessageFeedback.tenant_id == tenant_id, MessageFeedback.conversation_id.in_(conversation_ids))
        .all()
    )

    from_dt = _coerce_datetime(from_ts)
    to_dt = _coerce_datetime(to_ts)
    if to_dt is None:
        to_dt = datetime.now(UTC)
    if from_dt is None:
        window_minutes = 30 * 24 * 60
    else:
        delta = to_dt - from_dt
        window_minutes = max(60, int(delta.total_seconds() // 60) + 60)

    traces: list[dict[str, Any]] = []
    for conv in conversations:
        try:
            response = list_rag_traces(
                tenant_id=str(tenant_id),
                conversation_id=str(conv.id),
                limit=200,
                window_minutes=window_minutes,
                max_bytes=10_000_000,
            )
        except Exception:
            continue
        for item in getattr(response, "items", []) or []:
            traces.append(_coerce_mapping(item))

    built = build_dataset_analysis_sources(
        traces=traces,
        feedback_rows=[_coerce_mapping(item) for item in feedback_rows],
        conversations=[_coerce_mapping(item) for item in conversations],
        messages=[_coerce_mapping(item) for item in messages],
    )
    rows = build_poc_interaction_rows(built["rows"])

    filtered: list[dict[str, Any]] = []
    wanted_polarity = str(feedback_polarity or "").strip().lower() or None
    for row in rows:
        created_at = _coerce_datetime(row.get("created_at"))
        if from_dt is not None and created_at is not None and created_at < from_dt:
            continue
        if to_dt is not None and created_at is not None and created_at > to_dt:
            continue
        if wanted_polarity and row.get("feedback_polarity") != wanted_polarity:
            continue
        filtered.append(row)
    return filtered


def _build_full_bundle(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID,
    dataset_name: str,
    from_ts: str | None,
    to_ts: str | None,
    feedback_polarity: str | None,
    category: str | None,
    limit: int = 20,
) -> dict[str, Any]:
    rows = _load_dataset_scope_rows(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        from_ts=from_ts,
        to_ts=to_ts,
        feedback_polarity=feedback_polarity,
    )
    attribution = classify_feedback_records(rows, max_examples_per_category=max(1, int(limit or 1)))
    patterns = mine_query_patterns(rows, top_k_keywords=20)
    metrics = compute_feedback_metrics(
        all_interactions=len(rows),
        feedback_interactions=len([row for row in rows if bool(row.get("has_feedback"))]),
        counts=attribution["counts"],
    )

    meta = {
        "filters": _base_filters_dict(
            dataset_id=dataset_id,
            from_ts=from_ts,
            to_ts=to_ts,
            feedback_polarity=feedback_polarity,
            category=category,
            limit=limit,
        ),
        "generated_at": _iso_now(),
        "scope_summary": _scope_summary(rows),
        "schema_version": _EXPORT_SCHEMA,
        "definitions": _definitions(),
        "dataset_name": dataset_name,
    }

    return {
        "meta": meta,
        "metrics": metrics,
        "counts": attribution["counts"],
        "ratios": attribution["ratios"],
        "top_examples": attribution["top_examples"],
        "manual_review_candidates": attribution["manual_review_candidates"],
        "glossary_candidates": patterns["glossary_candidates"],
        "keyword_scores": patterns["keyword_scores"],
        "coverage_heatmap": build_document_heatmap(rows),
        "umap_scatter": build_umap_scatter(rows),
        "rows": rows,
    }


def build_dataset_analysis_summary(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID,
    dataset_name: str,
    from_ts: str | None = None,
    to_ts: str | None = None,
    feedback_polarity: str | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    bundle = _build_full_bundle(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        from_ts=from_ts,
        to_ts=to_ts,
        feedback_polarity=feedback_polarity,
        category=category,
        limit=10,
    )
    bundle["meta"]["schema_version"] = _SUMMARY_SCHEMA
    return {
        "meta": bundle["meta"],
        "metrics": bundle["metrics"],
        "counts": bundle["counts"],
        "ratios": bundle["ratios"],
    }


def build_dataset_analysis_examples(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID,
    dataset_name: str,
    from_ts: str | None = None,
    to_ts: str | None = None,
    feedback_polarity: str | None = None,
    category: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    bundle = _build_full_bundle(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        from_ts=from_ts,
        to_ts=to_ts,
        feedback_polarity=feedback_polarity,
        category=category,
        limit=limit,
    )
    top_examples = bundle["top_examples"]
    if category:
        top_examples = {str(category): list(top_examples.get(str(category), []))[: max(1, int(limit or 1))]}
        manual_review = [
            row for row in bundle["manual_review_candidates"] if str(row.get("category") or "") == str(category)
        ][: max(1, int(limit or 1))]
    else:
        manual_review = list(bundle["manual_review_candidates"])[: max(1, int(limit or 1))]
    bundle["meta"]["schema_version"] = _EXAMPLES_SCHEMA
    return {
        "meta": bundle["meta"],
        "top_examples": top_examples,
        "manual_review_candidates": manual_review,
        "glossary_candidates": bundle["glossary_candidates"][: max(1, int(limit or 1))],
    }


def export_dataset_analysis_json(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID,
    dataset_name: str,
    from_ts: str | None = None,
    to_ts: str | None = None,
    feedback_polarity: str | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    bundle = _build_full_bundle(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        from_ts=from_ts,
        to_ts=to_ts,
        feedback_polarity=feedback_polarity,
        category=category,
        limit=20,
    )
    bundle["meta"]["schema_version"] = _EXPORT_SCHEMA
    return bundle


def export_dataset_analysis_jsonl(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID,
    dataset_name: str,
    from_ts: str | None = None,
    to_ts: str | None = None,
    feedback_polarity: str | None = None,
    category: str | None = None,
) -> str:
    bundle = _build_full_bundle(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        from_ts=from_ts,
        to_ts=to_ts,
        feedback_polarity=feedback_polarity,
        category=category,
        limit=20,
    )
    lines = [json.dumps(row, ensure_ascii=False, sort_keys=True) for row in bundle["rows"]]
    return "".join(f"{line}\n" for line in lines)


def export_dataset_analysis_html(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID,
    dataset_name: str,
    from_ts: str | None = None,
    to_ts: str | None = None,
    feedback_polarity: str | None = None,
    category: str | None = None,
) -> str:
    bundle = _build_full_bundle(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        from_ts=from_ts,
        to_ts=to_ts,
        feedback_polarity=feedback_polarity,
        category=category,
        limit=20,
    )
    report = build_dataset_analysis_report(
        dataset_id=str(dataset_id),
        dataset_name=dataset_name,
        filters=bundle["meta"]["filters"],
        scope_summary=bundle["meta"]["scope_summary"],
        metrics=bundle["metrics"],
        counts=bundle["counts"],
        ratios=bundle["ratios"],
        top_examples=bundle["top_examples"],
        manual_review_candidates=bundle["manual_review_candidates"],
        glossary_candidates=bundle["glossary_candidates"],
        keyword_scores=bundle["keyword_scores"],
        coverage_heatmap=bundle["coverage_heatmap"],
        umap_scatter=bundle["umap_scatter"],
    )
    report["meta"]["definitions"] = bundle["meta"]["definitions"]
    return render_dataset_analysis_html(report)


def writeback_dataset_analysis_glossary_candidates(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID,
    dataset_name: str,
    ruleset_name: str,
    from_ts: str | None = None,
    to_ts: str | None = None,
    feedback_polarity: str | None = None,
    category: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    bundle = _build_full_bundle(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        from_ts=from_ts,
        to_ts=to_ts,
        feedback_polarity=feedback_polarity,
        category=category,
        limit=limit,
    )
    selected_candidates = list(bundle["glossary_candidates"])[: max(1, int(limit or 1))]
    result = write_glossary_candidates(ruleset_name, selected_candidates)
    return {
        "schema": _GLOSSARY_WRITEBACK_SCHEMA,
        "dataset_id": str(dataset_id),
        "dataset_name": dataset_name,
        "ruleset": str(ruleset_name or "").strip(),
        "filters": bundle["meta"]["filters"],
        "candidate_count": int(result["candidate_count"]),
        "added_count": int(result["added_count"]),
        "skipped_count": int(result["skipped_count"]),
        "added_tokens": list(result["added_tokens"]),
        "skipped_tokens": list(result["skipped_tokens"]),
        "generated_path": result["generated_path"],
    }


def create_dataset_analysis_png_task(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID,
    dataset_name: str,
    background_tasks: Any,
    from_ts: str | None = None,
    to_ts: str | None = None,
    feedback_polarity: str | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    task = create_png_export_task(
        dataset_id=str(dataset_id),
        filters=_base_filters_dict(
            dataset_id=dataset_id,
            from_ts=from_ts,
            to_ts=to_ts,
            feedback_polarity=feedback_polarity,
            category=category,
        ),
    )

    def _run() -> None:
        bg_db = SessionLocal()
        try:
            bundle = _build_full_bundle(
                db=bg_db,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                dataset_name=dataset_name,
                from_ts=from_ts,
                to_ts=to_ts,
                feedback_polarity=feedback_polarity,
                category=category,
                limit=20,
            )
            report = build_dataset_analysis_report(
                dataset_id=str(dataset_id),
                dataset_name=dataset_name,
                filters=bundle["meta"]["filters"],
                scope_summary=bundle["meta"]["scope_summary"],
                metrics=bundle["metrics"],
                counts=bundle["counts"],
                ratios=bundle["ratios"],
                top_examples=bundle["top_examples"],
                manual_review_candidates=bundle["manual_review_candidates"],
                glossary_candidates=bundle["glossary_candidates"],
                keyword_scores=bundle["keyword_scores"],
                coverage_heatmap=bundle["coverage_heatmap"],
                umap_scatter=bundle["umap_scatter"],
            )
            report["meta"]["definitions"] = bundle["meta"]["definitions"]
            payload = render_dataset_analysis_png(report)
            complete_png_export_task(task["task_id"], payload)
        except Exception as exc:  # noqa: BLE001
            fail_png_export_task(task["task_id"], str(exc))
        finally:
            bg_db.close()

    background_tasks.add_task(_run)
    return task


def get_dataset_analysis_png_task_status(*, task_id: str) -> dict[str, Any]:
    return get_png_export_task(task_id)


def get_dataset_analysis_png_result(*, task_id: str) -> bytes:
    return get_png_export_task_result(task_id)
