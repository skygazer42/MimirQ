
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.rag.core.hashing import stable_hash
from app.rag.evaluation.replay_capture import sanitize_citations_for_capture

REGRESSION_RUN_BUNDLE_SCHEMA_V1 = "mimirq.ragas_regression_run_bundle.v1"


def _dt_to_json(v: Any) -> str | None:
    if v is None:
        return None
    try:
        # Accept datetime-like objects.
        if hasattr(v, "isoformat"):
            s = v.isoformat()
        else:
            return None
    except Exception:
        return None
    if s.endswith("+00:00"):
        s = s[:-6] + "Z"
    return s


def _coerce_uuid_str(v: Any) -> str | None:
    if v is None:
        return None
    try:
        return str(UUID(str(v)))
    except Exception:
        return None


def _hash_uuid_str(v: Any, *, length: int = 16) -> str | None:
    s = _coerce_uuid_str(v)
    if not s:
        return None
    return stable_hash(s, length=int(length or 16))


def _coerce_dict(v: Any) -> dict[str, Any]:
    return dict(v) if isinstance(v, dict) else {}


def _coerce_list(v: Any) -> list[Any]:
    return list(v) if isinstance(v, list) else []


def export_regression_run_bundle(
    run: Any,
    items: Sequence[Any],
    *,
    include_text: bool = False,
    include_contexts: bool = False,
    redact_ids: bool = True,
    max_items: int = 500,
    max_citations: int = 80,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Export a regression run bundle (PII-safe by default).

    Default behavior:
    - includes only question/response hashes + lengths (no raw text)
    - includes only allowlisted citation keys (no chunk_content / document_name / etc)

    When include_text=true:
    - includes raw question/response (may include PII)

    When include_contexts=true:
    - includes retrieved_contexts (must also set include_text=true; contexts are inherently PII-sensitive)
    """
    if include_contexts and not include_text:
        raise ValueError("include_contexts requires include_text=true")

    try:
        max_items_i = max(1, min(int(max_items or 0), 5000))
    except Exception:
        max_items_i = 500
    try:
        max_citations_i = max(0, min(int(max_citations or 0), 500))
    except Exception:
        max_citations_i = 80

    run_id = _coerce_uuid_str(getattr(run, "id", None))
    tenant_id = _coerce_uuid_str(getattr(run, "tenant_id", None))
    dataset_id = _coerce_uuid_str(getattr(run, "dataset_id", None))
    run_id_hash = _hash_uuid_str(run_id)
    tenant_id_hash = _hash_uuid_str(tenant_id)
    dataset_id_hash = _hash_uuid_str(dataset_id)

    out_items: list[dict[str, Any]] = []
    for raw in list(items or [])[:max_items_i]:
        case_id = _coerce_uuid_str(getattr(raw, "case_id", None))
        case_id_hash = _hash_uuid_str(case_id)
        question = str(getattr(raw, "question", "") or "")
        response = str(getattr(raw, "response", "") or "")

        rec: dict[str, Any] = {
            "case_id": case_id if not redact_ids else None,
            "case_id_hash": case_id_hash if redact_ids else None,
            "question_hash": stable_hash(question, length=16) if question else None,
            "question_chars": int(len(question)) if question else 0,
            "response_hash": stable_hash(response, length=16) if response else None,
            "response_chars": int(len(response)) if response else 0,
            "scores": _coerce_dict(getattr(raw, "scores", None)),
            "meta": _coerce_dict(getattr(raw, "meta", None)),
            "citations": sanitize_citations_for_capture(getattr(raw, "citations", None), max_items=max_citations_i),
            "created_at": _dt_to_json(getattr(raw, "created_at", None)),
        }

        if include_text:
            rec["question"] = question
            rec["response"] = response
        if include_contexts:
            rec["retrieved_contexts"] = _coerce_list(getattr(raw, "retrieved_contexts", None))

        # Drop None keys to keep the payload compact.
        out_items.append({k: v for k, v in rec.items() if v is not None})

    # Stable ordering for diffs.
    out_items.sort(
        key=lambda it: (
            str(it.get("case_id_hash") or it.get("case_id") or ""),
            str(it.get("question_hash") or ""),
        )
    )

    run_payload: dict[str, Any] = {
        "id": run_id if not redact_ids else None,
        "id_hash": run_id_hash if redact_ids else None,
        "tenant_id": tenant_id if not redact_ids else None,
        "tenant_id_hash": tenant_id_hash if redact_ids else None,
        "dataset_id": dataset_id if not redact_ids else None,
        "dataset_id_hash": dataset_id_hash if redact_ids else None,
        "status": str(getattr(run, "status", "") or ""),
        "metrics": _coerce_list(getattr(run, "metrics", None)),
        "params": _coerce_dict(getattr(run, "params", None)),
        "summary": _coerce_dict(getattr(run, "summary", None)),
        "error_message": getattr(run, "error_message", None),
        "created_at": _dt_to_json(getattr(run, "created_at", None)),
        "started_at": _dt_to_json(getattr(run, "started_at", None)),
        "finished_at": _dt_to_json(getattr(run, "finished_at", None)),
    }
    run_payload = {k: v for k, v in run_payload.items() if v is not None}

    now0 = now or datetime.now(UTC)

    return {
        "schema": REGRESSION_RUN_BUNDLE_SCHEMA_V1,
        "generated_at": _dt_to_json(now0),
        "run": run_payload,
        "items": out_items,
    }


__all__ = ["REGRESSION_RUN_BUNDLE_SCHEMA_V1", "export_regression_run_bundle"]
