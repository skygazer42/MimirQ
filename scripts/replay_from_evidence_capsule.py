#!/usr/bin/env python3
from __future__ import annotations

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


def _recompute_capsule_hash(capsule: dict[str, Any]) -> str:
    from app.rag.core.hashing import stable_json_hash

    payload = dict(capsule)
    payload.pop("capsule_hash", None)
    return stable_json_hash(payload, length=24)


def run(*, capsule_path: Path) -> dict[str, Any]:
    from app.rag.core.evidence_capsule_builder import EVIDENCE_CAPSULE_SCHEMA_V1, validate_evidence_capsule

    capsule = _load_json(capsule_path)
    ok, reason = validate_evidence_capsule(capsule)
    if not ok:
        raise ValueError(f"invalid_capsule:{reason}")
    if str(capsule.get("schema") or "") != EVIDENCE_CAPSULE_SCHEMA_V1:
        raise ValueError("unsupported_capsule_schema")

    expected_hash = str(capsule.get("capsule_hash") or "").strip()
    actual_hash = _recompute_capsule_hash(capsule)
    hash_valid = bool(expected_hash and expected_hash == actual_hash)

    retrieval_summary = capsule.get("retrieval_summary") if isinstance(capsule.get("retrieval_summary"), dict) else {}
    retrieval_contract = capsule.get("retrieval_contract") if isinstance(capsule.get("retrieval_contract"), dict) else {}
    must_recall = capsule.get("must_recall") if isinstance(capsule.get("must_recall"), dict) else {}

    replay_request = {
        "query": str(capsule.get("query_for_retrieval") or ""),
        "rag_config": {
            "retrieval_mode": str(retrieval_summary.get("retrieval_mode") or ""),
            "retrieval_contract_mode": str(retrieval_contract.get("mode") or ""),
            "must_recall": bool(must_recall.get("enabled")),
        },
        "expected_citation_hashes": [str(v) for v in list(capsule.get("citation_hashes") or []) if str(v).strip()],
    }

    return {
        "schema": "mimirq.evidence_replay.v1",
        "capsule_path": str(capsule_path),
        "capsule_hash": expected_hash,
        "capsule_hash_recomputed": actual_hash,
        "capsule_hash_valid": hash_valid,
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
    args = ap.parse_args(argv)

    try:
        result = run(capsule_path=Path(str(args.capsule)).resolve())
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
