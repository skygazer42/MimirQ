#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _load_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("capsule_root_not_object")
    return obj


def run(*, capsule_path: Path, strict: bool = True, verify_signature: bool = False) -> dict[str, Any]:
    from app.rag.core.evidence_capsule_builder import (
        EVIDENCE_CAPSULE_SCHEMA_V1,
        recompute_capsule_hash,
        validate_evidence_capsule,
        verify_evidence_capsule_signature,
    )

    capsule = _load_json(capsule_path)
    ok, reason = validate_evidence_capsule(
        capsule,
        strict=bool(strict),
        verify_signature=bool(verify_signature),
    )
    if not ok:
        raise ValueError(f"invalid_capsule:{reason}")
    if str(capsule.get("schema") or "") != EVIDENCE_CAPSULE_SCHEMA_V1:
        raise ValueError("unsupported_capsule_schema")

    expected_hash = str(capsule.get("capsule_hash") or "").strip()
    actual_hash = recompute_capsule_hash(capsule)
    hash_valid = bool(expected_hash and expected_hash == actual_hash)
    signature_valid = None
    signature_reason = ""
    if verify_signature:
        signature_valid, signature_reason = verify_evidence_capsule_signature(capsule)

    retrieval_summary = capsule.get("retrieval_summary") if isinstance(capsule.get("retrieval_summary"), dict) else {}
    retrieval_contract = (
        capsule.get("retrieval_contract") if isinstance(capsule.get("retrieval_contract"), dict) else {}
    )
    must_recall = capsule.get("must_recall") if isinstance(capsule.get("must_recall"), dict) else {}

    # Prefer must-recall proof inside retrieval_trace when present; this keeps replay requests
    # self-contained even when the capsule-level must_recall summary is compact.
    proof: dict[str, Any] = {}
    trace = capsule.get("retrieval_trace") if isinstance(capsule.get("retrieval_trace"), dict) else {}
    if isinstance(trace, dict):
        contract_diag = trace.get("contract_diagnostics") if isinstance(trace.get("contract_diagnostics"), dict) else {}
        mr = (
            contract_diag.get("must_recall")
            if isinstance(contract_diag, dict) and isinstance(contract_diag.get("must_recall"), dict)
            else {}
        )
        p = mr.get("proof") if isinstance(mr, dict) and isinstance(mr.get("proof"), dict) else {}
        proof = dict(p) if isinstance(p, dict) else {}

    required_source_keys = (
        [str(v) for v in (proof.get("required_source_keys") or []) if str(v).strip()] if isinstance(proof, dict) else []
    )
    required_anchor_fields = (
        [str(v) for v in (proof.get("required_anchor_fields") or []) if str(v).strip()]
        if isinstance(proof, dict)
        else []
    )
    if not required_anchor_fields:
        required_anchor_fields = [str(v) for v in (must_recall.get("required_anchor_fields") or []) if str(v).strip()]

    replay_request = {
        "query": str(capsule.get("query_for_retrieval") or ""),
        "rag_config": {
            "retrieval_mode": str(retrieval_summary.get("retrieval_mode") or ""),
            "retrieval_contract_mode": str(retrieval_contract.get("mode") or ""),
            "must_recall": bool(must_recall.get("enabled")),
            "must_recall_expected_source_keys": required_source_keys,
            "must_recall_required_anchor_fields": required_anchor_fields,
        },
        "expected_citation_hashes": [str(v) for v in (capsule.get("citation_hashes") or []) if str(v).strip()],
    }

    return {
        "schema": "mimirq.evidence_replay.v1",
        "capsule_path": str(capsule_path),
        "capsule_hash": expected_hash,
        "capsule_hash_recomputed": actual_hash,
        "capsule_hash_valid": hash_valid,
        "signature_valid": signature_valid,
        "signature_reason": signature_reason or None,
        "replay_request": replay_request,
        "must_recall": {
            "status": str(must_recall.get("status") or ""),
            "passed": bool(must_recall.get("passed")),
            "fail_reasons": list(must_recall.get("fail_reasons") or []),
        },
        "retrieval_summary": {
            "retrieval_config_hash": str(retrieval_summary.get("retrieval_config_hash") or ""),
            "citations_count": int(retrieval_summary.get("citations_count") or 0),
            "abstain_triggered": bool(retrieval_summary.get("abstain_triggered")),
            "abstain_reason": str(retrieval_summary.get("abstain_reason") or ""),
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build replay payload from an evidence capsule JSON.")
    ap.add_argument("--capsule", required=True, help="Path to evidence capsule JSON")
    ap.add_argument("--out", default="", help="Optional output path")
    ap.add_argument("--compact", action="store_true", help="Print compact JSON")
    ap.add_argument("--no-strict", action="store_true", help="Disable strict integrity checks")
    ap.add_argument("--verify-signature", action="store_true", help="Require signature verification")
    args = ap.parse_args(argv)

    try:
        result = run(
            capsule_path=Path(str(args.capsule)).resolve(),
            strict=not bool(args.no_strict),
            verify_signature=bool(args.verify_signature),
        )
    except Exception as exc:
        print(f"[replay_from_evidence_capsule] ERROR: {exc}", file=sys.stderr)
        return 1

    if str(args.out or "").strip():
        out_path = Path(str(args.out)).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.compact:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
