#!/usr/bin/env python3
"""
Offline must-recall proof auditor.

Input payload can be:
- a retrieval response object
- a regression run detail object ({run, items})
- a list of retrieval response objects

The auditor validates proof object shape and simple consistency constraints.
"""


import argparse
import json
import sys
from pathlib import Path
from typing import Any

from app.rag.policy.recall_obligation import (
    MUST_RECALL_PROOF_SCHEMA_V1,
    RECALL_OBLIGATION_LEDGER_SCHEMA_V1,
)


def _extract_must_recall_proof(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    direct = item.get("must_recall_proof")
    if isinstance(direct, dict):
        return direct

    metrics = item.get("metrics")
    if isinstance(metrics, dict) and isinstance(metrics.get("must_recall_proof"), dict):
        return dict(metrics.get("must_recall_proof") or {})

    query_debug = item.get("query_debug")
    if isinstance(query_debug, dict):
        rc = query_debug.get("retrieval_contract")
        if isinstance(rc, dict) and isinstance(rc.get("must_recall_proof"), dict):
            return dict(rc.get("must_recall_proof") or {})

    trace = item.get("retrieval_trace")
    if isinstance(trace, dict):
        contract_diag = trace.get("contract_diagnostics")
        if isinstance(contract_diag, dict):
            must_recall = contract_diag.get("must_recall")
            if isinstance(must_recall, dict) and isinstance(must_recall.get("proof"), dict):
                return dict(must_recall.get("proof") or {})
    return None


def _collect_items(payload: Any) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    if isinstance(payload, dict):
        if isinstance(payload.get("items"), list):
            for idx, raw in enumerate(payload.get("items") or []):
                if not isinstance(raw, dict):
                    continue
                # Regression item detail may keep retrieval payload in item_meta.
                item_meta = raw.get("item_meta") if isinstance(raw.get("item_meta"), dict) else {}
                source = item_meta if item_meta else raw
                out.append((f"items[{idx}]", source))
            if out:
                return out
        out.append(("root", payload))
        return out
    if isinstance(payload, list):
        for idx, raw in enumerate(payload):
            if isinstance(raw, dict):
                out.append((f"list[{idx}]", raw))
    return out


def _validate_proof(label: str, proof: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if str(proof.get("schema") or "") != MUST_RECALL_PROOF_SCHEMA_V1:
        errors.append(f"{label}:invalid_schema")

    ledger = proof.get("obligation_ledger")
    if not isinstance(ledger, dict):
        errors.append(f"{label}:missing_obligation_ledger")
    else:
        if str(ledger.get("schema") or "") != RECALL_OBLIGATION_LEDGER_SCHEMA_V1:
            errors.append(f"{label}:invalid_obligation_ledger_schema")

    passed = bool(proof.get("passed"))
    enabled = bool(proof.get("enabled"))
    status = str(proof.get("status") or "")
    missing_source_keys = list(proof.get("missing_source_keys") or [])
    anchor_missing_any = int(proof.get("anchor_missing_any") or 0)
    fail_reasons = [str(v) for v in (proof.get("fail_reasons") or []) if str(v).strip()]

    if enabled and passed:
        if missing_source_keys:
            errors.append(f"{label}:passed_but_missing_source_keys")
        if anchor_missing_any > 0:
            errors.append(f"{label}:passed_but_anchor_missing")
        if isinstance(ledger, dict) and int(ledger.get("missing_total") or 0) > 0:
            errors.append(f"{label}:passed_but_obligation_missing")
    if enabled and status == "failed" and not fail_reasons:
        errors.append(f"{label}:failed_without_reasons")
    return errors


def audit_must_recall_proofs(payload: Any) -> dict[str, Any]:
    items = _collect_items(payload)
    proofs_found = 0
    invalid: list[dict[str, Any]] = []

    for label, item in items:
        proof = _extract_must_recall_proof(item)
        if not isinstance(proof, dict):
            continue
        proofs_found += 1
        errs = _validate_proof(label, proof)
        if errs:
            invalid.append(
                {
                    "item": label,
                    "errors": errs[:12],
                    "status": str(proof.get("status") or ""),
                    "passed": bool(proof.get("passed")),
                }
            )

    return {
        "schema": "mimirq.must_recall_proof_audit.v1",
        "records_total": int(len(items)),
        "proofs_found": int(proofs_found),
        "proofs_invalid": int(len(invalid)),
        "proofs_valid": int(max(0, proofs_found - len(invalid))),
        "ok": bool(proofs_found > 0 and len(invalid) == 0),
        "invalid": invalid[:50],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit must-recall proof payloads")
    parser.add_argument("--input", required=True, help="Input JSON path")
    parser.add_argument("--out", default="", help="Optional output JSON path")
    parser.add_argument("--compact", action="store_true", help="Print compact JSON")
    args = parser.parse_args(argv)

    try:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
        report = audit_must_recall_proofs(payload)
    except Exception as exc:
        print(f"[must_recall_proof_audit] ERROR: {exc}", file=sys.stderr)
        return 1

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.compact:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))

    return 0 if bool(report.get("ok")) else 2


if __name__ == "__main__":
    raise SystemExit(main())

