from __future__ import annotations

import json
import uuid


def test_persist_retrieval_audit_snapshot_sanitizes_and_posts(tmp_path):  # noqa: ANN001
    import scripts.persist_retrieval_audit_snapshot as mod

    summary_path = tmp_path / "readiness.json"
    dataset_id = str(uuid.uuid4())
    summary_path.write_text(
        json.dumps(
            {
                "summary": {"passed": False},
                "retrieval_audit": {
                    "status": "failed",
                    "plugin_refs": ["plugin:demo@1.0.0:chunk", "plugin:demo@1.0.0:chunk"],
                    "plugin_package_hashes": ["sha256:abc123"],
                    "failure_categories": {"scope": 1, "raw_context": 99},
                    "gates": [
                        {
                            "name": "external_probe",
                            "status": "failed",
                            "metrics": {
                                "hit_at_1": 0.5,
                                "expected_metadata_hit_rate": 0.75,
                                "raw_context": "SHOULD_NOT_SEND_RAW_CHUNK",
                                "api_key": "SHOULD_NOT_SEND_SECRET",
                            },
                            "failed_conditions": ["expected_metadata_hit_rate"],
                            "source": "external_gate",
                        }
                    ],
                    "raw_query": "SHOULD_NOT_SEND_QUERY",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls: list[dict] = []

    def _fake_request_json(**kwargs):  # noqa: ANN202
        calls.append(kwargs)
        return kwargs["payload"]

    response = mod.persist_retrieval_audit_snapshot(
        summary_path=summary_path,
        base_url="http://mimirq.test/api/v1",
        dataset_id=dataset_id,
        tenant_id="tenant-1",
        account_id="account-1",
        user_id="user-1",
        bearer="secret-token",
        timeout=12.5,
        request_json=_fake_request_json,
    )

    assert response["status"] == "failed"
    assert len(calls) == 1
    call = calls[0]
    assert call["method"] == "PUT"
    assert call["url"] == f"http://mimirq.test/api/v1/datasets/{dataset_id}/retrieval-audit"
    assert call["timeout"] == 12.5
    assert call["headers"]["Authorization"] == "Bearer secret-token"
    assert call["headers"]["X-Tenant-ID"] == "tenant-1"
    assert call["headers"]["X-Account-ID"] == "account-1"
    assert call["headers"]["X-User-ID"] == "user-1"
    assert call["payload"]["plugin_refs"] == ["plugin:demo@1.0.0:chunk"]
    assert call["payload"]["failure_categories"] == {"scope": 1}
    assert call["payload"]["gates"][0]["metrics"] == {
        "hit_at_1": 0.5,
        "expected_metadata_hit_rate": 0.75,
    }
    assert "SHOULD_NOT_SEND" not in str(call["payload"])


def test_persist_retrieval_audit_snapshot_rejects_summary_without_audit(tmp_path) -> None:
    import pytest

    import scripts.persist_retrieval_audit_snapshot as mod

    summary_path = tmp_path / "readiness.json"
    summary_path.write_text('{"summary":{"passed":true}}', encoding="utf-8")

    with pytest.raises(ValueError, match="retrieval_audit"):
        mod.load_retrieval_audit_payload(summary_path)
