
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from app.models.chat import Conversation, Message
from app.models.evidence import EvidenceItem, EvidenceSuite
from app.models.feedback import MessageFeedback
from app.rag.core.logging import get_logger


def _now_utc_iso() -> str:
    return datetime.now(UTC).isoformat()


_DEFAULT_LTR_ROLLOUT_GATE_THRESHOLDS: dict[str, Any] = {
    "schema": "mimirq.ltr_rollout_gate_thresholds.v1",
    "metrics": {
        "delta.hit": {"min": 0.0},
        "delta.mrr": {"min": 0.0},
        "delta.recall": {"min": 0.0},
        "delta.ndcg": {"min": 0.0},
        "candidate.cases_used": {"min": 1.0},
    },
}
_DEFAULT_LTR_ROLLOUT_GATE_POLICY_PROFILE: dict[str, Any] = {
    "schema": "mimirq.ltr_rollout_gate_policy_profile.v1",
    "levels": {
        "pass": {"max_failed_checks": 0, "canary_ratio": 0.2},
        "warn": {"max_failed_checks": 1, "canary_ratio": 0.05},
        "block": {"max_failed_checks": 9999, "canary_ratio": 0.0},
    },
}


def _safe_uuid_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        text = str(value).strip()
        if not text:
            return None
        return str(UUID(text))
    except Exception:
        return None


def _safe_text(value: Any, *, max_len: int = 2000) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[: max(1, int(max_len or 1))]


def _safe_int(value: Any, *, min_value: int | None = None) -> int | None:
    try:
        if value is None:
            return None
        out = int(value)
    except Exception:
        return None
    if min_value is not None and out < min_value:
        return None
    return out


def _safe_float(value: Any, *, min_value: float | None = None, max_value: float | None = None) -> float | None:
    try:
        if value is None:
            return None
        out = float(value)
    except Exception:
        return None
    if min_value is not None and out < min_value:
        return None
    if max_value is not None and out > max_value:
        return None
    return out


