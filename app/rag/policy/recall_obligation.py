from __future__ import annotations

from typing import Any

from app.rag.policy.must_recall import normalize_source_keys

RECALL_OBLIGATION_LEDGER_SCHEMA_V1 = "mimirq.recall_obligation_ledger.v1"
MUST_RECALL_PROOF_SCHEMA_V1 = "mimirq.must_recall_proof.v1"


def _to_int(value: Any, *, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except Exception:
        return int(default)


def _build_source_key_obligations(
    *,
    required_source_keys: list[str],
    source_eval: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    matched_by_required = (
        source_eval.get("matched_by_required_source_key")
        if isinstance(source_eval, dict) and isinstance(source_eval.get("matched_by_required_source_key"), dict)
        else {}
    )
    obligations: list[dict[str, Any]] = []
    for key in required_source_keys:
        key_norm = str(key or "").strip()
        if not key_norm:
            continue
        matched = str(matched_by_required.get(key_norm) or "").strip()
        obligations.append(
            {
                "source_key": key_norm,
                "status": ("matched" if matched else "missing"),
                "matched_source_key": (matched or None),
            }
        )
    return obligations


def _build_anchor_obligations(
    *,
    required_anchor_fields: list[str],
    anchor_eval: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    missing_counts = (
        anchor_eval.get("missing_counts")
        if isinstance(anchor_eval, dict) and isinstance(anchor_eval.get("missing_counts"), dict)
        else {}
    )
    obligations: list[dict[str, Any]] = []
    for field in required_anchor_fields:
        name = str(field or "").strip()
        if not name:
            continue
        missing = max(0, _to_int(missing_counts.get(name), default=0))
        obligations.append(
            {
                "field": name,
                "status": ("matched" if missing <= 0 else "missing"),
                "missing_count": int(missing),
            }
        )
    return obligations


def build_recall_obligation_ledger(
    *,
    required_source_keys: list[str] | tuple[str, ...] | None,
    source_eval: dict[str, Any] | None,
    required_anchor_fields: list[str] | tuple[str, ...] | None,
    anchor_eval: dict[str, Any] | None,
) -> dict[str, Any]:
    source_keys = normalize_source_keys(list(required_source_keys or []))
    anchor_fields = normalize_source_keys(list(required_anchor_fields or []))

    source_obligations = _build_source_key_obligations(
        required_source_keys=source_keys,
        source_eval=(source_eval if isinstance(source_eval, dict) else None),
    )
    anchor_obligations = _build_anchor_obligations(
        required_anchor_fields=anchor_fields,
        anchor_eval=(anchor_eval if isinstance(anchor_eval, dict) else None),
    )

    source_missing = len([o for o in source_obligations if str(o.get("status") or "") == "missing"])
    anchor_missing_fields = len([o for o in anchor_obligations if str(o.get("status") or "") == "missing"])
    anchor_missing_any = max(
        0,
        _to_int((anchor_eval or {}).get("missing_any"), default=0) if isinstance(anchor_eval, dict) else 0,
    )
    required_total = int(len(source_obligations) + len(anchor_obligations))
    missing_total = int(source_missing + anchor_missing_fields)
    matched_total = max(0, required_total - missing_total)
    coverage_ratio = (float(matched_total) / float(required_total)) if required_total > 0 else 1.0

    return {
        "schema": RECALL_OBLIGATION_LEDGER_SCHEMA_V1,
        "required_total": required_total,
        "matched_total": matched_total,
        "missing_total": missing_total,
        "coverage_ratio": round(float(coverage_ratio), 6),
        "source_keys": {
            "required": int(len(source_obligations)),
            "missing": int(source_missing),
            "obligations": source_obligations,
        },
        "anchors": {
            "required": int(len(anchor_obligations)),
            "missing_fields": int(anchor_missing_fields),
            "missing_any": int(anchor_missing_any),
            "obligations": anchor_obligations,
        },
    }


def build_must_recall_proof(
    *,
    enabled: bool,
    status: str,
    passed: bool,
    required_source_keys: list[str] | tuple[str, ...] | None,
    required_anchor_fields: list[str] | tuple[str, ...] | None,
    source_eval: dict[str, Any] | None,
    anchor_eval: dict[str, Any] | None,
    fail_reasons: list[str] | tuple[str, ...] | None,
    second_pass: dict[str, Any] | None,
    contract_fail_reason_taxonomy: str,
) -> dict[str, Any]:
    ledger = build_recall_obligation_ledger(
        required_source_keys=required_source_keys,
        source_eval=source_eval,
        required_anchor_fields=required_anchor_fields,
        anchor_eval=anchor_eval,
    )
    source_eval_obj = source_eval if isinstance(source_eval, dict) else {}
    anchor_eval_obj = anchor_eval if isinstance(anchor_eval, dict) else {}
    reasons = [str(v) for v in (fail_reasons or []) if str(v).strip()][:16]
    proof = {
        "schema": MUST_RECALL_PROOF_SCHEMA_V1,
        "enabled": bool(enabled),
        "status": str(status or ""),
        "passed": bool(passed),
        "contract_fail_reason_taxonomy": str(contract_fail_reason_taxonomy or ""),
        "required_source_keys": normalize_source_keys(list(required_source_keys or [])),
        "missing_source_keys": [
            str(v)
            for v in (source_eval_obj.get("missing_source_keys") or [])
            if str(v).strip()
        ][:100],
        "required_anchor_fields": normalize_source_keys(list(required_anchor_fields or [])),
        "anchor_missing_any": max(0, _to_int(anchor_eval_obj.get("missing_any"), default=0)),
        "anchor_missing_counts": (
            dict(anchor_eval_obj.get("missing_counts") or {})
            if isinstance(anchor_eval_obj.get("missing_counts"), dict)
            else {}
        ),
        "fail_reasons": reasons,
        "obligation_ledger": ledger,
        "second_pass": (dict(second_pass or {}) if isinstance(second_pass, dict) else {}),
    }
    return proof


__all__ = [
    "MUST_RECALL_PROOF_SCHEMA_V1",
    "RECALL_OBLIGATION_LEDGER_SCHEMA_V1",
    "build_must_recall_proof",
    "build_recall_obligation_ledger",
]
