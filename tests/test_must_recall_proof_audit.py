from __future__ import annotations

from scripts.must_recall_proof_audit import audit_must_recall_proofs


def _valid_item() -> dict:
    return {
        "retrieval_trace": {
            "contract_diagnostics": {
                "must_recall": {
                    "proof": {
                        "schema": "mimirq.must_recall_proof.v1",
                        "enabled": True,
                        "status": "passed",
                        "passed": True,
                        "missing_source_keys": [],
                        "anchor_missing_any": 0,
                        "fail_reasons": [],
                        "obligation_ledger": {
                            "schema": "mimirq.recall_obligation_ledger.v1",
                            "missing_total": 0,
                        },
                    }
                }
            }
        }
    }


def test_audit_must_recall_proof_reports_ok() -> None:
    report = audit_must_recall_proofs({"items": [{"item_meta": _valid_item()}]})
    assert report["schema"] == "mimirq.must_recall_proof_audit.v1"
    assert report["proofs_found"] == 1
    assert report["proofs_invalid"] == 0
    assert report["ok"] is True


def test_audit_must_recall_proof_detects_inconsistent_pass_status() -> None:
    bad = _valid_item()
    proof = (
        bad.get("retrieval_trace", {})
        .get("contract_diagnostics", {})
        .get("must_recall", {})
        .get("proof", {})
    )
    proof["missing_source_keys"] = ["inventory"]
    proof["obligation_ledger"]["missing_total"] = 1

    report = audit_must_recall_proofs([bad])
    assert report["proofs_found"] == 1
    assert report["proofs_invalid"] == 1
    assert report["ok"] is False
    errors = list((report.get("invalid") or [])[0].get("errors") or [])
    assert any("passed_but_missing_source_keys" in e for e in errors)
