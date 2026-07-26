
import json
import threading
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.exceptions import MimirQError
from app.models.chat import Conversation, Message
from app.models.dataset import Dataset
from app.models.feedback import MessageFeedback
from app.rag.core.logging import get_logger
from app.rag.evaluation.poc_runner.attribution_classifier import classify_feedback_records
from app.rag.evaluation.poc_runner.coverage_heatmap import build_document_heatmap
from app.rag.evaluation.poc_runner.latency_decomposer import decompose_latency_rows
from app.rag.evaluation.poc_runner.metrics import compute_feedback_metrics
from app.rag.evaluation.poc_runner.png_tasks import (
    begin_png_export_task,
    complete_png_export_task,
    create_png_export_task,
    fail_png_export_task,
    get_png_export_task,
    get_png_export_task_heartbeat_interval_sec,
    get_png_export_task_result,
    heartbeat_png_export_task,
)
from app.rag.evaluation.poc_runner.query_pattern_miner import mine_query_patterns
from app.rag.evaluation.poc_runner.reports.attribution_report import (
    DatasetAnalysisReportPayload,
    build_dataset_analysis_report,
)
from app.rag.evaluation.poc_runner.reports.html_renderer import render_dataset_analysis_html
from app.rag.evaluation.poc_runner.reports.png_renderer import render_dataset_analysis_png
from app.rag.evaluation.poc_runner.reports.umap_scatter import build_umap_scatter
from app.rag.evaluation.poc_runner.source_builder import build_dataset_analysis_sources
from app.rag.evaluation.poc_runner.telemetry import build_poc_interaction_rows
from app.rag.industry_rules import load_ruleset
from app.rag.industry_rules.loaders import write_glossary_candidates
from app.rag.industry_rules.mining.auto_rules import build_ruleset_suggestions
from app.services.dataset_service import DatasetService
from app.services.rag_trace_service import list_rag_traces

_SUMMARY_SCHEMA = "mimirq.dataset_analysis.summary.v1"
_EXAMPLES_SCHEMA = "mimirq.dataset_analysis.examples.v1"
_EXPORT_SCHEMA = "mimirq.dataset_analysis.export.v1"
_GLOSSARY_WRITEBACK_SCHEMA = "mimirq.dataset_analysis.glossary_writeback.v1"
_DASHBOARD_SCHEMA = "mimirq.dataset_analysis.dashboard.v1"


class DatasetAnalysisSourceIncompleteError(MimirQError):
    def __init__(
        self,
        *,
        dataset_id: str,
        failed_conversation_ids: list[str] | None = None,
    ) -> None:
        detail = {
            "dataset_id": str(dataset_id or ""),
            "failed_conversation_ids": list(failed_conversation_ids or []),
        }
        super().__init__(
            message="Dataset analysis sources are incomplete",
            error_code="source_incomplete",
            status_code=503,
            detail=detail,
        )


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
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
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
    trace_failures: list[str] = []
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
            trace_failures.append(str(conv.id))
            get_logger(__name__).warning(
                "Dataset analysis trace load failed for conversation_id=%s dataset_id=%s",
                str(conv.id),
                str(dataset_id),
                exc_info=True,
            )
            continue
        for item in getattr(response, "items", []) or []:
            traces.append(_coerce_mapping(item))

    if trace_failures:
        raise DatasetAnalysisSourceIncompleteError(
            dataset_id=str(dataset_id),
            failed_conversation_ids=trace_failures,
        )

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
        "latency_breakdown": decompose_latency_rows(rows),
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