def _normalize_tags(values: Sequence[Any] | None, *, prefixes: Sequence[str] | None = None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in list(prefixes or []) + list(values or []):
        text = str(raw or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text[:64])
        if len(out) >= 30:
            break
    return out


def _normalized_reference_source_identity(item: dict[str, Any]) -> tuple[str, str] | None:
    document_id = _safe_uuid_text(item.get("document_id"))
    chunk_id = _safe_uuid_text(item.get("chunk_id"))
    if not document_id or not chunk_id:
        return None
    return document_id, chunk_id


def _normalized_reference_source_payload(item: dict[str, Any], *, document_id: str, chunk_id: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "document_id": document_id,
        "chunk_id": chunk_id,
    }
    for field_name, min_value in (
        ("page_number", 1),
        ("start_char", 0),
        ("end_char", 0),
        ("chunk_index", 0),
    ):
        value_int = _safe_int(item.get(field_name), min_value=min_value)
        if value_int is not None:
            payload[field_name] = value_int
    for field_name, max_len in (
        ("doc_pipeline_key", 128),
        ("pipeline_hash", 128),
        ("quote", 2000),
        ("label", 128),
    ):
        text = _safe_text(item.get(field_name), max_len=max_len)
        if text:
            payload[field_name] = text
    return payload


def normalize_reference_sources(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        identity = _normalized_reference_source_identity(item)
        if identity is None:
            continue
        key = identity
        if key in seen:
            continue
        seen.add(key)
        out.append(_normalized_reference_source_payload(item, document_id=key[0], chunk_id=key[1]))
        if len(out) >= 100:
            break
    return out


@dataclass(frozen=True)
class FeedbackCaseMaterialization:
    feedback_id: str
    dataset_id: str | None
    question: str
    expected_answer: str | None
    reference_sources: list[dict[str, Any]]
    tags: list[str]
    extra: dict[str, Any]


def materialize_feedback_case(
    *,
    feedback: MessageFeedback,
    assistant: Message,
    conversation: Conversation,
    user_message: Message | None,
    trace_payload: dict[str, Any] | None = None,
) -> FeedbackCaseMaterialization:
    meta = assistant.message_metadata if isinstance(getattr(assistant, "message_metadata", None), dict) else {}
    dataset_id = _safe_uuid_text(meta.get("dataset_id")) or _safe_uuid_text(getattr(conversation, "dataset_id", None))
    request_id = str(meta.get("request_id") or "").strip()

    question = str(getattr(user_message, "content", "") or "").strip() or "(missing user question)"
    reference_sources = normalize_reference_sources(getattr(assistant, "citations", None))
    if not reference_sources and isinstance(trace_payload, dict):
        reference_sources = normalize_reference_sources(trace_payload.get("citations"))

    tags = _normalize_tags(getattr(feedback, "tags", None))
    extra = dict(getattr(feedback, "extra", {}) or {})
    extra.setdefault("source", "feedback")
    extra.setdefault("feedback_id", str(feedback.id))
    extra.setdefault("message_id", str(feedback.message_id))
    extra.setdefault("rating", int(getattr(feedback, "rating", 0) or 0))
    if request_id:
        extra["retrieval_trace_request_id"] = request_id
    if isinstance(trace_payload, dict) and trace_payload:
        extra["retrieval_trace"] = dict(trace_payload)

    return FeedbackCaseMaterialization(
        feedback_id=str(feedback.id),
        dataset_id=dataset_id,
        question=question,
        expected_answer=_safe_text(getattr(feedback, "expected_answer", None), max_len=20_000),
        reference_sources=reference_sources,
        tags=tags,
        extra=extra,
    )


def _dataset_text(value: UUID | str | None) -> str:
    if value is None:
        raise ValueError("dataset_id is required")
    return str(value)


def build_rollout_regression_bundle(
    *,
    dataset_id: UUID | str,
    suite: EvidenceSuite | None,
    evidence_items: Sequence[EvidenceItem] | None,
    feedback_cases: Sequence[FeedbackCaseMaterialization] | None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    dataset_text = _dataset_text(dataset_id)
    if suite is not None and str(suite.dataset_id) != dataset_text:
        raise ValueError("dataset_id mismatch between suite and workflow request")

    items_out: list[dict[str, Any]] = []
    approved_evidence_items = 0
    selected_feedback_cases = 0

    for item in (evidence_items or []):
        if str(getattr(item, "status", "") or "").strip().lower() != "approved":
            continue
        if str(getattr(item, "dataset_id", "") or "") != dataset_text:
            raise ValueError("dataset_id mismatch for evidence item")
        refs = normalize_reference_sources(getattr(item, "reference_sources", None))
        if not refs:
            continue
        approved_evidence_items += 1
        items_out.append(
            {
                "question": str(getattr(item, "query", "") or "").strip(),
                "expected_answer": getattr(item, "expected_answer", None),
                "reference_sources": refs,
                "tags": _normalize_tags(
                    getattr(item, "tags", None),
                    prefixes=[
                        "evidence_suite",
                        f"evidence_suite:{str(suite.id)}" if suite is not None else "evidence_suite",
                    ],
                ),
                "extra": {
                    "source": "evidence_suite",
                    "evidence_suite_id": str(suite.id) if suite is not None else None,
                    "evidence_item_id": str(item.id),
                    "status": "approved",
                },
            }
        )

    for case in (feedback_cases or []):
        if case.dataset_id and case.dataset_id != dataset_text:
            raise ValueError("dataset_id mismatch for feedback case")
        refs = normalize_reference_sources(case.reference_sources)
        if not refs:
            continue
        selected_feedback_cases += 1
        extra = dict(case.extra or {})
        extra.setdefault("source", "feedback")
        extra.setdefault("feedback_id", str(case.feedback_id))
        items_out.append(
            {
                "question": str(case.question or "").strip(),
                "expected_answer": case.expected_answer,
                "reference_sources": refs,
                "tags": _normalize_tags(case.tags, prefixes=["feedback", f"feedback:{str(case.feedback_id)}"]),
                "extra": extra,
            }
        )

    if not items_out:
        raise ValueError("no rollout cases could be materialized")

    return {
        "schema": "mimirq.regression_cases.v1",
        "dataset_id": dataset_text,
        "generated_at": generated_at or _now_utc_iso(),
        "source_summary": {
            "approved_evidence_items": int(approved_evidence_items),
            "selected_feedback_cases": int(selected_feedback_cases),
            "total_items": int(len(items_out)),
        },
        "items": items_out,
    }


def _metric_map(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in raw.items():
        try:
            out[str(key)] = round(float(value), 4)
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
    return out


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _normalize_gate_bound(value: Any) -> dict[str, float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"min": float(value)}
    if not isinstance(value, dict):
        return {}
    out: dict[str, float] = {}
    if "min" in value:
        mn = _as_float(value.get("min"))
        if mn is not None:
            out["min"] = mn
    if "max" in value:
        mx = _as_float(value.get("max"))
        if mx is not None:
            out["max"] = mx
    return out


def normalize_ltr_rollout_gate_thresholds(raw: Any | None) -> dict[str, Any]:
    payload = raw if isinstance(raw, dict) else {}
    metric_payload = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else payload
    metrics: dict[str, dict[str, float]] = {}
    if isinstance(metric_payload, dict):
        for key, value in metric_payload.items():
            metric_name = str(key or "").strip()
            if not metric_name:
                continue
            bounds = _normalize_gate_bound(value)
            if bounds:
                metrics[metric_name] = bounds
    if not metrics:
        for key, value in (_DEFAULT_LTR_ROLLOUT_GATE_THRESHOLDS.get("metrics") or {}).items():
            bounds = _normalize_gate_bound(value)
            if bounds:
                metrics[str(key)] = bounds

    raw_policy = payload.get("policy_profile")
    policy_profile = normalize_ltr_rollout_gate_policy_profile(raw_policy)
    return {
        "schema": "mimirq.ltr_rollout_gate_thresholds.v1",
        "metrics": metrics,
        "policy_profile": policy_profile,
    }


def normalize_ltr_rollout_gate_policy_profile(raw: Any | None) -> dict[str, Any]:
    payload = raw if isinstance(raw, dict) else {}
    levels_payload = payload.get("levels") if isinstance(payload.get("levels"), dict) else payload

    levels: dict[str, dict[str, Any]] = {}
    for level in ("pass", "warn", "block"):
        cur = levels_payload.get(level) if isinstance(levels_payload, dict) else None
        base = (
            _DEFAULT_LTR_ROLLOUT_GATE_POLICY_PROFILE.get("levels", {}).get(level)
            if isinstance(_DEFAULT_LTR_ROLLOUT_GATE_POLICY_PROFILE.get("levels"), dict)
            else {}
        )
        source = cur if isinstance(cur, dict) else {}
        max_failed = _safe_int(source.get("max_failed_checks"), min_value=0)
        if max_failed is None:
            max_failed = _safe_int((base or {}).get("max_failed_checks"), min_value=0) or 0
        canary_ratio = _safe_float(source.get("canary_ratio"), min_value=0.0, max_value=1.0)
        if canary_ratio is None:
            canary_ratio = _safe_float((base or {}).get("canary_ratio"), min_value=0.0, max_value=1.0) or 0.0
        levels[level] = {
            "max_failed_checks": int(max_failed),
            "canary_ratio": round(float(canary_ratio), 4),
        }

    # Ensure monotonic boundaries: pass <= warn <= block.
    pass_max = int(levels["pass"]["max_failed_checks"])
    warn_max = int(levels["warn"]["max_failed_checks"])
    block_max = int(levels["block"]["max_failed_checks"])
    if warn_max < pass_max:
        warn_max = pass_max
    if block_max < warn_max:
        block_max = warn_max
    levels["warn"]["max_failed_checks"] = int(warn_max)
    levels["block"]["max_failed_checks"] = int(block_max)

    return {
        "schema": "mimirq.ltr_rollout_gate_policy_profile.v1",
        "levels": levels,
    }


def _evaluate_gate_policy_decision(*, failed_checks: int, policy_profile: dict[str, Any]) -> dict[str, Any]:
    levels = policy_profile.get("levels") if isinstance(policy_profile.get("levels"), dict) else {}
    pass_cfg = levels.get("pass") if isinstance(levels.get("pass"), dict) else {}
    warn_cfg = levels.get("warn") if isinstance(levels.get("warn"), dict) else {}
    block_cfg = levels.get("block") if isinstance(levels.get("block"), dict) else {}

    pass_max = _safe_int(pass_cfg.get("max_failed_checks"), min_value=0)
    warn_max = _safe_int(warn_cfg.get("max_failed_checks"), min_value=0)
    if pass_max is None:
        pass_max = 0
    if warn_max is None:
        warn_max = max(pass_max, 1)

    if failed_checks <= pass_max:
        level = "pass"
        ratio = _safe_float(pass_cfg.get("canary_ratio"), min_value=0.0, max_value=1.0) or 0.0
    elif failed_checks <= warn_max:
        level = "warn"
        ratio = _safe_float(warn_cfg.get("canary_ratio"), min_value=0.0, max_value=1.0) or 0.0
    else:
        level = "block"
        ratio = _safe_float(block_cfg.get("canary_ratio"), min_value=0.0, max_value=1.0) or 0.0

    return {
        "schema": "mimirq.ltr_rollout_gate_decision.v1",
        "level": level,
        "failed_checks": int(max(0, int(failed_checks or 0))),
        "canary_ratio": round(float(ratio), 4),
    }


def _comparison_metric_root_value(*, comparison: dict[str, Any], root: str, key: str) -> float | None:
    metric_groups = {
        "candidate": ("candidate_metrics", "candidate_eval_summary"),
        "baseline": ("baseline_metrics", "baseline_eval_summary"),
    }
    if root in {"delta", "deltas"}:
        return _as_float((comparison.get("deltas") or {}).get(key))
    groups = metric_groups.get(root)
    if groups is None:
        return None
    metrics_key, summary_key = groups
    if key in {"hit", "mrr", "recall", "ndcg"}:
        return _as_float((comparison.get(metrics_key) or {}).get(key))
    if key.startswith("cases_"):
        return _as_float((comparison.get(summary_key) or {}).get(key))
    return None


def _comparison_nested_metric_value(*, comparison: dict[str, Any], parts: list[str]) -> float | None:
    current: Any = comparison
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return _as_float(current)


def _comparison_metric_value(*, comparison: dict[str, Any], metric_key: str) -> float | None:
    parts = [p.strip() for p in str(metric_key or "").split(".") if p.strip()]
    if not parts:
        return None
    root = parts[0]
    key = ".".join(parts[1:])
    direct_value = _comparison_metric_root_value(comparison=comparison, root=root, key=key)
    if direct_value is not None:
        return direct_value
    return _comparison_nested_metric_value(comparison=comparison, parts=parts)


def evaluate_ltr_rollout_gate(
    *,
    comparison: dict[str, Any],
    thresholds: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_ltr_rollout_gate_thresholds(thresholds)
    reasons: list[str] = []
    checks: list[dict[str, Any]] = []

    metrics = normalized.get("metrics") if isinstance(normalized.get("metrics"), dict) else {}
    for metric_name, bounds in metrics.items():
        metric = str(metric_name or "").strip()
        if not metric:
            continue
        metric_bounds = bounds if isinstance(bounds, dict) else {}
        actual = _comparison_metric_value(comparison=comparison, metric_key=metric)
        if actual is None:
            checks.append({"metric": metric, "passed": False, "actual": None, "bounds": dict(metric_bounds)})
            reasons.append(f"missing metric: {metric}")
            continue

        passed = True
        lower = _as_float(metric_bounds.get("min"))
        upper = _as_float(metric_bounds.get("max"))
        if lower is not None and actual < lower:
            passed = False
            reasons.append(f"{metric}={actual:.4f} < min {lower:.4f}")
        if upper is not None and actual > upper:
            passed = False
            reasons.append(f"{metric}={actual:.4f} > max {upper:.4f}")

        checks.append(
            {
                "metric": metric,
                "passed": bool(passed),
                "actual": round(float(actual), 4),
                "bounds": {k: round(float(v), 4) for k, v in metric_bounds.items() if _as_float(v) is not None},
            }
        )

    failed = sum(1 for item in checks if not bool(item.get("passed")))
    summary = {
        "total": int(len(checks)),
        "passed": int(len(checks) - failed),
        "failed": int(failed),
    }
    policy_profile = normalized.get("policy_profile") if isinstance(normalized.get("policy_profile"), dict) else {}
    decision = _evaluate_gate_policy_decision(failed_checks=int(failed), policy_profile=policy_profile)
    gate_passed = str(decision.get("level") or "").strip().lower() == "pass"

    return {
        "schema": "mimirq.ltr_rollout_gate_result.v1",
        "generated_at": generated_at or _now_utc_iso(),
        "passed": bool(gate_passed),
        "summary": summary,
        "reasons": reasons,
        "checks": checks,
        "decision": decision,
        "thresholds": normalized,
    }


def build_rollout_comparison(
    *,
    generated_at: str | None,
    candidate_eval: dict[str, Any],
    baseline_eval: dict[str, Any] | None,
    active_model_id: str | None,
    candidate_model_id: str | None,
) -> dict[str, Any]:
    retrieval_baseline_metrics = _metric_map(candidate_eval.get("baseline"))
    candidate_metrics = _metric_map(candidate_eval.get("ltr"))
    if baseline_eval is not None and isinstance(baseline_eval.get("ltr"), dict):
        baseline_source = "active_ltr_model"
        baseline_metrics = _metric_map(baseline_eval.get("ltr"))
    else:
        baseline_source = "retrieval_baseline"
        baseline_metrics = dict(retrieval_baseline_metrics)

    deltas: dict[str, float] = {}
    for key in sorted(set(candidate_metrics) | set(baseline_metrics)):
        deltas[key] = round(float(candidate_metrics.get(key, 0.0)) - float(baseline_metrics.get(key, 0.0)), 4)

    return {
        "schema": "mimirq.ltr_rollout_comparison.v1",
        "generated_at": generated_at or _now_utc_iso(),
        "baseline_source": baseline_source,
        "active_model_id": active_model_id,
        "candidate_model_id": candidate_model_id,
        "candidate_eval_summary": {
            "cases_total": int(candidate_eval.get("cases_total") or 0),
            "cases_used": int(candidate_eval.get("cases_used") or 0),
            "k": int(candidate_eval.get("k") or 0),
            "top_k": int(candidate_eval.get("top_k") or 0),
        },
        "baseline_eval_summary": (
            {
                "cases_total": int((baseline_eval or {}).get("cases_total") or 0),
                "cases_used": int((baseline_eval or {}).get("cases_used") or 0),
                "k": int((baseline_eval or {}).get("k") or 0),
                "top_k": int((baseline_eval or {}).get("top_k") or 0),
            }
            if isinstance(baseline_eval, dict)
            else None
        ),
        "retrieval_baseline_metrics": retrieval_baseline_metrics,
        "baseline_metrics": baseline_metrics,
        "candidate_metrics": candidate_metrics,
        "deltas": deltas,
        "activation": {
            "performed": False,
            "status": "manual_review_required",
        },
    }


def build_ltr_rollout_activation_plan(
    *,
    gate: dict[str, Any],
    candidate_model_id: str | None,
    actor_id: str | None = None,
    canary_on_pass: bool = False,
    canary_ratio: float | None = None,
) -> dict[str, Any]:
    if not bool(canary_on_pass):
        return {"performed": False, "status": "manual_review_required"}

    level = str(((gate.get("decision") or {}).get("level") if isinstance(gate, dict) else "") or "").strip().lower()
    if level != "pass":
        return {
            "performed": False,
            "status": "blocked_by_gate",
            "mode": "canary",
            "gate_level": level or "unknown",
            "canary_ratio": 0.0,
        }

    cid = str(candidate_model_id or "").strip()
    if not cid:
        return {
            "performed": False,
            "status": "missing_candidate_model_id",
            "mode": "canary",
            "gate_level": "pass",
            "canary_ratio": 0.0,
        }

    ratio = _safe_float(canary_ratio, min_value=0.0, max_value=1.0)
    if ratio is None:
        ratio = _safe_float((gate.get("decision") or {}).get("canary_ratio"), min_value=0.0, max_value=1.0)
    if ratio is None:
        ratio = 0.0

    return {
        "performed": True,
        "status": "canary_activation_ready",
        "mode": "canary",
        "candidate_model_id": cid,
        "canary_ratio": round(float(ratio), 4),
        "actor_id": (str(actor_id) if str(actor_id or "").strip() else None),
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "FeedbackCaseMaterialization",
    "build_ltr_rollout_activation_plan",
    "build_rollout_comparison",
    "build_rollout_regression_bundle",
    "evaluate_ltr_rollout_gate",
    "materialize_feedback_case",
    "normalize_ltr_rollout_gate_policy_profile",
    "normalize_ltr_rollout_gate_thresholds",
    "normalize_reference_sources",
    "sha256_file",
    "write_json",
]