def build_dataset_analysis_rule_suggestions(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID,
    dataset_name: str,
    ruleset_name: str,
    from_ts: str | None = None,
    to_ts: str | None = None,
    feedback_polarity: str | None = None,
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
    ruleset = load_ruleset(ruleset_name)
    out = build_ruleset_suggestions(rows, ruleset=ruleset, top_k=limit)
    out["dataset_id"] = str(dataset_id)
    out["dataset_name"] = dataset_name
    out["ruleset"] = ruleset_name
    return out


def build_tenant_dataset_analysis_dashboard(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    from_ts: str | None = None,
    to_ts: str | None = None,
    feedback_polarity: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    DatasetService.ensure_member(db, tenant_id, account_id)
    rows = (
        db.query(Dataset)
        .filter(Dataset.tenant_id == tenant_id)
        .order_by(Dataset.name.asc())
        .all()
    )

    cards: list[dict[str, Any]] = []
    summary = {
        "all_interactions": 0,
        "feedback_interactions": 0,
        "attributable_feedback_interactions": 0,
        "retrieval_miss": 0,
        "generation_error": 0,
        "out_of_scope": 0,
    }

    for dataset in rows:
        if not DatasetService.check_dataset_permission(db, dataset, account_id):
            continue
        payload = build_dataset_analysis_summary(
            db=db,
            tenant_id=tenant_id,
            dataset_id=dataset.id,
            dataset_name=str(getattr(dataset, "name", "") or ""),
            from_ts=from_ts,
            to_ts=to_ts,
            feedback_polarity=feedback_polarity,
            category=None,
        )
        meta = dict(payload.get("meta") or {})
        scope_summary = dict(meta.get("scope_summary") or {})
        counts = dict(payload.get("counts") or {})
        metrics = dict(payload.get("metrics") or {})

        summary["all_interactions"] += int(scope_summary.get("all_interactions") or 0)
        summary["feedback_interactions"] += int(scope_summary.get("feedback_interactions") or 0)
        summary["attributable_feedback_interactions"] += int(scope_summary.get("attributable_feedback_interactions") or 0)
        summary["retrieval_miss"] += int(counts.get("retrieval_miss") or 0)
        summary["generation_error"] += int(counts.get("generation_error") or 0)
        summary["out_of_scope"] += int(counts.get("out_of_scope") or 0)

        cards.append(
            {
                "dataset_id": str(dataset.id),
                "dataset_name": str(getattr(dataset, "name", "") or ""),
                "scope_summary": scope_summary,
                "metrics": metrics,
                "counts": counts,
                "ratios": dict(payload.get("ratios") or {}),
            }
        )
        if len(cards) >= max(1, int(limit or 1)):
            break

    return {
        "schema": _DASHBOARD_SCHEMA,
        "tenant_id": str(tenant_id),
        "dataset_count": int(len(cards)),
        "summary": summary,
        "datasets": cards,
        "filters": {
            "from_ts": from_ts,
            "to_ts": to_ts,
            "feedback_polarity": feedback_polarity,
            "limit": int(limit or 0),
        },
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
    report = build_dataset_analysis_report(DatasetAnalysisReportPayload(
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
        latency_breakdown=bundle["latency_breakdown"],
    ))
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
    del db  # background task owns its own session

    task = create_png_export_task(
        tenant_id=str(tenant_id),
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
        owner_token: str | None = None
        heartbeat_stop = threading.Event()
        heartbeat_state: dict[str, Any] = {"reason": None, "error": None}
        heartbeat_thread: threading.Thread | None = None

        def _heartbeat_loop() -> None:
            if not owner_token:
                return
            interval_sec = get_png_export_task_heartbeat_interval_sec()
            while not heartbeat_stop.wait(interval_sec):
                try:
                    renewed = heartbeat_png_export_task(
                        task["task_id"],
                        tenant_id=str(tenant_id),
                        dataset_id=str(dataset_id),
                        owner_token=owner_token,
                    )
                except Exception as exc:  # noqa: BLE001
                    heartbeat_state["reason"] = "shared_state_unavailable"
                    heartbeat_state["error"] = str(exc)
                    heartbeat_stop.set()
                    return
                if not renewed:
                    heartbeat_state["reason"] = "ownership_lost"
                    heartbeat_stop.set()
                    return

        try:
            started = begin_png_export_task(
                task["task_id"],
                tenant_id=str(tenant_id),
                dataset_id=str(dataset_id),
            )
            owner_token = str(started.get("owner_token") or "")
            heartbeat_thread = threading.Thread(
                target=_heartbeat_loop,
                name=f"dataset-analysis-png-heartbeat-{task['task_id'][:8]}",
                daemon=True,
            )
            heartbeat_thread.start()
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
            report = build_dataset_analysis_report(DatasetAnalysisReportPayload(
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
                latency_breakdown=bundle["latency_breakdown"],
            ))
            report["meta"]["definitions"] = bundle["meta"]["definitions"]
            payload = render_dataset_analysis_png(report)
            if heartbeat_state.get("reason") == "shared_state_unavailable":
                fail_png_export_task(
                    task["task_id"],
                    tenant_id=str(tenant_id),
                    dataset_id=str(dataset_id),
                    owner_token=owner_token,
                    error=str(heartbeat_state.get("error") or "PNG export shared state unavailable"),
                    error_code="shared_state_unavailable",
                )
                return
            if heartbeat_state.get("reason") == "ownership_lost":
                return
            complete_png_export_task(
                task["task_id"],
                tenant_id=str(tenant_id),
                dataset_id=str(dataset_id),
                owner_token=owner_token,
                png_bytes=payload,
            )
        except DatasetAnalysisSourceIncompleteError as exc:
            if owner_token:
                fail_png_export_task(
                    task["task_id"],
                    tenant_id=str(tenant_id),
                    dataset_id=str(dataset_id),
                    owner_token=owner_token,
                    error=str(exc.message),
                    error_code="source_incomplete",
                )
        except Exception as exc:  # noqa: BLE001
            if owner_token:
                if heartbeat_state.get("reason") == "shared_state_unavailable":
                    fail_png_export_task(
                        task["task_id"],
                        tenant_id=str(tenant_id),
                        dataset_id=str(dataset_id),
                        owner_token=owner_token,
                        error=str(heartbeat_state.get("error") or exc),
                        error_code="shared_state_unavailable",
                    )
                else:
                    fail_png_export_task(
                        task["task_id"],
                        tenant_id=str(tenant_id),
                        dataset_id=str(dataset_id),
                        owner_token=owner_token,
                        error=str(exc),
                        error_code="render_failed",
                    )
        finally:
            heartbeat_stop.set()
            if heartbeat_thread is not None:
                heartbeat_thread.join(timeout=max(1.0, get_png_export_task_heartbeat_interval_sec() * 2.0))
            bg_db.close()

    background_tasks.add_task(_run)
    return task


def get_dataset_analysis_png_task_status(*, task_id: str, tenant_id: UUID, dataset_id: UUID) -> dict[str, Any]:
    return get_png_export_task(
        task_id,
        tenant_id=str(tenant_id),
        dataset_id=str(dataset_id),
    )


def get_dataset_analysis_png_result(*, task_id: str, tenant_id: UUID, dataset_id: UUID) -> bytes:
    return get_png_export_task_result(
        task_id,
        tenant_id=str(tenant_id),
        dataset_id=str(dataset_id),
    )
